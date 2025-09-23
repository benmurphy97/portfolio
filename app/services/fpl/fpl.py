import pandas as pd
import numpy as np
from collections import defaultdict
from app.services.fpl.cache import fetch_fpl_with_cache

def get_bench_points_summary(league_id):

    print("Getting bench points")
    # api calls

    league_details_url = f"https://draft.premierleague.com/api/league/{league_id}/details"
    league_details = fetch_fpl_with_cache(url=league_details_url, cache_key=f"draft_league_{league_id}_details")


    # get finished gameweeks from classic fpl
    classic_bootstrap_url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    classic_bootstrap = fetch_fpl_with_cache(url=classic_bootstrap_url, cache_key="classic_bootstrap")


    draft_bootstrap_url = "https://draft.premierleague.com/api/bootstrap-static"
    draft_bootstrap = fetch_fpl_with_cache(url=draft_bootstrap_url, cache_key="draft_bootstrap")


    # use classic fpl api to get points scored per finished week for every player
    finished_gws = [e["id"] for e in classic_bootstrap["events"] if e["finished"]]
    print(f"DEBUG {finished_gws}")
    points_lookup_by_gw = {}
    for gw in finished_gws:
        gw_url = f"https://fantasy.premierleague.com/api/event/{gw}/live/"
        gw_data = fetch_fpl_with_cache(url=gw_url, cache_key=f"classic_event_{gw}_live")
        # mapping of classic fpl api to points scored
        points_lookup_by_gw[gw] = {e["id"]: e["stats"]["total_points"] for e in gw_data["elements"]}


    # get entry ids in the league
    entries = league_details["league_entries"]
    entry_ids = [e["entry_id"] for e in entries]

    # map entry_id → team name / manager name
    entry_info = {e["entry_id"]: {"entry_name": e["entry_name"],
                                  "player_name": f"{e['player_first_name']} {e['player_last_name']}"
                            } for e in entries}

    # create a draft api to classic api id lookup
    # draft id to name
    draft_id_to_name = {e['id']: f"{e['first_name']} {e['second_name']} {e['web_name']}" for e in draft_bootstrap['elements']}
    
    # classic id to name
    classic_name_to_id = {f"{e['first_name']} {e['second_name']} {e['web_name']}": e['id'] for e in classic_bootstrap['elements']}

    # create a lookup for draft id to player info for later
    player_lookup = {p["id"]: p for p in draft_bootstrap["elements"]}


    # --- 5. Loop over all teams and GWs to collect picks and points ---
    records = []
    
    for entry_id in entry_ids:
        if entry_id is not None:
            for gw in finished_gws:
                # get picks for each team
                entry_gw_url = f"https://draft.premierleague.com/api/entry/{entry_id}/event/{gw}"
                entry_gw_data = fetch_fpl_with_cache(url=entry_gw_url, cache_key=f"draft_entry_{entry_id}_gw_{gw}")

                picks = entry_gw_data["picks"] # list of elements by draft fpl id

                for pick in picks:
                    
                    # convert draft id to classic id
                    draft_id = pick['element']
                    classic_id = classic_name_to_id[draft_id_to_name[draft_id]]
                    event_points = points_lookup_by_gw[gw][classic_id]

                    player = player_lookup[draft_id]

                    # determine on pitch based on position
                    on_pitch = pick["position"] <= 11

                    records.append({
                            "entry_id": entry_id,
                            "entry_name": entry_info[entry_id]["entry_name"],
                            "manager": entry_info[entry_id]["player_name"],
                            "gameweek": gw,
                            "classic_fpl_player_id": classic_id,
                            "draft_fpl_player_id": draft_id,
                            "player_name": player["web_name"],
                            "position": pick["position"],
                            "event_points": event_points,
                            "on_pitch": on_pitch
                        })

    # --- 6. Create DataFrames ---
    df = pd.DataFrame(records)

    # --- 7. Summary per GW: points on pitch vs bench ---
    summary = (
        df.groupby(["entry_id", "entry_name", "manager", "gameweek", "on_pitch"])["event_points"]
        .sum()
        .unstack(fill_value=0)
        .rename(columns={True: "points_on_pitch", False: "points_on_bench"})
        .reset_index()
    )

    # --- 8. Season cumulative totals per team ---
    season_totals = (
        summary.groupby(["entry_id", "entry_name", "manager"])[["points_on_pitch", "points_on_bench"]]
            .sum()
            .reset_index()
    )
    season_totals["total_points"] = season_totals["points_on_pitch"] + season_totals["points_on_bench"]

    season_totals.rename(columns={'entry_name': 'Team Name',
                                  'manager': 'Manager',
                                  'points_on_pitch': 'Points on Pitch',
                                  'points_on_bench': 'Points on Bench',
                                  'total_points': 'Total Points All Players'}, inplace=True)
    
    return season_totals[['Team Name', 'Manager', 
                          'Points on Pitch', 'Points on Bench', 
                          'Total Points All Players']]


