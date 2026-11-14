import os
import re
import time
import xml.etree.ElementTree as ET
import requests
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://pblkvrybekogmweyajht.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_SERVICE_KEY:
    raise ValueError("SUPABASE_SERVICE_KEY must be set!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9"
}

def get_imdb_details(movie_name: str):
    """IMDb-യിൽ നിന്ന് 2026 സിനിമയുടെ ഒറിജിനൽ പേരും HD 2:3 പോസ്റ്ററും എടുക്കുന്നു"""
    try:
        clean_q = re.sub(r'[^a-zA-Z0-9\s:]', '', movie_name).strip().lower()
        if not clean_q:
            return movie_name, ""
        first_char = clean_q[0]
        url = f"https://v3.sg.media-imdb.com/suggestion/{first_char}/{requests.utils.quote(clean_q)}.json"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10).json()
        
        for item in res.get("d", []):
            year = item.get("y", 0)
            if item.get("qid") in ["movie", "feature"] and year in [2025, 2026]:
                raw_img = item.get("i", {}).get("imageUrl", "")
                if raw_img:
                    hd_poster = re.sub(r'\._V1_.*\.jpg$', '._V1_FMjpg_UX500_.jpg', raw_img)
                    return item.get("l", movie_name), hd_poster
    except Exception as e:
        print(f"IMDb error for {movie_name}: {e}")
    return movie_name, ""

def parse_box_office_article(headline: str, description: str):
    """വാർത്തയുടെ തലക്കെട്ടിൽ നിന്നും സമ്മറിയിൽ നിന്നും യഥാർത്ഥ Today Net, Total Net, Day എന്നിവ എടുക്കുന്നു"""
    full_text = f"{headline} . {description}"
    h_lower = headline.lower()
    
    banned = ["budget", "pre-release", "ott", "trailer", "teaser", "release date", "postponed", "salary", "remuneration", "rights", "announced", "first look", "shooting"]
    if any(b in h_lower for b in banned):
        return None

    clean_line = re.split(r'\s+[-–|]\s+', headline)[0].strip()
    title_split = re.split(
        r'(?i)\s+(box office|day \d+|week \d+|weekend|collection|collects|earns|mints|crosses|beats|hits|grosses|nett|net|movie|film|review)',
        clean_line
    )
    raw_title = title_split[0].strip(" :-–|\"'‘’“”")
    raw_title = re.sub(r"^.*?'s\s+", "", raw_title).strip()
    raw_title = re.sub(r'(?i)^(watch|exclusive|breaking|latest|update)\s*[:\-]?\s*', '', raw_title).strip()

    # Day എണ്ണം കണ്ടെത്തുന്നു
    day_m = re.search(r'(?i)day\s*(\d+)', full_text)
    day_count = int(day_m.group(1)) if day_m else 1

    # ₹ / Rs / Cr / L തുകകൾ കണ്ടെത്തുന്നു
    money_matches = re.findall(r'(?:₹|Rs\.?\s*|INR\s*)\s*([\d,\.]+)\s*(Cr|Crore|L|Lakh)', full_text, re.IGNORECASE)
    if not money_matches:
        return None

    parsed_vals = []
    for amt_str, unit_str in money_matches:
        try:
            val = float(amt_str.replace(",", ""))
            u = "L" if "l" in unit_str.lower() else "Cr"
            val_in_cr = val / 100.0 if u == "L" else val
            if 0.01 <= val_in_cr <= 1200:
                parsed_vals.append((amt_str, u, val_in_cr))
        except:
            continue

    if not parsed_vals:
        return None

    # ഏറ്റവും വലിയ തുക Total-ഉം, ചെറിയ തുക Today-ഉം ആയി വേർതിരിക്കുന്നു
    sorted_by_size = sorted(parsed_vals, key=lambda x: x[2])
    
    if len(sorted_by_size) >= 2 and sorted_by_size[-1][2] > sorted_by_size[0][2]:
        today_item = sorted_by_size[0]
        total_item = sorted_by_size[-1]
        today_net = f"₹{today_item[0]} {today_item[1]}"
        total_net = f"₹{total_item[0]} {total_item[1]}"
    else:
        only_item = sorted_by_size[0]
        total_net = f"₹{only_item[0]} {only_item[1]}"
        if day_count == 1:
            today_net = total_net
        else:
            est_day = round(only_item[2] / max(day_count, 2), 2)
            today_net = f"₹{int(est_day * 100)} L" if est_day < 1.0 else f"₹{est_day} Cr"

    return raw_title, today_net, total_net, day_count

def fetch_live_movies():
    queries = [
        ("Mollywood", 'Malayalam "box office collection" "Day" when:10d'),
        ("Kollywood", 'Tamil "box office collection" "Day" when:10d'),
        ("Tollywood", 'Telugu "box office collection" "Day" when:10d'),
        ("Bollywood", 'Bollywood "box office collection" "Day" when:10d'),
        ("Sandalwood", 'Kannada "box office collection" "Day" when:10d'),
        ("Hollywood", 'Hollywood India "box office collection" when:10d')
    ]
    
    results = {}
    for industry, q in queries:
        rss_url = f"https://news.google.com/rss/search?q={requests.utils.quote(q)}&hl=en-IN&gl=IN&ceid=IN:en"
        try:
            resp = requests.get(rss_url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            
            for item in root.findall(".//item")[:15]:
                title_el = item.find("title")
                desc_el = item.find("description")
                if title_el is None or not title_el.text:
                    continue
                
                headline = title_el.text
                desc_clean = re.sub(r'<[^>]+>', ' ', desc_el.text) if (desc_el is not None and desc_el.text) else ""
                
                parsed = parse_box_office_article(headline, desc_clean)
                if not parsed:
                    continue
                    
                raw_title, today_net, total_net, day_count = parsed
                if len(raw_title) < 2 or len(raw_title) > 35 or len(raw_title.split()) > 5:
                    continue
                if any(w in raw_title.lower() for w in ["top 10", "top 5", "box office", "records", "highest", "upcoming"]):
                    continue
                    
                key = raw_title.lower()
                if key not in results:
                    results[key] = {
                        "raw_title": raw_title,
                        "industry": industry,
                        "today_net": today_net,
                        "total_net": total_net,
                        "day_count": day_count
                    }
        except Exception as e:
            print(f"Error [{industry}]: {e}")
            
    return list(results.values())

def main():
    movies = fetch_live_movies()
    print(f"Found {len(movies)} active theatrical movies.")
    
    for m in movies:
        official_title, poster_url = get_imdb_details(m["raw_title"])
        if not poster_url:
            continue
            
        record = {
            "title": official_title,
            "industry": m["industry"],
            "poster_url": poster_url,
            "today_net": m["today_net"],
            "total_net": m["total_net"],
            "day_count": m["day_count"],
            "shows_count": "Live Tracking"
        }
        
        try:
            supabase.table("movies_live").upsert(record, on_conflict="title").execute()
            print(f"SAVED: {official_title} [{m['industry']}] | Today: {m['today_net']} | Total: {m['total_net']}")
        except Exception as e:
            print(f"Supabase error: {e}")
            
        time.sleep(0.2)

if __name__ == "__main__":
    main()
