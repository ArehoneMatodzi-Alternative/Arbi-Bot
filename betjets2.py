# betjets_scraper.py
# Scrape BetJets EPL 1X2 odds -> output/betjets_epl.csv + output/betjets_epl.json
# CI-friendly Playwright scraper with retries + debug artifacts.

from __future__ import annotations

import csv
import json
import os
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = os.getenv("BETJETS_URL", "https://betjets.co.za/en/sports/soccer/england/epl/1195")

OUT_DIR = Path(os.getenv("OUT_DIR", "output"))
CSV_PATH = OUT_DIR / "betjets_epl.csv"
JSON_PATH = OUT_DIR / "betjets_epl.json"

# Odds: allow 1.22 / 10.75 etc.
RE_ODD = re.compile(r"\b(\d{1,2}\.\d{1,2})\b")
RE_DATEBAR = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")  # 03/10/2025
RE_TIME_AMPM = re.compile(r"^([1-9]|1[0-2]):([0-5]\d)\s?(AM|PM)$", re.I)
RE_TIME_24 = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

COOKIE_SELECTORS = [
    "button:has-text('Accept')",
    "button:has-text('Accept all')",
    "button:has-text('I agree')",
    "button:has-text('Allow all')",
    "button:has-text('AGREE')",
    "text=Accept",
]

READY_SIGNALS = [
    "text=/Match Result/i",
    "text=/1X2/i",
    "text=/Premier League/i",
    "text=/EPL/i",
]

BLOCK_SIGNALS = [
    "text=/access denied/i",
    "text=/not available/i",
    "text=/restricted/i",
    "text=/verify/i",
    "text=/captcha/i",
    "text=/unusual traffic/i",
]


@dataclass
class Row:
    home_team: str
    away_team: str
    start_time: str          # "14:30"
    date: str                # "Sat (19 Dec)" etc.
    odds_home: float
    odds_draw: float
    odds_away: float
    category: str            # Soccer / England / Premier League
    market: str              # Match Result
    source: str              # Betjets


def brand_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").replace("www.", "")
    root = host.split(".")[0] if host else ""
    return root.capitalize() if root else "Unknown"


def category_from_url(url: str) -> str:
    # /en/sports/soccer/england/epl/1195 -> Soccer / England / Premier League
    parts = [p for p in urlparse(url).path.split("/") if p]
    if "sports" in parts:
        parts = parts[parts.index("sports") + 1 :]
    if parts and parts[-1].isdigit():
        parts = parts[:-1]

    def token_name(tok: str) -> str:
        t = tok.strip().lower().replace("-", " ").replace("_", " ")
        if t in {"epl", "premier league"}:
            return "Premier League"
        if t == "football":
            return "Football"
        if t == "soccer":
            return "Soccer"
        if t in {"england", "english"}:
            return "England"
        return t.title()

    good = [token_name(p) for p in parts[:3]]
    return " / ".join(good) if good else "Soccer / England / Premier League"


def ampm_to_24(h: int, m: int, ampm: str) -> str:
    a = ampm.upper()
    if a == "AM":
        h24 = 0 if h == 12 else h
    else:
        h24 = 12 if h == 12 else h + 12
    return f"{h24:02d}:{m:02d}"


def is_team(s: str) -> bool:
    # Team tokens up to 4 words, allow punctuation
    return bool(re.fullmatch(r"[A-Za-z0-9'.\-&/]+(?:\s+[A-Za-z0-9'.\-&/]+){0,4}", s)) and 2 <= len(s) <= 40


def is_noise(s: str) -> bool:
    low = s.strip().lower()
    bad = {
        "games", "outrights", "events", "live", "specials", "settings", "betslip",
        "match result", "total goals", "over", "under", "draw no bet", "double chance",
        "home", "draw", "away", "1", "x", "2",
    }
    return low in bad


def save_debug(page, tag: str = "betjets") -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(OUT_DIR / f"{tag}_debug.png"), full_page=True)
    except Exception:
        pass
    try:
        (OUT_DIR / f"{tag}_debug.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        (OUT_DIR / f"{tag}_debug.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
    except Exception:
        pass


def click_cookies(page) -> None:
    for sel in COOKIE_SELECTORS:
        try:
            page.locator(sel).first.click(timeout=1200)
            return
        except Exception:
            pass


def looks_blocked(page) -> bool:
    for sel in BLOCK_SIGNALS:
        try:
            if page.locator(sel).first.is_visible(timeout=500):
                return True
        except Exception:
            pass
    # also: if body has almost no text
    try:
        t = page.locator("body").inner_text(timeout=1500)
        if len(t.strip()) < 200:
            return True
    except Exception:
        pass
    return False


def wait_until_ready(page, timeout_ms: int = 90000) -> None:
    page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)

    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        click_cookies(page)

        # any visible “ready” signal
        for sel in READY_SIGNALS:
            try:
                if page.locator(sel).first.is_visible(timeout=500):
                    return
            except Exception:
                pass

        # odds present in body text is also a good signal
        try:
            txt = page.locator("body").inner_text(timeout=1500)
            if RE_ODD.search(txt):
                return
        except Exception:
            pass

        page.wait_for_timeout(500)

    # Don’t hard-fail here: continue and let parsing attempt happen
    print("WARN: Ready signals not found before timeout; continuing.")


