# imports
import feedparser
from bs4 import BeautifulSoup

from datetime import datetime
import time

# global variables
CACHE = {
    "articles": [],
    "last_fetch": 0
}
# ARTICLE_CACHE_DURATION = 300  # 5 minutes / 300 seconds
ARTICLE_CACHE_DURATION = 604800

# define medium username
MEDIUM_USERNAME = "benmurphy_29746"
FEED_URL = f"https://medium.com/feed/@{MEDIUM_USERNAME}"

# functions

# refresh cache if time elapsed
def fetch_articles():

    now = time.time()

    # check how long has elapsed between queries
    if now - CACHE['last_fetch'] > ARTICLE_CACHE_DURATION:

        # Parse Medium RSS feed
        feed = feedparser.parse(FEED_URL)
        if len(feed.entries) > 0:
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

            CACHE['articles'] = articles_data
            CACHE['last_fetch'] = now
        else:
            print(f"Articles not refreshed, 0 articles returned from RSS Time: {now}")

    return CACHE['articles']