def get_current_standings(league_id):
    league_details_url = f"https://draft.premierleague.com/api/league/{league_id}/details"
    league_details = fetch_fpl_with_cache(url=league_details_url, cache_key=f"draft_league_{league_id}_details")

    # create dataframe of current standings
    s_df = pd.DataFrame(league_details['standings'])

    ids = [i['id'] for i in league_details['league_entries']]
    names = [i['short_name'] for i in league_details['league_entries']]
    id_name_map = {i:v for i,v in zip(ids,names)}

    s_df['player'] = s_df['league_entry'].apply(lambda x: id_name_map[x])
    player_initials = s_df['player'].values.tolist()

    current_standings = s_df[['player', 'rank', 
                            'matches_won', 'matches_lost', 'matches_drawn', 
                            'points_for', 'points_against', 
                            'total']].copy()
    current_standings.rename(columns={'rank': 'Position',
                                        'player': 'Player',
                                        'matches_won': 'W',
                                        'matches_lost': 'L',
                                        'matches_drawn': 'D',
                                        'points_for': 'FPL Points For',
                                        'points_against': 'FPL Points Against',
                                        'total': 'Points'}, inplace=True)
    
    current_standings_row_data=list(current_standings.values.tolist())
    current_standings_col_names = current_standings.columns.values
    
    # scatter plot of avarage points for vs average points against for each player
    s_df['average_points_for'] = s_df['points_for'] / (s_df['matches_won'] + s_df['matches_lost'] + s_df['matches_drawn'])
    s_df['average_points_against'] = s_df['points_against'] / (s_df['matches_won'] + s_df['matches_lost'] + s_df['matches_drawn'])

    avg_pts_for = s_df['average_points_for'].values.tolist()
    avg_pts_against = s_df['average_points_against'].values.tolist()

    scatter_pts_for_vs_agnst_data_dict = []
    for i,v in zip(avg_pts_for, avg_pts_against):
        d = {'x': i, 'y': v}
        scatter_pts_for_vs_agnst_data_dict.append(d)

    return current_standings_row_data, current_standings_col_names,\
            scatter_pts_for_vs_agnst_data_dict, \
            player_initials



def get_expected_standings(league_id):
    league_details_url = f"https://draft.premierleague.com/api/league/{league_id}/details"
    league_details = fetch_fpl_with_cache(url=league_details_url, cache_key=f"draft_league_{league_id}_details")

    data_json = league_details

    ids = [i['id'] for i in league_details['league_entries']]
    names = [i['short_name'] for i in league_details['league_entries']]
    id_name_map = {i:v for i,v in zip(ids,names)}

    n_players = len(league_details['league_entries'])

    # expected league table
    matches = pd.DataFrame(data_json['matches'])

    matches1 = matches.loc[matches['finished']==True]
    matches1.drop(columns=['finished', 'started', 'winning_league_entry', 'winning_method'], inplace=True)
    matches1.rename(columns={'event': 'week',
                            'league_entry_1': 'player',
                            'league_entry_1_points': 'points_for',
                            'league_entry_2': 'opponent',
                            'league_entry_2_points': 'points_against'},
                inplace=True)


    matches2 = matches.loc[matches['finished']==True]
    matches2.drop(columns=['finished', 'started', 'winning_league_entry', 'winning_method'], inplace=True)
    matches2.rename(columns={'event': 'week',
                            'league_entry_1': 'opponent',
                            'league_entry_1_points': 'points_against',
                            'league_entry_2': 'player',
                            'league_entry_2_points': 'points_for'},
                inplace=True)

    matches_df = pd.concat([matches1, matches2]).sort_values(by=['week', 'points_for'], ascending=[True, False]).reset_index(drop=True)

    # get the rank of each player's score in the gameweek
    matches_df['points_for_week_rank'] = matches_df.groupby('week')['points_for'].rank(ascending=False, method='max')
    matches_df['points_against_week_rank'] = matches_df.groupby('week')['points_against'].rank(ascending=False, method='min')

    matches_df['player'] = matches_df['player'].apply(lambda x: id_name_map[x].strip())

    matches_df['number_of_opponents_beaten_in_week'] = n_players-matches_df['points_for_week_rank']
    matches_df['number_of_opponents_drawn_to_in_week'] = matches_df[['week', 'points_for']].duplicated(keep=False).astype(int).values

    matches_df['prob_winning_week'] = matches_df['number_of_opponents_beaten_in_week'].apply(lambda x: x/(n_players-1))
    matches_df['prob_losing_week'] = 1 - matches_df['prob_winning_week']

    matches_df['expected_points_win'] = matches_df['prob_winning_week'] * 3
    matches_df['expected_points_draw'] = matches_df['number_of_opponents_drawn_to_in_week'].apply(lambda x: (x/(n_players-1)) * 1 )

    matches_df['expected_points'] = matches_df['expected_points_win'] + matches_df['expected_points_draw']

    s_df = pd.DataFrame(data_json['standings'])
    s_df['player'] = s_df['league_entry'].apply(lambda x: id_name_map[x])

    # aggregate epected points by player
    expected_standing = matches_df.groupby('player')['expected_points'].sum().round(2).reset_index()

    # get real standings
    standings = s_df[['player', 'rank', 'total']].sort_values('player').reset_index(drop=True)
    standings['player'] = standings['player'].str.strip() # format player name

    standings['expected_points'] = expected_standing['expected_points']
    standings['over/under performance'] = standings['total']-standings['expected_points']
    standings.rename({'total': 'actual_points'}, inplace=True)
    standings.columns = ['Player', 'Actual Position', 'Actual Points', 'Expected Points', 'Over/Under Performance']

    standings = standings.sort_values(by='Expected Points', ascending=False)

    # asign expected rank position
    standings['Expected Position'] = standings['Expected Points'].rank(ascending=False).astype(int)

    standings = standings[['Player', 'Expected Position', 'Expected Points', 'Actual Points', 'Actual Position', 'Over/Under Performance']]

    return standings


