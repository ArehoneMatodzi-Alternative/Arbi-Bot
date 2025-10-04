# SuperSportBET → Premier League (CSV + JSON)
#Same instructions
import os, re, csv, json, time
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://www.supersportbet.com/sportsbook/?utm_source=supersport&utm_campaign=navigation&utm_medium=megaMenu"

OUT_DIR = r"C:\Users\User\Downloads\Arbitrage Website\output"
CSV_PATH = os.path.join(OUT_DIR, "supersport_premier.csv")
JSON_PATH = os.path.join(OUT_DIR, "supersport_premier.json")

# prices like 1.95 / 2.5
re_price = re.compile(r"\b(\d{1,2}\.\d{1,2}|\d{1,2}\.\d)\b")
# "3rd Oct, 21:00"
re_ord   = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec),\s*([01]?\d|2[0-3]):([0-5]\d)$", re.I)
# "Fri 21:00", "Today 21:00"
re_daytm = re.compile(r"^(Today|Tomorrow|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([01]?\d|2[0-3]):([0-5]\d)$", re.I)
# plain time "21:00"
re_time  = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
# section headers to fence EPL block
re_hdr   = re.compile(r"(premier league|english premier league|la liga|bundesliga|ligue 1|serie a|premier soccer league)", re.I)

mon = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
dow = {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}

def nice_date(d:int,m:int,y:Optional[int]=None)->str:
    if y is None: y = datetime.now().year
    return datetime(y,m,d).strftime("%a (%d %b)")

def nice_dow(day:str, hh:str, mm:str)->str:
    now=datetime.now(); idx=dow[day[:3].lower()]
    delta=(idx-now.weekday())%7
    if delta==0 and datetime(now.year,now.month,now.day,int(hh),int(mm))<now: delta=7
    return (now+timedelta(days=delta)).strftime("%a (%d %b)")

def is_team(s:str)->bool:
    return bool(re.fullmatch(r"[A-Za-z0-9'.\-&/]+(?:\s+[A-Za-z0-9'.\-&/]+){0,3}", s)) and 3<=len(s)<=40

def pick_spans(lines:List[str])->List[Tuple[int,int]]:
    heads=[i for i,s in enumerate(lines) if re.search(r"\bpremier league\b", s, re.I)]
    if not heads: return []
    nexts=[i for i,s in enumerate(lines) if re_hdr.search(s) and not re.search(r"premier league", s, re.I)]
    spans=[]
    for a in heads:
        b=min([j for j in nexts if j>a], default=len(lines))
        spans.append((a,b))
    return spans

