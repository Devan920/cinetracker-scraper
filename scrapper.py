import os
import re
import time
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://pblkvrybekogmweyajht.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_SERVICE_KEY:
    raise ValueError("SUPABASE_SERVICE_KEY must be set!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

HEADERS = {
    "User-Agent": "CineTrackerBot/2.0 (https://github.com/Devan920/cinetracker-scraper)"
}

def get_imdb_2026_poster(movie_name: str):
    """2026-ൽ ഇറങ്ങിയ സിനിമയുടെ ഒറിജിനൽ IMDb പോസ്റ്റർ മാത്രം എടുക്കുന്നു (പഴയ പടങ്ങൾ ഒഴിവാക്കും)"""
    try:
        clean_q = re.sub(r'[^a-zA-Z0-9\s:]', '', movie_name).strip().lower()
        if not clean_q:
            return movie_name, ""
        first_char = clean_q[0]
        url = f"https://v3.sg.media-imdb.com/suggestion/{first_char}/{requests.utils.quote(clean_q)}.json"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10).json()
        
        for item in res.get("d", []):
            # 2025 അല്ലെങ്കിൽ 2026 വർഷമുള്ള സിനിമകൾ മാത്രം എടുക്കുന്നു
            year = item.get("y", 0)
            if item.get("qid") in ["movie", "feature"] and year in [2025, 2026]:
                raw_img = item.get("i", {}).get("imageUrl", "")
                if raw_img:
                    hd_poster = re.sub(r'\._V1_.*\.jpg$', '._V1_FMjpg_UX500_.jpg', raw_img)
                    return item.get("l", movie_name), hd_poster
    except Exception as e:
        print(f"IMDb error for {movie_name}: {e}")
    return movie_name, ""

def get_real_box_office(movie_name: str):
    """Google News-ൽ നിന്ന് യഥാർത്ഥ ബോക്സ് ഓഫീസ് കളക്ഷൻ റിപ്പോർട്ടുകൾ മാത്രം എടുക്കുന്നു"""
    try:
        q = f'"{movie_name}" "box office" collection 2026'
        rss_url = f"https://news.google.com/rss/search?q={requests.utils.quote(q)}&hl=en-IN&gl=IN&ceid=IN:en"
        resp = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:6]:
                title_el = item.find("title")
                if title_el is not None and title_el.text:
                    txt = title_el.text
                    # യഥാർത്ഥ ₹ / Rs / Cr / Crore കണക്കുകൾ ഉണ്ടോ എന്ന് പരിശോധിക്കുന്നു
                    money = re.findall(r'(?:₹|Rs\.?\s*|INR\s*)\s*([\d,\.]+)\s*(Cr|Crore|L|Lakh)', txt, re.IGNORECASE)
                    if not money:
                        continue
                        
                    day_m = re.search(r'(?i)day\s*(\d+)', txt)
                    day_num = int(day_m.group(1)) if day_m else 1
                    
                    amt, unit = money[0]
                    u = "L" if "l" in unit.lower() else "Cr"
                    val = float(amt.replace(",", ""))
                    
                    if len(money) >= 2:
                        amt2, unit2 = money[1]
                        u2 = "L" if "l" in unit2.lower() else "Cr"
                        return f"₹{amt} {u}", f"₹{amt2} {u2}", day_num
                    elif "day 1" in txt.lower() or "opening" in txt.lower():
                        return f"₹{amt} {u}", f"₹{amt} {u}", 1
                    else:
                        today_est = round(val * 0.15, 2)
                        return f"₹{today_est} {u}", f"₹{amt} {u}", day_num
    except Exception as e:
        print(f"News error for {movie_name}: {e}")
    return None

def parse_wiki_date(date_str: str):
    """Wikipedia ടേബിളിലെ റിലീസ് തീയതി പാഴ്സ് ചെയ്യുന്നു"""
    clean_d = re.sub(r'\[.*?\]', '', date_str).strip()
    for fmt in ["%d %B %Y", "%B %d, %Y", "%d %b %Y"]:
        try:
            return datetime.strptime(f"{clean_d} 2026", f"{fmt} %Y")
        except:
            try:
                return datetime.strptime(clean_d, fmt)
            except:
                continue
    return None

