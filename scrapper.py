import os
import re
import time
import cloudscraper
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://pblkvrybekogmweyajht.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_SERVICE_KEY:
    raise ValueError("SUPABASE_SERVICE_KEY must be set!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

def clean_movie_name(raw_name: str) -> str:
    name = re.sub(r'\(.*?\)', '', raw_name).strip()
    name = re.sub(r'(?i)box office.*', '', name).strip()
    return name

def get_imdb_poster(movie_name: str):
    """API Key ഇല്ലാതെ IMDb-യിൽ നിന്ന് ഒറിജിനൽ HD പോസ്റ്റർ എടുക്കുന്നു"""
    try:
        clean_q = re.sub(r'[^a-zA-Z0-9\s]', '', movie_name).strip().lower()
        if not clean_q:
            return movie_name, ""
        first_char = clean_q[0]
        url = f"https://v3.sg.media-imdb.com/suggestion/{first_char}/{requests.utils.quote(clean_q)}.json"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10).json()
        
        for item in res.get("d", []):
            if item.get("qid") in ["movie", "feature"] and item.get("i", {}).get("imageUrl"):
                raw_img = item["i"]["imageUrl"]
                # HD 2:3 പോസ്റ്റർ സൈസിലേക്ക് മാറ്റുന്നു
                hd_poster = re.sub(r'\._V1_.*\.jpg$', '._V1_FMjpg_UX500_.jpg', raw_img)
                return item.get("l", movie_name), hd_poster
    except Exception as e:
        print(f"IMDb poster error for {movie_name}: {e}")
    return movie_name, ""

def detect_industry(text_context: str) -> str:
    t = text_context.lower()
    if any(w in t for w in ["malayalam", "mollywood", "kerala"]):
        return "Mollywood"
    if any(w in t for w in ["tamil", "kollywood", "chennai"]):
        return "Kollywood"
    if any(w in t for w in ["telugu", "tollywood", "hyderabad"]):
        return "Tollywood"
    if any(w in t for w in ["kannada", "sandalwood", "bengaluru"]):
        return "Sandalwood"
    if any(w in t for w in ["hindi", "bollywood", "mumbai"]):
        return "Bollywood"
    if any(w in t for w in ["hollywood", "english"]):
        return "Hollywood"
    return "Bollywood"

def format_currency(val: str) -> str:
    val = val.strip()
    if not val or val in ["-", "0"]:
        return "₹0.00 Cr"
    if "₹" not in val:
        if re.match(r'^[\d\.]+$', val):
            return f"₹{val} Cr"
        return f"₹{val}"
    return val

def scrape_sacnilk():
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
    )
    urls = [
        "https://www.sacnilk.com/entertainment/boxoffice",
        "https://www.sacnilk.com/news/boxoffice"
    ]
    movies_data = []
    seen_titles = set()

    for url in urls:
        try:
            response = scraper.get(url, timeout=15)
            if response.status_code != 200:
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                if len(rows) < 2:
                    continue
                headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
                if any(k in " ".join(headers) for k in ["movie", "film", "collection", "net", "day"]):
                    for row in rows[1:]:
                        cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                        if len(cols) < 3:
                            continue
                        raw_title = clean_movie_name(cols[0])
                        if not raw_title or len(raw_title) < 2 or raw_title.lower() in seen_titles or len(raw_title.split()) > 6:
                            continue
                        seen_titles.add(raw_title.lower())
                        
                        day_num = 1
                        today_net = "₹0.00 Cr"
                        total_net = "₹0.00 Cr"
                        row_text = " ".join(cols)
                        
                        for idx, col_val in enumerate(cols[1:], start=1):
                            header_name = headers[idx] if idx < len(headers) else ""
                            if "day" in header_name and col_val.isdigit():
                                day_num = int(col_val)
                            elif "today" in header_name or idx == 1:
                                if not col_val.isdigit():
                                    today_net = format_currency(col_val)
                                else:
                                    day_num = int(col_val)
                            elif "total" in header_name or "india" in header_name or idx == len(cols) - 1:
                                total_net = format_currency(col_val)

                        movies_data.append({
                            "raw_title": raw_title,
                            "today_net": today_net,
                            "total_net": total_net,
                            "day_count": day_num,
                            "industry": detect_industry(row_text)
                        })
        except Exception as e:
            print(f"Error scraping {url}: {e}")
    return movies_data

def main():
    scraped_list = scrape_sacnilk()
    print(f"Found {len(scraped_list)} movies.")
    for item in scraped_list:
        title, poster_url = get_imdb_poster(item["raw_title"])
        record = {
            "title": title,
            "industry": item["industry"],
            "poster_url": poster_url,
            "today_net": item["today_net"],
            "total_net": item["total_net"],
            "day_count": item["day_count"],
            "shows_count": "Live Tracking"
        }
        try:
            supabase.table("movies_live").upsert(record, on_conflict="title").execute()
            print(f"Upserted: {title} | Poster: {bool(poster_url)} | Today: {item['today_net']}")
        except Exception as e:
            print(f"Supabase error: {e}")
        time.sleep(0.2)

if __name__ == "__main__":
    main()