#  use monte carlo simulation to preict final league table standings for a league
def get_predicted_standings(league_id, num_simulations=50):

    league_details_url = f"https://draft.premierleague.com/api/league/{league_id}/details"
    league_details = fetch_fpl_with_cache(url=league_details_url, cache_key=f"draft_league_{league_id}_details")

    standings = pd.DataFrame(league_details['standings'])
    matches = pd.DataFrame(league_details['matches'])

    # --- Identify remaining fixtures ---
    upcoming = matches[~matches['finished']]

    # --- Compute average points scored per game so far ---
    standings['games_played'] = (
        standings[['matches_won', 'matches_lost', 'matches_drawn']].sum(axis=1)
    )
    standings['avg_points_for'] = standings['points_for'] / standings['games_played']

    team_strength = standings.set_index('league_entry')['avg_points_for'].to_dict()

    # --- Simulation storage ---
    rank_counts = defaultdict(lambda: np.zeros(len(standings), dtype=int))

    # --- Run simulations ---
    for _ in range(num_simulations):
        # Start from current points
        sim_table = standings[['league_entry', 'total']].copy()
        sim_table = sim_table.set_index('league_entry')

        # Simulate each remaining fixture
        for _, match in upcoming.iterrows():
            t1, t2 = match['league_entry_1'], match['league_entry_2']
            mu1, mu2 = team_strength[t1], team_strength[t2]

            score1 = np.random.poisson(mu1)
            score2 = np.random.poisson(mu2)

            if score1 > score2:
                sim_table.loc[t1, 'total'] += 3
            elif score2 > score1:
                sim_table.loc[t2, 'total'] += 3
            else:
                sim_table.loc[t1, 'total'] += 1
                sim_table.loc[t2, 'total'] += 1

        # Assign ranks
        sim_table['rank'] = sim_table['total'].rank(method="min", ascending=False).astype(int)

        for team_id, row in sim_table.iterrows():
            final_rank = row['rank'] - 1  # zero-based index
            rank_counts[team_id][final_rank] += 1

    # --- Convert to probability DataFrame ---
    results = []
    id_name_map = {e['id']: e['short_name'] for e in league_details['league_entries']}
    for team_id, counts in rank_counts.items():
        probs = counts / num_simulations
        results.append([id_name_map[team_id]] + probs.tolist())

    num_teams = len(standings)
    columns = ['Team'] + ["1st", "2nd", "3rd"] + [f"{i+1+3}th" for i in range(num_teams-3)]
    probs_df = pd.DataFrame(results, columns=columns)

    return probs_df.sort_values(by=["1st", "2nd", columns[-1]], ascending=[False, False, True]).reset_index(drop=True)


# central function to create all charts for chart.html
def get_fpl_charts(league_id):

    # bench points 
    bench_points_table = get_bench_points_summary(league_id)
    bench_row_data=list(bench_points_table.values.tolist())
    bench_col_names = bench_points_table.columns.values
    
    # current standings
    current_standings_row_data, current_standings_col_names, \
        scatter_pts_for_vs_agnst_data_dict,\
            player_initials = get_current_standings(league_id)
    
    # expected standings
    expected_standings = get_expected_standings(league_id)
    expected_standings_row_data = list(round(expected_standings,3).values.tolist())
    expected_standings_col_names = expected_standings.columns.values

    predicted_standings = get_predicted_standings(league_id)
    print(predicted_standings)
    
    return bench_row_data, bench_col_names, \
            current_standings_row_data, current_standings_col_names, \
            scatter_pts_for_vs_agnst_data_dict, \
            player_initials, \
            expected_standings_row_data, expected_standings_col_names

