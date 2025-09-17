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
    
    # the league id enterred may be valid input but the number doesnt correspond to a League ID
    # IDs are created iteratively - most recently created league will have the largest ID number 
    # but we dont know what the largest one is
    # define url for fpl api
    url = f"https://draft.premierleague.com/api/league/{league_id}/details"
    try:
        print("fetching league details")
        league_details = fetch_fpl_with_cache(url=url, cache_key=f"draft_league_{league_id}_details")
        print("Succes league details")
    except:
        flash('The League ID enterred could not be loaded. Try again with a different League ID.')
        return redirect(url_for('inputLeagueID'))
    
    league_name = league_details['league']['name']
    league_scoring_mode = league_details['league']['scoring']

    # support for head to head leagues only.
    if league_scoring_mode == 'h':
        print("League is head to head")
        bench_row_data, bench_col_names, \
            current_standings_row_data, current_standings_col_names, \
            scatter_pts_for_vs_agnst_data_dict, \
            player_initials, \
            xlt_row_data, xlt_col_names = build_fpl_charts(league_id)

        return render_template(
                template_name_or_list='chart.html',
                league_id=league_id,
                league_name=league_name,
                data_dict=scatter_pts_for_vs_agnst_data_dict,
                labels=player_initials,

                bench_row_data=bench_row_data,
                bench_col_names=bench_col_names,

                clt_row_data=current_standings_row_data,
                clt_col_names=current_standings_col_names,

                xlt_col_names=xlt_col_names, 
                xlt_row_data=xlt_row_data,
                zip=zip,
                
                current_year=datetime.now().year)
    
    else:
        flash('Only head-to-head leagues are currently supported. Try again with a different League ID.')
        return redirect(url_for('inputLeagueID'))