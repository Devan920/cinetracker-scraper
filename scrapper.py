import os
import re
import time
import cloudscraper
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client

# Environment Variables (GitHub Secrets അല്ലെങ്കിൽ ലോക്കൽ .env-ൽ നിന്നും എടുക്കും)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://pblkvrybekogmweyajht.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

if not SUPABASE_SERVICE_KEY or not TMDB_API_KEY:
    raise ValueError("SUPABASE_SERVICE_KEY and TMDB_API_KEY must be set!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

LANG_TO_WOOD = {
    "ml": "Mollywood",
    "ta": "Kollywood",
    "te": "Tollywood",
    "hi": "Bollywood",
    "kn": "Sandalwood",
    "en": "Hollywood"
}

def clean_movie_name(raw_name: str) -> str:
    # ബ്രാക്കറ്റിലുള്ള വർഷമോ അധിക വിവരങ്ങളോ നീക്കം ചെയ്യുന്നു
    name = re.sub(r'\(.*?\)', '', raw_name).strip()
    # "Box Office Collection" പോലെയുള്ള വാക്കുകൾ ഉണ്ടെങ്കിൽ മാറ്റുന്നു
    name = re.sub(r'(?i)box office.*', '', name).strip()
    return name

def get_tmdb_metadata(movie_name: str):
    """TMDB API വഴി ഒറിജിനൽ പേര്, HD പോസ്റ്റർ, ഇൻഡസ്ട്രി എന്നിവ കണ്ടെത്തുന്നു"""
    try:
        search_url = "https://api.themoviedb.org/3/search/movie"
        params = {
            "api_key": TMDB_API_KEY,
            "query": movie_name,
            "include_adult": "false"
        }
        res = requests.get(search_url, params=params, timeout=10).json()
        results = res.get("results", [])
        
        if results:
            # ഏറ്റവും പുതിയ റിലീസുകൾക്ക് മുൻഗണന നൽകാൻ sort ചെയ്യുന്നു
            results.sort(key=lambda x: x.get("release_date", ""), reverse=True)
            movie = results[0]
            
            official_title = movie.get("title") or movie_name
            poster_path = movie.get("poster_path")
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
            lang = movie.get("original_language", "")
            industry = LANG_TO_WOOD.get(lang, "Other")
            
            return official_title, poster_url, industry
    except Exception as e:
        print(f"TMDB error for {movie_name}: {e}")
        
    return movie_name, "", "Other"

def format_currency(val: str) -> str:
    val = val.strip()
    if not val or val == "-" or val == "0":
        return "₹0.00 Cr"
    if "₹" not in val:
        # വെറും നമ്പർ ആണെങ്കിൽ Cr ചേർക്കുന്നു
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
            print(f"Fetching: {url}")
            response = scraper.get(url, timeout=15)
            if response.status_code != 200:
                print(f"Failed with status {response.status_code}")
                continue
                
            soup = BeautifulSoup(response.text, "html.parser")
            tables = soup.find_all("table")
            
            for table in tables:
                rows = table.find_all("tr")
                if len(rows) < 2:
                    continue
                    
                headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
                
                # ബോക്സ് ഓഫീസ് ടേബിൾ ആണോ എന്ന് പരിശോധിക്കുന്നു
                if any(k in " ".join(headers) for k in ["movie", "film", "collection", "net", "day"]):
                    for row in rows[1:]:
                        cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                        if len(cols) < 3:
                            continue
                            
                        raw_title = clean_movie_name(cols[0])
                        if not raw_title or len(raw_title) < 2 or raw_title.lower() in seen_titles:
                            continue
                        
                        # ഹെഡ്‌ലൈൻ പോലെയുള്ള നീളം കൂടിയ ടെക്സ്റ്റുകൾ ഒഴിവാക്കുന്നു
                        if len(raw_title.split()) > 6:
                            continue

                        seen_titles.add(raw_title.lower())
                        
                        # Day, Today Net, Total Net എന്നിവ വേർതിരിക്കുന്നു
                        day_num = 1
                        today_net = "₹0.00 Cr"
                        total_net = "₹0.00 Cr"
                        
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
                            "day_count": day_num
                        })
        except Exception as e:
            print(f"Error scraping {url}: {e}")

    return movies_data

def main():
    scraped_list = scrape_sacnilk()
    print(f"Found {len(scraped_list)} movies.")
    
    for item in scraped_list:
        title, poster_url, industry = get_tmdb_metadata(item["raw_title"])
        
        record = {
            "title": title,
            "industry": industry,
            "poster_url": poster_url,
            "today_net": item["today_net"],
            "total_net": item["total_net"],
            "day_count": item["day_count"],
            "shows_count": "Live Tracking"
        }
        
        try:
            supabase.table("movies_live").upsert(record, on_conflict="title").execute()
            print(f"Upserted: {title} ({industry}) - Today: {item['today_net']}, Total: {item['total_net']}")
        except Exception as e:
            print(f"Supabase error for {title}: {e}")
            
        time.sleep(0.3) # TMDB API rate limit ഒഴിവാക്കാൻ

if __name__ == "__main__":
    main()
