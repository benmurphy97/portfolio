from flask import render_template, request, redirect, url_for, flash
from app import app
from app.forms import LeagueIDForm
import json
from urllib.request import urlopen 
import pandas as pd

import feedparser
from bs4 import BeautifulSoup  # for parsing HTML

from datetime import datetime
import time

@app.route('/')
@app.route('/home')
def home():
    return render_template('home.html', title='Home')


CACHE = {
    "articles": [],
    "last_fetch": 0
}
# ARTICLE_CACHE_DURATION = 300  # 5 minutes / 300 seconds
ARTICLE_CACHE_DURATION = 604800

def fetch_articles():
    # define medium username
    medium_username = "benmurphy_29746"
    feed_url = f"https://medium.com/feed/@{medium_username}"

    # Parse Medium RSS feed
    feed = feedparser.parse(feed_url)

    articles_data = []
    for entry in feed.entries:

        # Parse HTML in summary to find first image
        soup = BeautifulSoup(entry.summary, "html.parser")
        img_tag = soup.find("img")
        thumbnail = img_tag["src"] if img_tag else None

        # Format date to remove time
        published_date = datetime.strptime(entry.published, "%a, %d %b %Y %H:%M:%S %Z")
        formatted_date = published_date.strftime("%d %b %Y")  # e.g. "02 Aug 2024"

        articles_data.append({
            "title": entry.title,
            "link": entry.link,
            "description": soup.get_text(),  # plain text from summary
            "published": formatted_date,
            "thumbnail": thumbnail
        })

    return articles_data


# route for pulling my articles directly from Medium
@app.route("/articles")
def articles():

    now = time.time()

    # check how long has elapsed between queries
    if now - CACHE['last_fetch'] > ARTICLE_CACHE_DURATION:
        CACHE['articles'] = fetch_articles()
        CACHE['last_fetch'] = now
    
    return render_template("articles.html", articles=CACHE['articles'])

@app.route('/fetch_fpl_data', methods=['GET', 'POST'])
def fetch_fpl_data(league_data):

    # get entry ids in the league
    entries = league_data["league_entries"]
    entry_ids = [e["entry_id"] for e in entries]

    # map entry_id → team name / manager name
    entry_info = {e["entry_id"]: {
        "entry_name": e["entry_name"],
        "player_name": f"{e['player_first_name']} {e['player_last_name']}"
    } for e in entries}

    # --- 2. Get Draft player info ---
    draft_bootstrap_url = "https://draft.premierleague.com/api/bootstrap-static"
    response = urlopen(draft_bootstrap_url) 
    draft_bootstrap = json.loads(response.read())
    players = draft_bootstrap["elements"]
    player_lookup = {p["id"]: p for p in players}

    # --- 3. Get finished gameweeks from Classic FPL ---
    fpl_bootstrap_url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    response = urlopen(fpl_bootstrap_url) 
    fpl_bootstrap = json.loads(response.read())
    finished_gws = [e["id"] for e in fpl_bootstrap["events"] if e["finished"]]

    # --- 4. Pre-fetch Classic points for all finished GWs ---
    points_lookup_by_gw = {}
    for gw in finished_gws:
        url = f"https://fantasy.premierleague.com/api/event/{gw}/live/"
        response = urlopen(url) 
        gw_data = json.loads(response.read())
        points_lookup_by_gw[gw] = {e["id"]: e["stats"]["total_points"] for e in gw_data["elements"]}

    print(f"GW {gw} keys: {list(points_lookup_by_gw[gw].keys())[:20]}")  # first 20 IDs
    print("Player 661 in points_lookup?", 661 in points_lookup_by_gw[gw])
    print("Player 661 points:", points_lookup_by_gw[gw].get(661))

    # --- 5. Loop over all teams and GWs to collect picks and points ---
    records = []
    
    # https://draft.premierleague.com/api/entry/124780/event/1
    for entry_id in entry_ids:
        for gw in finished_gws:
            draft_url = f"https://draft.premierleague.com/api/entry/{entry_id}/event/{gw}"            
            response = urlopen(draft_url) 
            draft_data = json.loads(response.read())

            picks = draft_data["picks"]

            for pick in picks:
                player_id = pick["element"]
                player = player_lookup[player_id]

                # determine on pitch based on position
                on_pitch = pick["position"] <= 11

                # official FPL points (no multiplier/captain in Draft)
                event_points = points_lookup_by_gw[gw][player_id]

                records.append({
                    "entry_id": entry_id,
                    "entry_name": entry_info[entry_id]["entry_name"],
                    "manager": entry_info[entry_id]["player_name"],
                    "gameweek": gw,
                    "player_id": player_id,
                    "player_name": player["web_name"],
                    "position": pick["position"],
                    "event_points": event_points,
                    "on_pitch": on_pitch
                })


    # --- 6. Create DataFrames ---
    df = pd.DataFrame(records)
    print(df.iloc[179:220])

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


    # --- 9. Display results ---
    print("Per-GW summary (first 5 rows):")
    print(summary.head(20))

    print("\nSeason totals:")
    print(season_totals.sort_values("total_points", ascending=False))



