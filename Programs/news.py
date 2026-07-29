import requests
from bs4 import BeautifulSoup
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

NEWS_FEEDS = {
    # Countries
    "world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "italy": "https://www.ansa.it/sito/ansait_rss.xml",
    "japan": "https://www.japantimes.co.jp/feed/",
    "slovenia": "https://www.rtvslo.si/feeds/00.xml",
    "usa": "https://www.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    # "austria": "https://rss.orf.at/news.xml",
    # "switzerland": "https://www.srf.ch/news/bnf/rss/1646",
    
    # Other
    "economics": "https://www.economist.com/sections/international/rss.xml",
    "science": "https://www.nasa.gov/rss/breaking_news.rss",
    "tech": "https://www.wired.com/feed/rss",
    "nature": "https://www.nationalgeographic.com/rss/index.xml",
    "space": "https://www.space.com/feeds/all",
    
    # AI
    "ai": "https://www.technologyreview.com/topic/artificial-intelligence/rss/",
    "machine-learning": "https://machinelearningmastery.com/feed/"
}

# UI Colors
CLR_HEADER = '\033[95m'
CLR_CYAN = '\033[96m'
CLR_RED = '\033[91m'
CLR_END = '\033[0m'
CLR_BOLD = '\033[1m'

def fetch_news(region):
    url = NEWS_FEEDS.get(region.lower())
    if not url:
        return None

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    try:
        # Reduced timeout slightly for a snappier feel
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        items = soup.find_all('item') or soup.find_all('entry')

        if not items:
            return f"\n{CLR_BOLD}{CLR_HEADER}--- {region.upper()} ---{CLR_END}\nNo articles found today."

        output = [f"\n{CLR_BOLD}{CLR_HEADER}--- Latest {region.upper()} News ---{CLR_END}"]
        for i, item in enumerate(items[:5], 1):
            title_tag = item.find('title')
            if title_tag:
                output.append(f"{CLR_CYAN}{i}.{CLR_END} {title_tag.text.strip()}")
        
        return "\n".join(output)
            
    except (requests.exceptions.RequestException, Exception):
        # Graceful Crash: Just returns a clean error message
        return f"\n{CLR_BOLD}{CLR_RED}--- {region.upper()} (Offline) ---{CLR_END}\nSource currently unavailable."

if __name__ == "__main__":
    args = sys.argv[1:]
    target_regions = args if args else list(NEWS_FEEDS.keys())

    print(f"{CLR_BOLD}Fetching live updates...{CLR_END}")

    with ThreadPoolExecutor(max_workers=len(target_regions)) as executor:
        future_to_region = {executor.submit(fetch_news, reg): reg for reg in target_regions}
        
        for future in as_completed(future_to_region):
            result = future.result()
            if result:
                print(result)

    print(f"\n{CLR_CYAN}{'='*40}{CLR_END}")
    