def open_page()->str:
    os.makedirs(OUT_DIR, exist_ok=True)
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True)
        ctx=b.new_context(viewport={"width":1366,"height":960}, locale="en-ZA",
                          user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"))
        page=ctx.new_page(); page.set_default_timeout(70000)
        page.goto(URL, wait_until="domcontentloaded")
        for sel in ["button:has-text('Accept')","text=Accept","button:has-text('Got it')"]:
            try: page.locator(sel).first.click(timeout=1500); break
            except Exception: pass
        for sel in ["text=Soccer","button:has-text('Soccer')","a:has-text('Soccer')"]:
            try: page.locator(sel).first.click(timeout=1500); break
            except Exception: pass
        same,last=0,0
        for _ in range(520):
            page.mouse.wheel(0,1600); page.wait_for_timeout(200)
            try: h=page.evaluate("document.body.scrollHeight")
            except Exception: h=0
            if h==last: same+=1
            else: same=0
            last=h
            if same>=7: break
        try: txt=page.locator("body").inner_text(timeout=5000)
        except PWTimeout: txt=page.content()
        ctx.close(); b.close()
        return txt

def parse(txt:str)->List[Dict]:
    lines=[s.strip() for s in txt.splitlines() if s.strip()]
    spans=pick_spans(lines) or [(0,len(lines))]
    out=[]
    for a,b in spans:
        i=a
        last_date=None  # remember date for time-only rows
        while i<b:
            s=lines[i]

            m=re_ord.match(s)
            if m:
                d=int(m.group(1)); mth=mon[m.group(2)[:3].lower()]
                start=f"{int(m.group(3)):02d}:{m.group(4)}"; date=nice_date(d,mth)
                last_date=date
                j=i+1
                home=away=""
                while j<b and not home:
                    if is_team(lines[j]): home=lines[j]
                    j+=1
                while j<b and not away:
                    if is_team(lines[j]): away=lines[j]
                    j+=1
                if home and away and home.lower()!=away.lower():
                    window=" ".join(lines[j:min(b,j+80)])
                    prices=[float(x) for x in re_price.findall(window)]
                    if len(prices)>=3:
                        over=prices[3] if len(prices)>3 else ""
                        under=prices[4] if len(prices)>4 else ""
                        out.append({"home_team":home,"away_team":away,"start_time":start,"date":date,
                                    "odds_home":prices[0],"odds_draw":prices[1],"odds_away":prices[2],
                                    "category":"Football / England / Premier League","market":"Match Result",
                                    "over":over,"under":under,"source":"SuperSportBET"})
                i=j; continue

            m2=re_daytm.match(s)
            if m2:
                day,hh,mm=m2.groups(); start=f"{int(hh):02d}:{mm}"; date=nice_dow(day,hh,mm)
                last_date=date
                j=i+1
                home=away=""
                while j<b and not home:
                    if is_team(lines[j]): home=lines[j]
                    j+=1
                while j<b and not away:
                    if is_team(lines[j]): away=lines[j]
                    j+=1
                if home and away and home.lower()!=away.lower():
                    window=" ".join(lines[j:min(b,j+80)])
                    prices=[float(x) for x in re_price.findall(window)]
                    if len(prices)>=3:
                        over=prices[3] if len(prices)>3 else ""
                        under=prices[4] if len(prices)>4 else ""
                        out.append({"home_team":home,"away_team":away,"start_time":start,"date":date,
                                    "odds_home":prices[0],"odds_draw":prices[1],"odds_away":prices[2],
                                    "category":"Football / England / Premier League","market":"Match Result",
                                    "over":over,"under":under,"source":"SuperSportBET"})
                i=j; continue

            m3=re_time.match(s)
            if m3:  # fallback: time-only under the same date section
                start=f"{int(m3.group(1)):02d}:{m3.group(2)}"
                date = last_date or datetime.now().strftime("%a (%d %b)")
                j=i+1
                home=away=""
                while j<b and not home:
                    if is_team(lines[j]): home=lines[j]
                    j+=1
                while j<b and not away:
                    if is_team(lines[j]): away=lines[j]
                    j+=1
                if home and away and home.lower()!=away.lower():
                    window=" ".join(lines[j:min(b,j+80)])
                    prices=[float(x) for x in re_price.findall(window)]
                    if len(prices)>=3:
                        over=prices[3] if len(prices)>3 else ""
                        under=prices[4] if len(prices)>4 else ""
                        out.append({"home_team":home,"away_team":away,"start_time":start,"date":date,
                                    "odds_home":prices[0],"odds_draw":prices[1],"odds_away":prices[2],
                                    "category":"Football / England / Premier League","market":"Match Result",
                                    "over":over,"under":under,"source":"SuperSportBET"})
                i=j; continue

            i+=1

    # dedupe
    seen=set(); rows=[]
    for r in out:
        k=(r["home_team"].lower(), r["away_team"].lower(), r["date"], r["start_time"])
        if k not in seen: seen.add(k); rows.append(r)
    return rows

def write(rows:List[Dict]):
    cols=["home_team","away_team","start_time","date","odds_home","odds_draw","odds_away","category","market","over","under","source"]
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CSV_PATH,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({k:r.get(k,"") for k in cols})
    with open(JSON_PATH,"w",encoding="utf-8") as f:
        json.dump([{k:r.get(k,"") for k in cols} for r in rows], f, ensure_ascii=False, indent=2)

def main():
    txt=open_page()
    rows=parse(txt)
    write(rows)
    print("supersportbet: saved", len(rows))

if __name__=="__main__":
    main()
