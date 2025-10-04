# scrape SunBet Premier League and dump csv + json
# For SunBet only (at least for now)
# create a virtual environment and activate it
# run this to install the libraries : pip install requests beautifulsoup4 pandas playwright
# run this: playwright install
# Now you can run this file, it should output a data folder with both csv and json

import os, re, json, csv, time
from contextlib import contextmanager
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, Page, Frame, TimeoutError as PWTimeout

URL = "https://www.sunbet.co.za/sports-landing/#sports-hub/football/england/premier_league"

OUT_DIR = r"C:\Users\User\Downloads\Arbitrage Website\output"
CSV_PATH = os.path.join(OUT_DIR, "sunbet_premier.csv")
JSON_PATH = os.path.join(OUT_DIR, "sunbet_premier.json")

# patterns for the data to actually look pretty
re_price = re.compile(r"\b(\d{1,2}\.\d{1,2})\b")
re_day   = re.compile(r"^(Today|Tomorrow|Mon|Tue|Wed|Thu|Fri|Sat|Sun)$", re.I)
re_time  = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
re_date  = re.compile(r"^(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?:\s+(\d{2,4}))?$", re.I)
re_date_time = re.compile(r"^(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*(\d{2,4})?\s+([01]?\d|2[0-3]):([0-5]\d)$", re.I)
re_over  = re.compile(r"\bOver\s+\d+(?:\.\d+)?\s+(\d{1,2}\.\d{1,2})", re.I)
re_under = re.compile(r"\bUnder\s+\d+(?:\.\d+)?\s+(\d{1,2}\.\d{1,2})", re.I)

weekday_idx = {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}
month_idx   = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}



def _brand_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").replace("www.", "")
    root = host.split(".")[0] if host else ""
    # tiny prettifier
    special = {"sunbet":"SunBet", "betjets":"Betjets"}
    return special.get(root, root.capitalize() or "Unknown")

def _token_name(tok: str) -> str:
    t = tok.strip().lower().replace("-", " ").replace("_", " ")
    if t in {"epl","premier league"}: return "Premier League"
    if t in {"football","soccer"}: return t.title()
    if t in {"england","english"}: return "England"
    return t.title()

def _category_from_url(url: str) -> str:
    u = urlparse(url)
    # SunBet puts the path in the hash fragment
    path = (u.fragment or u.path)
    parts = [p for p in path.split("/") if p]
    if "sports" in parts:
        parts = parts[parts.index("sports")+1:]
    if "sports-hub" in parts:
        parts = parts[parts.index("sports-hub")+1:]
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    nice = [_token_name(p) for p in parts[:3]]
    return " / ".join([p for p in nice if p])

def _category_from_text(lines: List[str], url: str) -> str:
    sport = country = league = None
    for s in lines[:200]:
        low = s.lower()
        if not sport and ("soccer" in low or "football" in low):
            sport = "Soccer" if "soccer" in low else "Football"
        if not country and ("england" in low or "english" in low):
            country = "England"
        if not league and ("premier league" in low or low == "epl"):
            league = "Premier League"
        if sport and country and league:
            break
    if not (sport and country and league):
        # fallback to URL tokens
        from_url = _category_from_url(url).split(" / ")
        if not sport   and len(from_url)>0: sport   = from_url[0]
        if not country and len(from_url)>1: country = from_url[1]
        if not league  and len(from_url)>2: league  = from_url[2]
    parts = [p for p in [sport, country, league] if p]
    return " / ".join(parts) if parts else _category_from_url(url)

def _detect_market(lines: List[str]) -> str:
    for s in lines[:200]:
        low = s.lower().strip()
        if "match result" in low: return "Match Result"
        if low == "1x2": return "1X2"
    return "Match Result"

def ok_team(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9'.\-&/]+(?:\s+[A-Za-z0-9'.\-&/]+){0,3}", s)) and 2 <= len(s) <= 40

def formatdate(day_word: Optional[str], date_word: Optional[Tuple[int,int,int]], hh: str, mm: str) -> Tuple[str,str]:
    # return "HH:MM" and "Sun (05 Oct)"
    now = datetime.now()
    if day_word:
        lw = day_word.lower()
        if lw == "today":
            dt = now.date()
        elif lw == "tomorrow":
            dt = (now + timedelta(days=1)).date()
        else:
            idx = weekday_idx[lw[:3]]; cur = now.weekday()
            delta = (idx - cur) % 7
            if delta == 0 and datetime(now.year, now.month, now.day, int(hh), int(mm)) < now:
                delta = 7
            dt = (now + timedelta(days=delta)).date()
    elif date_word:
        d, m, y = date_word
        dt = datetime(y if y else now.year, m, d).date()
    else:
        dt = now.date()
    return f"{hh}:{mm}", dt.strftime("%a (%d %b)")


@contextmanager
def launch(headless: bool = True):
    with sync_playwright() as p:
        b = p.chromium.launch(headless=headless)
        try:
            yield b
        finally:
            b.close()

def pick_frame(page: Page, wait_ms: int = 10000) -> Optional[Frame]:
    deadline = time.time() + wait_ms / 1000.0
    best, score = None, -1
    while time.time() < deadline:
        for f in page.frames:
            try:
                hits = f.locator("text=/More Bets/i").count()
            except Exception:
                continue
            if hits > score:
                score, best = hits, f
        if score >= 1:
            break
        time.sleep(0.25)
    return best