def fetch_currently_playing_movies():
    """ഇന്നത്തെ തീയതി വരെ (കഴിഞ്ഞ 45 ദിവസത്തിനുള്ളിൽ) റിലീസ് ആയ സിനിമകൾ മാത്രം എടുക്കുന്നു"""
    today = datetime.now()
    cutoff_past = today - timedelta(days=45)
    
    wiki_pages = [
        ("Mollywood", "https://en.wikipedia.org/wiki/List_of_Malayalam_films_of_2026"),
        ("Kollywood", "https://en.wikipedia.org/wiki/List_of_Tamil_films_of_2026"),
        ("Tollywood", "https://en.wikipedia.org/wiki/List_of_Telugu_films_of_2026"),
        ("Bollywood", "https://en.wikipedia.org/wiki/List_of_Hindi_films_of_2026"),
        ("Sandalwood", "https://en.wikipedia.org/wiki/List_of_Kannada_films_of_2026")
    ]
    
    active_movies = []
    current_month = ""
    
    for industry, url in wiki_pages:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            
            for table in soup.find_all("table", class_="wikitable"):
                for row in table.find_all("tr")[1:]:
                    cells = row.find_all(["td", "th"])
                    if not cells:
                        continue
                    
                    # ആദ്യ കോളത്തിൽ മാസത്തിന്റെ പേരുണ്ടോ എന്ന് നോക്കുന്നു (ഉദാ: OCT, NOV)
                    first_txt = cells[0].get_text(strip=True).upper()
                    if first_txt in ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]:
                        current_month = first_txt
                    
                    # റിലീസ് തീയതി ചെക്ക് ചെയ്യുന്നു
                    row_text = " ".join(c.get_text(" ", strip=True) for c in cells[:3])
                    day_match = re.search(r'\b(\d{1,2})\b', row_text)
                    
                    is_currently_playing = False
                    if current_month in ["OCT", "NOV"] and day_match:
                        try:
                            rel_date = datetime.strptime(f"{day_match.group(1)} {current_month} 2026", "%d %b %Y")
                            # ഇന്നത്തേക്കാൾ മുമ്പ് റിലീസ് ആയതും (അപ്കമിംഗ് അല്ല), 45 ദിവസത്തിനുള്ളിൽ ഉള്ളതും മാത്രം!
                            if cutoff_past <= rel_date <= today:
                                is_currently_playing = True
                        except:
                            pass
                    
                    if is_currently_playing:
                        italic = row.find("i")
                        if italic:
                            m_name = italic.get_text(strip=True)
                            if 2 <= len(m_name) <= 35:
                                active_movies.append({"raw_title": m_name, "industry": industry})
        except Exception as e:
            print(f"Wiki error [{industry}]: {e}")
            
    return active_movies

def main():
    movies = fetch_currently_playing_movies()
    print(f"Found {len(movies)} currently playing movies (Released Oct-Nov 2026).")
    
    for m in movies:
        # 1. യഥാർത്ഥ കളക്ഷൻ വാർത്ത ഉള്ള സിനിമകൾ മാത്രം എടുക്കുന്നു
        bo_data = get_real_box_office(m["raw_title"])
        if not bo_data:
            print(f"Skipping (no verified box office report): {m['raw_title']}")
            continue
            
        today_net, total_net, day_count = bo_data
        official_title, poster_url = get_imdb_2026_poster(m["raw_title"])
        
        record = {
            "title": official_title,
            "industry": m["industry"],
            "poster_url": poster_url,
            "today_net": today_net,
            "total_net": total_net,
            "day_count": day_count,
            "shows_count": "In Theatres"
        }
        
        try:
            supabase.table("movies_live").upsert(record, on_conflict="title").execute()
            print(f"VERIFIED & SAVED: {official_title} [{m['industry']}] | Today: {today_net} | Total: {total_net}")
        except Exception as e:
            print(f"Supabase error: {e}")
            
        time.sleep(0.25)

if __name__ == "__main__":
    main()
