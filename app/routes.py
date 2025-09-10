from flask import render_template, request, redirect, url_for, flash
from app import app
from app.forms import LeagueIDForm
import json
from urllib.request import urlopen 
import pandas as pd

from datetime import datetime

from app.services.articles import fetch_articles
from app.services.fpl import fetch_fpl_with_cache, get_bench_points_summary, build_fpl_charts

@app.route('/')
@app.route('/home')
def home():
    return render_template('home.html', title='Home')


# route for pulling my articles directly from Medium
@app.route("/articles")
def articles():
    articles = fetch_articles()
    return render_template("articles.html", articles=articles)


@app.route('/inputLeagueID', methods=['GET', 'POST'])
def inputLeagueID():
    form = LeagueIDForm()
    if form.validate_on_submit():
        return redirect(url_for('chart'))
    return render_template('inputLeagueID.html', title='League ID Input', form=form)


@app.route('/chart', methods=['GET', 'POST'])
def chart():
    
    league_id = request.form.get('league_id')

    if not league_id:
        flash("Please enter a league id.")
        return redirect(url_for('inputLeagueID'))
    
    url = f"https://draft.premierleague.com/api/league/{league_id}/details"
    league_details = fetch_fpl_with_cache(url=url, cache_key=f"league_{league_id}_details")

    # cupport for head to head leagues only.
    if league_details['league']['scoring'] == 'h':

        charts = build_fpl_charts(league_id)

    return render_template(
            template_name_or_list='chart.html',
            league_id=league_id,
            league_name=league_name,
            data_dict=data_dict,
            labels=player_initials,

            bench_row_data=bench_row_data,
            bench_col_names=bench_col_names,

            clt_row_data=clt_row_data,
            clt_col_names=clt_col_names,

            xlt_col_names=xlt_col_names, 
            xlt_row_data=xlt_row_data,
            zip=zip,
            
            current_year=datetime.now().year)

    # the league id enterred may be valid input but the number doesnt correspond to a League ID
    # IDs are created iteratively - most recently created league will have the largest ID number 
    # but we dont know what the largest one is
    # define url for fpl api
    url = f"https://draft.premierleague.com/api/league/{league_id}/details"

    try:
        league_details = fetch_fpl_with_cache(url=url, cache_key=f"league_{league_id}_details")
    except:
        flash('The League ID enterred could not be loaded. Try again with a different League ID.')
        return redirect(url_for('inputLeagueID'))
    
    data_json = league_details

    league_name = data_json['league']['name']
    # if scoring is head-to-head format
    if data_json['league']['scoring'] == 'h':

        bench_points = get_bench_points_summary(data_json)

        bench_row_data=list(bench_points.values.tolist())
        bench_col_names = bench_points.columns.values

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

            bench_row_data=bench_row_data,
            bench_col_names=bench_col_names,

            clt_row_data=clt_row_data,
            clt_col_names=clt_col_names,

            xlt_col_names=xlt_col_names, 
            xlt_row_data=xlt_row_data,
            zip=zip,
            
            current_year=datetime.now().year)
    
    else:
        flash('Only head-to-head leagues are currently supported. Try again with a different League ID.')
        return redirect(url_for('inputLeagueID'))