@app.route('/inputLeagueID', methods=['GET', 'POST'])
def inputLeagueID():

    form = LeagueIDForm()

    if form.validate_on_submit():
        return redirect(url_for('chart'))
    
    return render_template('inputLeagueID.html', title='League ID Input', form=form)


@app.route('/chart', methods=['GET', 'POST'])
def chart():
    
    league_id = request.form.get('league_id')

    # the league id enterred may be valid input but the number doesnt correspond to a League ID
    # IDs are created iteratively - most recently created league will have the largest ID number but we dont know what the largest one is
    # define url for fpl api
    url = f"https://draft.premierleague.com/api/league/{league_id}/details"

    try:
        # store the response of URL 
        response = urlopen(url) 
    except:
        flash('The League ID enterred could not be loaded. Try again with a different League ID.')
        return redirect(url_for('inputLeagueID'))
    
    # storing the JSON response  
    data_json = json.loads(response.read())

    league_name = data_json['league']['name']
    # if scoring is head-to-head format
    if data_json['league']['scoring'] == 'h':

        fetch_fpl_data(data_json)

        # create id:name lookup
        ids = [i['id'] for i in data_json['league_entries']]
        names = [i['short_name'] for i in data_json['league_entries']]
        id_name_map = {i:v for i,v in zip(ids,names)}


        # create dataframe of current standings
        s_df = pd.DataFrame(data_json['standings'])

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
        
        clt_row_data=list(current_standings.values.tolist())
        clt_col_names = current_standings.columns.values

        # scatter plot
        s_df['average_points_for'] = s_df['points_for'] / (s_df['matches_won'] + s_df['matches_lost'] + s_df['matches_drawn'])
        s_df['average_points_against'] = s_df['points_against'] / (s_df['matches_won'] + s_df['matches_lost'] + s_df['matches_drawn'])

        avg_pts_for = s_df['average_points_for'].values.tolist()
        avg_pts_against = s_df['average_points_against'].values.tolist()

        del(s_df)

        data_dict = []
        for i,v in zip(avg_pts_for, avg_pts_against):
            d = {'x': i, 'y': v}
            data_dict.append(d)

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

        matches_df['number_of_opponents_beaten_in_week'] = 10-matches_df['points_for_week_rank']
        matches_df['number_of_opponents_drawn_to_in_week'] = matches_df[['week', 'points_for']].duplicated(keep=False).astype(int).values

        matches_df['prob_winning_week'] = matches_df['number_of_opponents_beaten_in_week'].apply(lambda x: x/9)
        matches_df['prob_losing_week'] = 1 - matches_df['prob_winning_week']

        matches_df['expected_points_win'] = matches_df['prob_winning_week']*3
        matches_df['expected_points_draw'] = matches_df['number_of_opponents_drawn_to_in_week'].apply(lambda x: (x/9) * 1 )

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

        xlt_row_data=list(round(standings,3).values.tolist())
        xlt_col_names = standings.columns.values

        return render_template(
            template_name_or_list='chart.html',
            league_id=league_id,
            league_name=league_name,
            data_dict=data_dict,
            labels=player_initials,

            clt_col_names = clt_col_names,
            clt_row_data = clt_row_data,

            xlt_col_names=xlt_col_names, 
            xlt_row_data=xlt_row_data,
            zip=zip,
            
            current_year=datetime.now().year)
    
    else:
        flash('Only head-to-head leagues are currently supported. Try again with a different League ID.')
        return redirect(url_for('inputLeagueID'))



# @app.route('/rugby_matches')
# def rugby_matches():


#     # Fixtures with odds
#     # TODO find out what date the matches were on - join on match time, home and away team
#     odds = pd.read_csv("urc_latest_results_odds.csv")
#     odds_row_data=list(odds.values.tolist())
#     odds_col_names = odds.columns.values

#     # get what the predictions were for the past matches

#     return render_template('rugby_matches.html', 
#                            title='Rugby Matches',
#                             column_names=odds_col_names, 
#                             row_data=odds_row_data,
#                             zip=zip)


# @app.route('/rugby_season_simulation')
# def rugby_season_simulation():
#     return render_template('rugby_season_simulation.html', 
#                            title='Rugby Season Simulation')