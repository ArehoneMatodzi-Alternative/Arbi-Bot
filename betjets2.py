# scrape BetJets EPL and write csv + json 
# For betjets only (at least for now)
# create a virtual environment and activate it
# run this to install the libraries : pip install requests beautifulsoup4 pandas playwright
# run this: playwright install
# Now you can run this file, it should output a data folder with both csv and json


import os, re, json, csv, time
from contextlib import contextmanager
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://betjets.co.za/en/sports/football/england/epl/1195"
OUT_DIR = r"C:\Users\User\Downloads\Arbitrage Website\output"
CSV_PATH = os.path.join(OUT_DIR, "betjets_epl.csv")
JSON_PATH = os.path.join(OUT_DIR, "betjets_epl.json")

# odds (2 decimals), date bars, and times
re_price = re.compile(r"\b(\d{1,2}\.\d{2})\b")
re_datebar = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")                         # 03/10/2025
re_time_ampm = re.compile(r"^([1-9]|1[0-2]):([0-5]\d)\s?(AM|PM)$", re.I)     # 9:00 PM
re_time_24   = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")                   # 21:00



@contextmanager
def launch(headless: bool = True):
    with sync_playwright() as p:
        b = p.chromium.launch(headless=headless)
        try:
            yield b
        finally:
            b.close()

def brand_from_url(url: str) -> str:
    # site name from hostname
    host = (urlparse(url).hostname or "").replace("www.", "")
    root = host.split(".")[0] if host else ""
    return root.capitalize() if root else "Unknown"

def token_name(tok: str) -> str:
    # map short codes → nice names
    t = tok.strip().lower().replace("-", " ").replace("_", " ")
    if t in {"epl", "premier league"}: return "Premier League"
    if t == "football": return "Football"
    if t == "soccer": return "Soccer"
    if t == "england" or t == "english": return "England"
    return t.title()

def category_from_url(url: str) -> str:
    # /sports/football/england/epl/1195 → Football / England / Premier League
    parts = [p for p in urlparse(url).path.split("/") if p]
    if "sports" in parts:
        parts = parts[parts.index("sports")+1:]
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    good = [token_name(p) for p in parts[:3]]
    return " / ".join(good)

def category_from_text(lines: List[str], url: str) -> str:
    # try breadcrumbs/headers first, then fallback to URL
    sport = None
    country = None
    league = None
    for s in lines[:150]:
        low = s.lower()
        if not sport and ("soccer" in low or "football" in low):
            sport = "Soccer" if "soccer" in low else "Football"
        if not country and ("england" in low or "english" in low):
            country = "England"
        if not league and (low == "epl" or "premier league" in low):
            league = "Premier League"
        if sport and country and league:
            break
    # URL fallback for anything missing
    if not (sport and country and league):
        from_url = category_from_url(url).split(" / ")
        if not sport and len(from_url) > 0: sport = from_url[0]
        if not country and len(from_url) > 1: country = from_url[1]
        if not league and len(from_url) > 2: league = from_url[2]
    parts = [p for p in [sport, country, league] if p]
    return " / ".join(parts) if parts else category_from_url(url)

def detect_market(lines: List[str]) -> str:
    # prefer the label shown on the page
    for s in lines[:200]:
        if "match result" in s.lower():
            return "Match Result"
        if s.strip().lower() == "1x2":
            return "1X2"
    return "Match Result"

def ampm_to_24(h: int, m: int, ampm: str) -> str:
    a = ampm.upper()
    if a == "AM":
        h24 = 0 if h == 12 else h
    else:
        h24 = 12 if h == 12 else h + 12
    return f"{h24:02d}:{m:02d}"

def is_team(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9'.\-&/]+(?:\s+[A-Za-z0-9'.\-&/]+){0,3}", s)) and 2 <= len(s) <= 40

def skip_word(s: str) -> bool:
    s2 = s.lower()
    junk = {
        "games","outrights","match result","total goals","o/u","over","under",
        "home","draw","away","events","live","specials","settings","betslip",
        "+197","+194"
    }
    return s2 in junk or s2 in {"1","x","2"}

# fetching + parsing 