def scroll_to_load(page, max_scrolls: int = 220) -> None:
    flat = 0
    last_h = 0
    for _ in range(max_scrolls):
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(250)
        try:
            h = page.evaluate("document.body.scrollHeight")
        except Exception:
            h = 0
        if h == last_h:
            flat += 1
            if flat >= 7:
                break
        else:
            flat = 0
        last_h = h


def open_page_text(url: str, headless: bool = True) -> Tuple[str, str]:
    last_err: Optional[Exception] = None

    for attempt in range(3):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                ctx = browser.new_context(
                    viewport={"width": 1366, "height": 960},
                    locale="en-ZA",
                    timezone_id="Africa/Johannesburg",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                page = ctx.new_page()
                page.set_default_timeout(60000)

                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                click_cookies(page)

                wait_until_ready(page, timeout_ms=90000)

                if looks_blocked(page):
                    save_debug(page, tag="betjets_blocked")
                    raise RuntimeError("BetJets looks blocked / not rendering on this runner.")

                scroll_to_load(page)
                click_cookies(page)

                # Pull visible text; this is what you successfully parse locally
                txt = page.locator("body").inner_text(timeout=8000)
                final_url = page.url

                ctx.close()
                browser.close()
                return txt, final_url

        except Exception as e:
            last_err = e
            print(f"WARN: open attempt {attempt+1}/3 failed: {e}")
            time.sleep(2)

    raise last_err if last_err else RuntimeError("Unknown failure opening BetJets")


def parse_rows(txt: str, page_url: str) -> List[Row]:
    lines = [x.strip() for x in txt.splitlines() if x.strip()]
    source = brand_from_url(page_url)
    category = category_from_url(page_url)
    market = "Match Result"

    out: List[Row] = []
    current_date: Optional[datetime] = None

    i = 0
    n = len(lines)

    while i < n:
        s = lines[i]

        md = RE_DATEBAR.match(s)
        if md:
            dd, mm, yy = int(md.group(1)), int(md.group(2)), int(md.group(3))
            try:
                current_date = datetime(yy, mm, dd)
            except ValueError:
                current_date = None
            i += 1
            continue

        mt12 = RE_TIME_AMPM.match(s)
        mt24 = RE_TIME_24.match(s) if not mt12 else None

        if mt12 or mt24:
            if mt12:
                start_time = ampm_to_24(int(mt12.group(1)), int(mt12.group(2)), mt12.group(3))
            else:
                start_time = f"{int(mt24.group(1)):02d}:{int(mt24.group(2)):02d}"

            j = i + 1

            home = ""
            while j < n and not home:
                t = lines[j]
                if not is_noise(t) and is_team(t):
                    home = t
                j += 1

            away = ""
            while j < n and not away:
                t = lines[j]
                if not is_noise(t) and is_team(t):
                    away = t
                j += 1

            if not (home and away) or home.lower() == away.lower():
                i = j
                continue

            window = " ".join(lines[j : min(n, j + 50)])
            odds = RE_ODD.findall(window)

            # We need 3 odds for 1X2
            if len(odds) < 3:
                i = j
                continue

            date_str = (current_date.strftime("%a (%d %b)") if current_date else datetime.now().strftime("%a (%d %b)"))

            try:
                out.append(
                    Row(
                        home_team=home,
                        away_team=away,
                        start_time=start_time,
                        date=date_str,
                        odds_home=float(odds[0]),
                        odds_draw=float(odds[1]),
                        odds_away=float(odds[2]),
                        category=category,
                        market=market,
                        source=source,
                    )
                )
            except Exception:
                pass

            i = j
            continue

        i += 1

    # dedupe by match + time + date
    seen = set()
    deduped: List[Row] = []
    for r in out:
        key = (r.home_team.lower(), r.away_team.lower(), r.date, r.start_time)
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


def write_outputs(rows: List[Row]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cols = [
        "home_team", "away_team", "start_time", "date",
        "odds_home", "odds_draw", "odds_away",
        "category", "market", "source",
    ]

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            d = asdict(r)
            w.writerow({k: d.get(k, "") for k in cols})

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in rows], f, ensure_ascii=False, indent=2)


def main() -> int:
    print(f"BetJets URL: {URL}")
    txt, final_url = open_page_text(URL, headless=True)
    rows = parse_rows(txt, final_url)
    write_outputs(rows)
    print(f"BetJets: saved {len(rows)} rows -> {CSV_PATH} / {JSON_PATH}")

    # If you prefer the workflow not to fail when BetJets returns 0 (site down),
    # keep exit code 0. If you want it to fail loudly, return 2.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
