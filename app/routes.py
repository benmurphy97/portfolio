from flask import render_template, request, redirect, url_for, flash
from app import app
from app.forms import LeagueIDForm
import json
from urllib.request import urlopen 
import pandas as pd
import os
from datetime import datetime
import time

from app.services.articles import fetch_articles
from app.services.fpl.fpl import get_bench_points_summary, get_fpl_charts
from app.services.fpl.cache import enqueue_league_cache_update, fetch_fpl_with_cache

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
    
    league_cache_file = f"cache/draft_league_{league_id}_details.json"

    if not os.path.exists(league_cache_file):
        # this is a new league_id
        enqueue_league_cache_update(league_id)

        # Wait briefly (max 5s) for cache updater thread to finish
        timeout = 5
        waited = 0
        while not os.path.exists(league_cache_file) and waited < timeout:
            time.sleep(1)
            waited += 1
    
    # --- If still no cache, it's invalid ---
    if not os.path.exists(league_cache_file):
        flash("The League ID entered could not be loaded. Try again with a different League ID.")
        return redirect(url_for('inputLeagueID'))

    # --- Load from cache (safe now) ---
    with open(league_cache_file, "r") as f:
        league_details = json.load(f)

    league_name = league_details['league']['name']
    league_scoring_mode = league_details['league']['scoring']

    # support for head to head leagues only.
    if league_scoring_mode == 'h':
        print("League is head to head")
        bench_row_data, bench_col_names, \
            current_standings_row_data, current_standings_col_names, \
            scatter_pts_for_vs_agnst_data_dict, \
            player_initials, \
            xlt_row_data, xlt_col_names = get_fpl_charts(league_id)

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