def open_page(headless: bool = True) -> Tuple[str, str]:
    # returns (visible_text, final_url)
    os.makedirs(OUT_DIR, exist_ok=True)
    with launch(headless=headless) as b:
        ctx = b.new_context(
            viewport={"width": 1366, "height": 960},
            locale="en-ZA",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        )
        page = ctx.new_page()
        page.set_default_timeout(10000000)
        page.goto(URL, wait_until="networkidle")  # or "load"
        page.wait_for_selector("text=Match Result", timeout=15000)

        for sel in ["button:has-text('Accept')", "text=Accept"]:
            try:
                page.locator(sel).first.click(timeout=1500); break
            except Exception:
                pass
        flat, last_h = 0, 0
        for _ in range(240):
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(250)
            try: h = page.evaluate("document.body.scrollHeight")
            except Exception: h = 0
            if h == last_h:
                flat += 1
                if flat >= 6: break
            else:
                flat = 0
            last_h = h
        try:
            txt = page.locator("body").inner_text(timeout=5000)
        except PWTimeout:
            txt = page.content()
        final_url = page.url
        ctx.close()
        return txt, final_url

def parse_epl(txt: str, page_url: str) -> List[Dict]:
    lines = [x.strip() for x in txt.splitlines() if x.strip()]
    source = brand_from_url(page_url)
    category = category_from_text(lines, page_url)
    market = detect_market(lines)

    n, i = len(lines), 0
    out: List[Dict] = []
    current_date: Optional[datetime] = None

    while i < n:
        line = lines[i]

        # date bar like 03/10/2025
        md = re_datebar.match(line)
        if md:
            dd, mm, yy = int(md.group(1)), int(md.group(2)), int(md.group(3))
            try: current_date = datetime(yy, mm, dd)
            except ValueError: current_date = None
            i += 1
            continue

        # time: 9:00 PM or 21:00
        mt12 = re_time_ampm.match(line)
        mt24 = re_time_24.match(line) if not mt12 else None
        if mt12 or mt24:
            if mt12:
                hh = int(mt12.group(1)); mn = int(mt12.group(2)); ampm = mt12.group(3)
                start_time = ampm_to_24(hh, mn, ampm)
            else:
                start_time = f"{int(mt24.group(1)):02d}:{int(mt24.group(2)):02d}"

            j = i + 1

            # teams after time
            home, away = "", ""
            while j < n and not home:
                s = lines[j]
                if not skip_word(s) and is_team(s): home = s
                j += 1
            while j < n and not away:
                s = lines[j]
                if not skip_word(s) and is_team(s): away = s
                j += 1

            if not (home and away and home.lower() != away.lower()):
                i = j; continue

            # odds near teams
            window = " ".join(lines[j:min(n, j + 40)])
            prices = re_price.findall(window)
            if len(prices) < 3:
                i = j; continue

            odds_home = float(prices[0])
            odds_draw = float(prices[1])
            odds_away = float(prices[2])
            over  = float(prices[3]) if len(prices) > 3 else ""
            under = float(prices[4]) if len(prices) > 4 else ""

            format_date = (current_date.strftime("%a (%d %b)")
                           if current_date else datetime.now().strftime("%a (%d %b)"))

            out.append({
                "home_team": home,
                "away_team": away,
                "start_time": start_time,
                "date":  format_date,
                "odds_home": odds_home,
                "odds_draw": odds_draw,
                "odds_away": odds_away,
                "category": category,
                "market": market,
                "over": over,
                "under": under,
                "source": source,
            })

            i = j
            continue

        i += 1

    # dedupe
    seen, rows = set(), []
    for r in out:
        key = (r["home_team"].lower(), r["away_team"].lower(), r["date"], r["start_time"])
        if key not in seen:
            seen.add(key); rows.append(r)
    return rows

def write_files(rows: List[Dict]):
    cols = ["home_team","away_team","start_time","date",
            "odds_home","odds_draw","odds_away",
            "category","market","over","under","source"]
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({k: r.get(k, "") for k in cols})
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump([{k: r.get(k, "") for k in cols} for r in rows], f, ensure_ascii=False, indent=2)

def main():
    txt, final_url = open_page()     # headless=True default
    rows = parse_epl(txt, final_url)
    write_files(rows)
    print(f"BetJets: saved {len(rows)}")

if __name__ == "__main__":
    main()
