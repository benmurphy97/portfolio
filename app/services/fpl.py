from urllib.request import urlopen 
import json
import pandas as pd
import os
import time

CACHE_DIR = "cache"
CACHE_TTL = 60 * 60 # 60 secs * 60 minutes


# get data from api, use cache if data exists already
def fetch_fpl_with_cache(url, cache_key):

    # if cache folder does not exist
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

    # construct cache file path
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")

    # use cache data if exists
    if os.path.exists(cache_file):
        mtime = os.path.getmtime(cache_file)
        # if the file has been modified recently, load the data from it
        if time.time() - mtime < CACHE_TTL:
            # read from cache
            with open(cache_file, "r") as f:
                return json.load(f)

    # if data is not in cache, load the data into cache and return it
    response =  urlopen(url)
    data = json.loads(response.read())

    # write to cache
    with open(cache_file, "w") as f:
        json.dump(data, f)

    return data



def get_bench_points_summary(league_id):

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

    



# central function to create all charts for chart.html
def build_fpl_charts(league_id):

    # bench points 
    bench_points_table = get_bench_points_summary(league_id)
    bench_row_data=list(bench_points_table.values.tolist())
    bench_col_names = bench_points_table.columns.values
    
    # current standings
    current_standings_row_data, current_standings_col_names, scatter_pts_for_vs_agnst_data_dict, player_initials = get_current_standings(league_id)
    
    # expected standings


    return bench_points_table, current_standings_table