def pull_text(headless: bool = True) -> Tuple[str,str]:
    # return visible text + final url
    os.makedirs(OUT_DIR, exist_ok=True)
    with launch(headless=headless) as b:
        ctx = b.new_context(
            viewport={"width": 1366, "height": 960},
            locale="en-ZA",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        )
        page = ctx.new_page()
        page.set_default_timeout(70000)
        page.goto(URL, wait_until="domcontentloaded")

        # cookie button on shell
        for sel in ["button:has-text('Accept all')", "button:has-text('Accept')", "text=Accept all", "text=Accept"]:
            try:
                page.locator(sel).first.click(timeout=1500); break
            except Exception:
                pass

        f = pick_frame(page, wait_ms=10000)
        if f is None:
            txt = page.locator("body").inner_text(timeout=4000)
            u = page.url
            ctx.close()
            return txt, u

        # cookie button in frame
        for sel in ["button:has-text('Accept all')", "button:has-text('Accept')", "text=Accept all", "text=Accept"]:
            try:
                f.locator(sel).first.click(timeout=1200); break
            except Exception:
                pass

        # ensure matches tab if present
        for label in ["Matches", "Match", "All Matches", "Fixtures"]:
            try:
                f.locator(f"text=^{label}$").first.click(timeout=1200); break
            except Exception:
                pass

        # scroll inside frame
        same, last_h = 0, 0
        for _ in range(280):
            try: f.evaluate("window.scrollBy(0, 1800)")
            except Exception: pass
            page.wait_for_timeout(250)
            try:
                h = f.evaluate("document.scrollingElement ? document.scrollingElement.scrollHeight : document.body.scrollHeight")
            except Exception:
                h = 0
            if h == last_h:
                same += 1
                if same >= 6: break
            else:
                same = 0
            last_h = h

        try:
            txt = f.locator("body").inner_text(timeout=5000)
        except PWTimeout:
            txt = page.locator("body").inner_text(timeout=5000)

        u = page.url
        ctx.close()
        return txt, u


def extract_rows(txt: str, page_url: str) -> List[Dict]:
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    category = _category_from_text(lines, page_url)
    market   = _detect_market(lines)
    source   = _brand_from_url(page_url)

    n, i = len(lines), 0
    out: List[Dict] = []

    def skip(s: str) -> bool:
        s2 = s.lower()
        junk = {"special","total","draw no bet","double chance","both teams",
                "competitions","outrights","live","events","home","draw","away",
                "2nd half","top leagues","top competitions","search results","bb",
                "settings","total goals","1","x","2"}
        return s2 in junk

    while i < n:
        line = lines[i]

        # single-line date+time (e.g., "18 Oct 13:30")
        m_all = re_date_time.match(line)
        if m_all:
            d = int(m_all.group(1)); mon = month_idx[m_all.group(2)[:3].lower()]
            y = int(m_all.group(3)) if m_all.group(3) else None
            hh, mm = m_all.group(4).zfill(2), m_all.group(5)
            start_time, date_txt = formatdate(None, (d, mon, y if y else 0), hh, mm)
            j = i + 1
        else:
            # "Fri" + "21:00"  OR  "18 Oct" + "13:30"
            m_day  = re_day.match(line)
            m_date = re_date.match(line) if not m_day else None
            m_tn   = re_time.match(lines[i+1]) if i+1 < n else None
            if m_day and m_tn:
                day_word = m_day.group(1)
                hh, mm = m_tn.group(1).zfill(2), m_tn.group(2)
                start_time, date_txt = formatdate(day_word, None, hh, mm)
                j = i + 2
            elif m_date and m_tn:
                d = int(m_date.group(1)); mon = month_idx[m_date.group(2)[:3].lower()]
                y = int(m_date.group(3)) if m_date.group(3) else None
                hh, mm = m_tn.group(1).zfill(2), m_tn.group(2)
                start_time, date_txt = formatdate(None, (d, mon, y if y else 0), hh, mm)
                j = i + 2
            else:
                i += 1
                continue

        # team lines
        home = ""
        while j < n and not home:
            s = lines[j]
            if not skip(s) and ok_team(s): home = s
            j += 1

        away = ""
        while j < n and not away:
            s = lines[j]
            if not skip(s) and ok_team(s): away = s
            j += 1

        if not (home and away and home.lower() != away.lower()):
            i = j
            continue

        # odds window
        window = " ".join(lines[j:min(n, j + 40)])
        prices = re_price.findall(window)
        if len(prices) < 3:
            i = j
            continue

        odds_home = float(prices[0])
        odds_draw = float(prices[1])
        odds_away = float(prices[2])

        mO = re_over.search(window)
        mU = re_under.search(window)
        over  = float(mO.group(1)) if mO else ""
        under = float(mU.group(1)) if mU else ""

        out.append({
            "home_team": home,
            "away_team": away,
            "start_time": start_time,
            "date": date_txt,
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

    # dedupe
    seen, rows = set(), []
    for r in out:
        k = (r["home_team"].lower(), r["away_team"].lower(), r["date"], r["start_time"])
        if k not in seen:
            seen.add(k); rows.append(r)
    return rows

# ---------------- write + run ----------------

def write_files(rows: List[Dict]):
    cols = ["home_team","away_team","start_time","date",
            "odds_home","odds_draw","odds_away",
            "category","market","over","under","source"]
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({k: r.get(k, "") for k in cols})
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump([{k: r.get(k, "") for k in cols}], f, ensure_ascii=False, indent=2) if False else \
        json.dump([{k: r.get(k, "") for k in cols} for r in rows], f, ensure_ascii=False, indent=2)

def main():
    txt, final_url = pull_text()   # headless=True by default
    rows = extract_rows(txt, final_url)
    write_files(rows)
    print(f"saved {len(rows)} rows")

if __name__ == "__main__":
    main()
