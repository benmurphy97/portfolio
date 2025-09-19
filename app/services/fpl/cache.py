from threading import Thread
import os
import json
import time
from urllib.request import urlopen 

import requests

CACHE_DIR = "cache"
LATEST_GW_FILE = os.path.join(CACHE_DIR, "latest_finished_gw.json")
GLOBAL_GW_FILE = os.path.join(CACHE_DIR, "latest_finished_gw_global.json")
CACHE_TTL = 60 * 60 * 24 * 7 # 60 secs * 60 minutes

def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)


# get the number of the latest finished gameweek
def fetch_latest_finished_gw():
    url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    data = requests.get(url).json()
    return max([e["id"] for e in data["events"] if e["finished"]])


def get_cached_latest_gw(league_id):
    """Read the last cached GW number for this league (if exists)."""
    gw_file = os.path.join(CACHE_DIR, f"latest_finished_gw_{league_id}.json")
    if os.path.exists(gw_file):
        with open(gw_file, "r") as f:
            return json.load(f).get("latest_finished_gw")
    return None

def set_cached_latest_gw(league_id, gw):
    """Write the last cached GW number for this league."""
    gw_file = os.path.join(CACHE_DIR, f"latest_finished_gw_{league_id}.json")
    with open(gw_file, "w") as f:
        json.dump({"latest_finished_gw": gw}, f)


# get data from api, use cache if data exists already
def fetch_fpl_with_cache(url, cache_key):
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")

    # Use cache if exists
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            return json.load(f)

    # Otherwise, fetch from API and write to cache
    print(f"Fetching {url} → cache key {cache_key}")
    response = urlopen(url)
    data = json.loads(response.read())
    with open(cache_file, "w") as f:
        json.dump(data, f)
    return data


def get_cached_latest_global_gw():
    """Read the last cached global GW number (if exists)."""
    if os.path.exists(GLOBAL_GW_FILE):
        with open(GLOBAL_GW_FILE, "r") as f:
            return json.load(f).get("latest_finished_gw")
    return None


def set_cached_latest_global_gw(gw):
    """Write the last cached global GW number."""
    with open(GLOBAL_GW_FILE, "w") as f:
        json.dump({"latest_finished_gw": gw}, f)


def update_global_cache():
    """Update bootstrap + event live data if a new global GW has finished."""
    current_latest_gw = fetch_latest_finished_gw()
    cached_latest_gw = get_cached_latest_global_gw()

    if cached_latest_gw == current_latest_gw:
        return

    print(f"🌍 Updating global cache for latest GW {current_latest_gw}...")

    # Bootstrap data
    fetch_fpl_with_cache("https://fantasy.premierleague.com/api/bootstrap-static/", "classic_bootstrap")
    fetch_fpl_with_cache("https://draft.premierleague.com/api/bootstrap-static", "draft_bootstrap")

    # GW points for all finished GWs up to latest
    for gw in range(1, current_latest_gw + 1):
        fetch_fpl_with_cache(
            f"https://fantasy.premierleague.com/api/event/{gw}/live/",
            cache_key=f"classic_event_{gw}_live"
        )

    # Update marker
    set_cached_latest_global_gw(current_latest_gw)
    print(f"✅ Global cache updated (latest GW = {current_latest_gw})")


def update_league_cache(league_id):
    # fetch league details
    url = f"https://draft.premierleague.com/api/league/{league_id}/details"
    response = urlopen(url)
    league_details = json.loads(response.read())

    league_scoring_mode = league_details['league']['scoring']
    if league_scoring_mode != 'h':
        h2h_ind = False
        print(f"League {league_id} is not head-to-head. Skipping cache update.")
        return h2h_ind

    # --- Step 2: determine latest finished GW for this league ---
    finished_gws = [m['event'] for m in league_details['matches'] if m['finished']]
    current_latest_gw = max(finished_gws) if finished_gws else None
    cached_latest_gw = get_cached_latest_gw(league_id)

    first_time = cached_latest_gw is None

    if not first_time and cached_latest_gw == current_latest_gw:
        print(f"⏩ League {league_id}: no new GW finished (still GW {current_latest_gw}). Skipping update.")
        return

    if first_time:
        print(f"🆕 First time caching league {league_id} → fetching all data.")

    # --- Step 3: cache league details ---
    cache_file = os.path.join(CACHE_DIR, f"draft_league_{league_id}_details.json")
    with open(cache_file, "w") as f:
        json.dump(league_details, f)

    # --- Step 4: cache picks for all finished GWs ---
    for entry in league_details['league_entries']:
        entry_id = entry['entry_id']
        # TODO odd numbers of players cause the average gw score be used to make up the numbers
        if entry_id is None:
            continue # dont save to cache
        for gw in finished_gws:
            fetch_fpl_with_cache(
                f"https://draft.premierleague.com/api/entry/{entry_id}/event/{gw}",
                cache_key=f"draft_entry_{entry_id}_gw_{gw}"
            )

    # --- Step 5: update global caches (only if new global GW) ---
    update_global_cache()

    # --- Step 6: update league marker ---
    set_cached_latest_gw(league_id, current_latest_gw)

    print(f"✅ Cache updated for league {league_id} (latest GW = {current_latest_gw})")


# background updater thread
class FPLCacheUpdater(Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.queue = []  # league_ids waiting to update - for when multiple users request data
        self.last_global_check = 0 # timestamp of latest check for global fpl api data

    def run(self):
        while True:
            # check if any league ids need to be processed
            if self.queue:
                league_id = self.queue.pop(0)
                try:
                    update_league_cache(league_id)
                except Exception as e:
                    print(f"Error updating cache for league {league_id}: {e}")
            
            # every hour check if a new gameweek has finished
            now = time.time()
            if now - self.last_global_check > 3600: # 1 hour
                try:
                    update_global_cache()
                except Exception as e:
                    print(f"Error updating global fpl cache {e}")
                    self.last_global_check = now

            time.sleep(5)  # wait before checking again


    def request_update(self, league_id):
        if league_id not in self.queue:
            self.queue.append(league_id)

# --- singleton instance ---
cache_updater = FPLCacheUpdater()
cache_updater.start()

# call this in routes.py when a new league_id is submitted
def enqueue_league_cache_update(league_id):
    cache_updater.request_update(league_id)

