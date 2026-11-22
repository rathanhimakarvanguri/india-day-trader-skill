#!/usr/bin/env python3
"""News monitor for trader-news. Standard library only.

Watches headlines and NSE corporate announcements for the stocks you watch or
hold and prints only what is new since the last check, newest first, with how
far each stock has moved today and a flag on anything that touches your
symbols.

    python3 news.py                                    # watchlist + plan + portfolio symbols
    python3 news.py --tickers RELIANCE TCS INFY
    python3 news.py --tickers RELIANCE --all --hours 72  # everything in 3 days, seen or not
    python3 news.py --no-nse                           # headlines only
    python3 news.py --no-moves                         # skip the price line per symbol

Your symbols, when --tickers is not given: every hit in trader/watchlist.json
(trader-scanner), the symbol in trader/plan.json (trader-exit) and the
positions in trader/portfolio.json. Names come from trader/universe.txt when
it has them, so Google News can search "Reliance Industries" and not just
"RELIANCE".

Sources, one request each per symbol:
  - Google News RSS, India edition, the last 2 days:
    https://news.google.com/rss/search?q="<NAME>"+NSE+when:2d&hl=en-IN&gl=IN&ceid=IN:en
  - Yahoo Finance headline RSS: .../rss/2.0/headline?s=<SYMBOL>.NS&region=IN&lang=en-IN
  - NSE corporate announcements (the filings a listed company must make under
    SEBI's LODR rules: results, board meetings, deals, resignations, ratings):
    https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=<SYMBOL>
    NSE's site sets cookies on its home page first and turns away bare
    scripts, so this opens https://www.nseindia.com/ once, keeps the cookies,
    then asks. If NSE still refuses, the tool says so and headlines still run.
  - The move: Yahoo Finance's chart endpoint (unofficial, can lag), the last
    price against yesterday's close.

Times print in India time (IST). State: trader/state/news.json remembers
what you have seen (30 days), so an item shows once. Offline: --offline DIR
reads gnews-<SYM>.xml, yahoo-<SYM>.xml, nse-<SYM>.json and chart-<SYM>.json
from DIR. The tests use it.

Headlines are leads, not facts: open the story or the filing before acting,
and treat nothing here as advice.
"""

import argparse
import datetime as _dt
import email.utils
import gzip
import hashlib
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

YAHOO = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=IN&lang=en-IN"
GNEWS = "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en"
CHART = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m"
NSE_HOME = "https://www.nseindia.com/"
NSE_ANN = "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=%s"
NSE_FILE = "https://nsearchives.nseindia.com/corporate/%s"
BSE_LIST = ("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry="
            "&segment=Equity&status=Active")
BSE_ANN = ("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1&strPrevDate=%s"
           "&strScrip=%s&strSearch=P&strToDate=%s&strType=C&subcategory=-1")
BSE_FILE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/%s"
BSE_HOME = "https://www.bseindia.com/"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
KEEP_DAYS = 30
MOVE_PCT = 3.0  # a stock this far from yesterday's close is flagged as moving

# NSE announcement subjects ("desc") that usually move a stock the same day
IMPORTANT_SUBJECTS = re.compile(
    r"financial result|outcome of board meeting|acquisition|amalgamation|merger|scheme of arrangement|"
    r"resignation|cessation|credit rating|fraud|default|insolvency|cirp|buy ?back|bonus|split|"
    r"change in (?:director|auditor|management|key managerial)|pledge|order|contract|award|"
    r"press release|investigation|search|survey|penalty|clarification", re.I)
KEYWORDS = [
    ("earnings", r"\bresults?\b|\bQ[1-4]\b|\bprofit\b|\bnet loss\b|\brevenue\b|\bEBITDA\b|\bguidance\b"),
    ("analyst", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|target price|price target|\boutperform\b|"
                r"\bunderperform\b|\bbuy rating\b|\bsell rating\b"),
    ("legal", r"\bSEBI\b|\bED\b|\bCBI\b|\bIT raid|\bincome tax\b|\bprobe\b|\binvestigation\b|\bNCLT\b|"
              r"\bcourt\b|\bpenalty\b|\bshow[- ]cause\b"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bamalgamation\b|\bstake\b|\bblock deal\b|"
             r"\bbulk deal\b|\bdeal\b|\border win\b|\bwins order\b|\bbags\b"),
    ("capital", r"\bdividend\b|\bbuy ?back\b|\bbonus\b|\bstock split\b|\bQIP\b|\brights issue\b|"
                r"\bOFS\b|\bfund ?rais"),
    ("people", r"\bCEO\b|\bCFO\b|\bMD\b|\bresign|\bsteps down\b|\bappoint"),
    ("risk", r"\bdefault\b|\binsolvency\b|\bpledge\b|\bdowngrade\b|\bfraud\b|\bfire\b|\bshutdown\b|"
             r"\bcircuit\b"),
    ("regulatory", r"\bUSFDA\b|\bFDA\b|\bwarning letter\b|\bobservations?\b|\bRBI\b|\bTRAI\b|\bCCI\b|"
                   r"\bapproval\b"),
    ("macro", r"\brepo rate\b|\bMPC\b|\binflation\b|\bCPI\b|\bGDP\b|\bFIIs?\b|\bFPIs?\b|\bDIIs?\b|"
              r"\bBudget\b|\bmonsoon\b|\bcrude\b|\brupee\b|\btariffs?\b|\bGIFT Nifty\b"),
]


class NewsError(Exception):
    pass


# ---------------------------------------------------------------- time

IST_HOURS = 5.5  # India Standard Time is UTC+05:30 all year: no daylight saving


def ist_offset(utc):
    """Hours from UTC for India: always +5.5."""
    return IST_HOURS


def to_ist(utc):
    """Aware or naive UTC -> naive India wall-clock time."""
    if utc.tzinfo is not None:
        utc = utc.astimezone(_dt.timezone.utc)
    return utc.replace(tzinfo=None) + _dt.timedelta(hours=IST_HOURS)



def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def watch_from_files(portfolio="trader/portfolio.json", watchlist="trader/watchlist.json",
                     plan="trader/plan.json"):
    """{symbol: name or None}: the scanner's hits, the planned trade and your holdings."""
    out = {}
    wl = load_json(watchlist) or {}
    for h in wl.get("hits", []):
        sym = h.get("symbol") or h.get("ticker")
        if sym:
            out[sym.upper()] = h.get("name")
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.setdefault(pl["symbol"].upper(), pl.get("name"))
    pf = load_json(portfolio) or {}
    for p in pf.get("positions", []):
        sym = p.get("ticker") or p.get("symbol")
        if sym:
            out[sym.upper()] = p.get("name") or out.get(sym.upper())
    return out


def names_from_universe(path="trader/universe.txt"):
    """{SYMBOL: company name} from trader-scanner's universe (SYMBOL|Name a line)."""
    out = {}
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                if "|" in ln:
                    sym, name = ln.rstrip("\n").split("|", 1)
                    if sym.strip() and name.strip():
                        out[sym.strip().upper()] = name.strip()
    return out


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, offline=None, pause=0.3):
        self.offline = offline
        self.pause = pause
        self._last = 0.0
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))
        self._nse_warm = False

    def _offline(self, name):
        path = os.path.join(self.offline, name)
        if not os.path.isfile(path):
            raise NewsError("offline: no file %s" % path)
        with open(path, "rb") as fh:
            return fh.read()

    def get(self, url, name, referer=None, accept="*/*"):
        if self.offline:
            return self._offline(name)
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        headers = {"User-Agent": BROWSER_UA, "Accept-Encoding": "gzip", "Accept": accept,
                   "Accept-Language": "en-IN,en;q=0.9"}
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        try:
            with self._opener.open(req, timeout=30) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as exc:
            raise NewsError("HTTP %s for %s" % (exc.code, url.split("?")[0]))
        except urllib.error.URLError as exc:
            raise NewsError("could not reach %s: %s" % (url.split("/")[2], exc.reason))

    def bse(self, url, name):
        """BSE's API answers browser-like requests that come from bseindia.com."""
        if self.offline:
            return self._offline(name)
        return self.get(url, name, referer=BSE_HOME, accept="application/json")

    def nse(self, url, name):
        """NSE's API wants the cookies its home page sets, and a browser-like request."""
        if self.offline:
            return self._offline(name)
        if not self._nse_warm:
            self.get(NSE_HOME, "", accept="text/html")
            self._nse_warm = True
        return self.get(url, name, referer=NSE_HOME, accept="application/json")


def yahoo_symbol(ticker):
    s = ticker.upper().strip()
    return urllib.parse.quote(s if s.endswith((".NS", ".BO")) else s + ".NS", safe=".-")


def gnews_query(ticker, name=None):
    """Search words for Google News: the company name in quotes when known, plus NSE."""
    words = ('"%s"' % _short_name(name)) if name else ('"%s"' % ticker)
    return urllib.parse.quote_plus("%s NSE when:2d" % words)


def _short_name(name):
    """'Reliance Industries Limited' -> 'Reliance Industries' (fewer missed headlines)."""
    n = re.sub(r"\s+(limited|ltd\.?)$", "", (name or "").strip(), flags=re.I)
    return n or name


# ---------------------------------------------------------------- parsing

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _text(el, name):
    for c in el.iter():
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_time(value):
    """RFC 822 (RSS) or ISO 8601 (Atom) -> aware UTC datetime, or None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


def parse_rss(data, ticker, source="Yahoo Finance"):
    """A headline RSS (Yahoo or Google News) -> items."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("RSS for %s is not valid XML: %s" % (ticker, exc))
    out = []
    for it in root.iter("item"):
        title = _text(it, "title")
        link = _text(it, "link")
        guid = _text(it, "guid") or link
        if source == "Google News":
            src = _text(it, "source")
            if src and title.endswith(" - " + src):
                title = title[:-len(" - " + src)]
            source_label = ("GNews/" + src) if src else "Google News"
        else:
            source_label = source
        out.append({"id": "rss:" + guid, "source": source_label, "kind": "headline",
                    "ticker": ticker, "title": title, "summary": _text(it, "description"),
                    "link": link, "time": parse_time(_text(it, "pubDate"))})
    return out


def parse_nse_time(value):
    """NSE's '13-Nov-2026 17:45:12' or '2026-11-13 17:45:12' (IST) -> aware UTC."""
    value = (value or "").strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%m-%Y %H:%M:%S"):
        try:
            local = _dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
        return (local - _dt.timedelta(hours=IST_HOURS)).replace(tzinfo=_dt.timezone.utc)
    return None


def parse_bse_time(value):
    """BSE's '2026-11-20T18:01:23.47' or '20/11/2026 18:01:23' (IST) -> aware UTC."""
    v = (value or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?", v)
    if m:
        y, mo, d, h, mi, se = (int(x or 0) for x in m.groups())
    else:
        m = re.match(r"^(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?", v)
        if not m:
            return None
        d, mo, y, h, mi, se = (int(x or 0) for x in m.groups())
    local = _dt.datetime(y, mo, d, h, mi, se)
    return (local - _dt.timedelta(hours=IST_HOURS)).replace(tzinfo=_dt.timezone.utc)


def parse_bse_codes(data):
    """BSE's list of scrips -> {NSE-style symbol: BSE scrip code}. BSE's scrip_id is the same as the
    NSE symbol for most large companies (RELIANCE 500325, TCS 532540); where it differs, put the code
    in trader/bse_codes.json yourself."""
    try:
        rows = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except ValueError:
        raise NewsError("BSE's scrip list is not JSON")
    rows = rows.get("Table", rows) if isinstance(rows, dict) else rows
    out = {}
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict):
            sid = str(r.get("scrip_id") or r.get("SCRIP_ID") or "").strip().upper()
            code = str(r.get("SCRIP_CD") or r.get("scrip_cd") or "").strip()
            if sid and code.isdigit():
                out[sid] = code
    return out


def parse_bse(data, ticker):
    """BSE AnnSubCategoryGetData JSON ({"Table": [...]}) -> items, like NSE's."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except ValueError:
        raise NewsError("BSE announcements for %s are not JSON" % ticker)
    rows = doc.get("Table", []) if isinstance(doc, dict) else doc
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        cat = " ".join(str(r.get("SUBCATNAME") or r.get("CATEGORYNAME") or "").split())
        subject = " ".join(str(r.get("NEWSSUB") or r.get("HEADLINE") or "announcement").replace("''", "'").split())
        detail = " ".join(str(r.get("HEADLINE") or r.get("MORE") or "").split())
        company = r.get("SLONGNAME") or ticker
        subject = re.sub(r"^%s\s*-\s*\d+\s*-\s*" % re.escape(str(company)), "", subject) or subject
        att = str(r.get("ATTACHMENTNAME") or "").strip()
        when = parse_bse_time(r.get("NEWS_DT") or r.get("DissemDT") or r.get("News_submission_dt"))
        out.append({"id": "bse:%s:%s" % (ticker, r.get("NEWSID") or subject), "source": "BSE filing",
                    "kind": "filing", "ticker": ticker,
                    "title": "%s: %s" % (company, (cat + ": " + subject) if cat and cat.lower() not in
                                         subject.lower() else subject),
                    "summary": detail[:400], "important": bool(IMPORTANT_SUBJECTS.search(cat + " " + subject)),
                    "link": (BSE_FILE % att) if att else "https://www.bseindia.com/corporates/ann.html",
                    "time": when})
    return out


def bse_codes(fetcher, path="trader/bse_codes.json"):
    """{SYMBOL: code}: your trader/bse_codes.json first, then BSE's list (saved to that file for next time)."""
    mine = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                mine = {k.upper(): str(v) for k, v in json.load(fh).items()}
        except (OSError, ValueError):
            mine = {}
    if mine and not fetcher.offline:
        return mine
    try:
        got = parse_bse_codes(fetcher.bse(BSE_LIST, "bse-scrips.json"))
    except NewsError:
        return mine
    got.update(mine)
    if not fetcher.offline and got:
        try:
            folder = os.path.dirname(path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(got, fh, indent=0, sort_keys=True)
        except OSError:
            pass
    return got


def parse_nse(data, ticker):
    """NSE corporate-announcements JSON (a list, or {"data": [...]}) -> items."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except ValueError:
        raise NewsError("NSE announcements for %s are not JSON (NSE may have sent its block page)" % ticker)
    rows = doc.get("data", []) if isinstance(doc, dict) else doc
    if not isinstance(rows, list):
        raise NewsError("NSE announcements for %s are not the shape this tool knows" % ticker)
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        subject = " ".join(str(r.get("desc") or r.get("subject") or "announcement").split())
        detail = " ".join(str(r.get("attchmntText") or r.get("text") or "").split())
        company = r.get("sm_name") or ticker
        link = str(r.get("attchmntFile") or "")
        if link and not link.startswith("http"):
            link = NSE_FILE % link.lstrip("/")
        when = parse_nse_time(r.get("sort_date") or r.get("an_dt") or r.get("exchdisstime"))
        rid = str(r.get("seq_id") or r.get("an_dt") or "") + "|" + subject
        title = "%s: %s" % (company, subject)
        out.append({"id": "nse:%s:%s" % (ticker, rid), "source": "NSE filing", "kind": "filing",
                    "ticker": ticker, "title": title, "summary": detail[:400],
                    "important": bool(IMPORTANT_SUBJECTS.search(subject)),
                    "link": link or ("https://www.nseindia.com/get-quotes/equity?symbol=%s" % ticker),
                    "time": when})
    return out


def parse_chart(data, ticker):
    """Yahoo chart JSON -> {"ticker", "price", "prev_close", "pct", "time"} or raise."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        meta = doc["chart"]["result"][0]["meta"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise NewsError("chart for %s is not usable" % ticker)
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if not price or not prev:
        raise NewsError("chart for %s has no price" % ticker)
    when = meta.get("regularMarketTime")
    return {"ticker": ticker, "price": round(float(price), 2), "prev_close": round(float(prev), 2),
            "pct": round((float(price) / float(prev) - 1) * 100, 2),
            "time": _dt.datetime.fromtimestamp(when, _dt.timezone.utc) if when else None}


def collect_moves(fetcher, watch, errors=None):
    errors = [] if errors is None else errors
    out = []
    for t in sorted(watch):
        name = "chart-%s.json" % t
        try:
            try:
                data = fetcher.get(CHART % ("query2", yahoo_symbol(t)), name)
            except NewsError as exc:
                if fetcher.offline or not re.search(r"HTTP (429|5\d\d)", str(exc)):
                    raise
                data = fetcher.get(CHART % ("query1", yahoo_symbol(t)), name)
            out.append(parse_chart(data, t))
        except NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                errors.append("price for %s: %s" % (t, exc))
    return out


def name_variants(name):
    """'Tata Consultancy Services Ltd.' -> ['Tata Consultancy Services', 'Tata Consultancy']."""
    short = _short_name(name) if name else None
    if not short or len(short) < 4:
        return []
    out = [short]
    words = short.replace(".", " ").split()
    if len(words) >= 3 and len(" ".join(words[:2])) >= 8:
        out.append(" ".join(words[:2]))
    return out


def mention_patterns(watch):
    pats = {}
    for t, name in watch.items():
        alts = [r"\(%s\)" % re.escape(t), r"\b(?:NSE|BSE|NSEI)\s*:\s*%s\b" % re.escape(t),
                r"(?<![A-Za-z0-9&])%s(?![A-Za-z0-9&])" % re.escape(t)]      # TCS, M&M, as written
        if len(t) >= 5 and t.isalpha():
            alts.append(r"(?i:\b%s\b)" % re.escape(t))                       # RELIANCE / Reliance
        for v in name_variants(name):
            alts.append(r"(?i:\b%s\b)" % re.escape(v).replace(r"\ ", r"[\s-]"))
        pats[t] = re.compile("|".join(alts))
    return pats


def tag(items, watch):
    """Which of your tickers each item touches, and why it matters."""
    pats = mention_patterns(watch)
    for it in items:
        hay = "%s %s" % (it["title"], it.get("summary") or "")
        touches = {it["ticker"]} if it["ticker"] in watch else set()
        for t, rx in pats.items():
            if rx.search(hay):
                touches.add(t)
        it["touches"] = sorted(touches)
        own = pats.get(it["ticker"])
        text = it["title"] if it["source"].startswith(("GNews", "Google")) else hay
        it["about_symbol"] = it["kind"] == "filing" or own is None or bool(own.search(text))
        it["tags"] = [label for label, rx in KEYWORDS if re.search(rx, hay, re.I)]
        if it["kind"] == "filing" and re.search(r"financial result", it["title"], re.I) \
                and "earnings" not in it["tags"]:
            it["tags"].insert(0, "earnings")
    return items


def dedupe(items):
    """One item per story: same id, or same link, or same title the same day."""
    seen, out = {}, []
    for it in items:
        keys = [it["id"], it["link"],
                "%s|%s" % (re.sub(r"\W+", " ", it["title"].lower()).strip(),
                           it["time"].date() if it["time"] else "")]
        hit = next((seen[k] for k in keys if k and k in seen), None)
        if hit is not None:
            for t in it.get("touches", []):
                if t not in hit["touches"]:
                    hit["touches"].append(t)
            hit["touches"].sort()
            continue
        for k in keys:
            if k:
                seen[k] = it
        out.append(it)
    return out


def fingerprint(it):
    return hashlib.sha1(it["id"].encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- the check

def collect(fetcher, watch, state, nse=True, errors=None, gnews=True):
    errors = [] if errors is None else errors
    items = []
    for t in sorted(watch):
        if gnews:
            try:
                items += parse_rss(fetcher.get(GNEWS % gnews_query(t, watch.get(t)), "gnews-%s.xml" % t), t,
                                   "Google News")
            except NewsError as exc:
                if not (fetcher.offline and "no file" in str(exc)):
                    errors.append("Google News for %s: %s" % (t, exc))
        try:
            items += parse_rss(fetcher.get(YAHOO % yahoo_symbol(t), "yahoo-%s.xml" % t), t)
        except NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                errors.append("Yahoo headlines for %s: %s" % (t, exc))
    if nse:
        refused = False
        for t in sorted(watch):
            if refused:
                break
            try:
                items += parse_nse(fetcher.nse(NSE_ANN % urllib.parse.quote(t), "nse-%s.json" % t), t)
            except NewsError as exc:
                if fetcher.offline and "no file" in str(exc):
                    continue
                if re.search(r"HTTP (401|403)|not JSON", str(exc)):
                    refused = True
                else:
                    errors.append("NSE announcements for %s: %s" % (t, exc))
        if refused:
            items += collect_bse(fetcher, watch, errors)
    return items


def collect_bse(fetcher, watch, errors, days=7):
    """The same companies' filings from BSE, for when NSE turns the script away."""
    codes = bse_codes(fetcher)
    to = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=IST_HOURS)
    frm = (to - _dt.timedelta(days=days)).strftime("%Y%m%d")
    out, missing = [], []
    for t in sorted(watch):
        code = codes.get(t)
        if not code:
            missing.append(t)
            continue
        try:
            out += parse_bse(fetcher.bse(BSE_ANN % (frm, code, to.strftime("%Y%m%d")), "bse-%s.json" % t), t)
        except NewsError as exc:
            if fetcher.offline and "no file" in str(exc):
                continue
            errors.append("BSE announcements for %s: %s" % (t, exc))
    errors.append("NSE turned the script away, so company filings come from BSE (the same disclosures, "
                  "filed with both exchanges)")
    if missing:
        errors.append("no BSE code for %s: add it to trader/bse_codes.json, e.g. {\"%s\": \"500325\"}"
                      % (", ".join(missing), missing[0]))
    return out


def select(items, state, now, hours=48, show_all=False):
    """Items within the window; only unseen ones unless show_all."""
    seen = state.setdefault("seen", {})
    cutoff = now - _dt.timedelta(hours=hours)
    ahead = now + _dt.timedelta(minutes=10)  # a pinned --now: nothing from after it
    out = []
    for it in items:
        if it["time"] is not None and (it["time"] < cutoff or it["time"] > ahead):
            continue
        fp = fingerprint(it)
        it["new"] = fp not in seen
        if it["new"] or show_all:
            out.append(it)
    out.sort(key=lambda i: (i["time"] or now), reverse=True)
    return out


def remember(items, state, now):
    seen = state.setdefault("seen", {})
    stamp = now.isoformat()
    for it in items:
        seen.setdefault(fingerprint(it), stamp)
    cutoff = (now - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
    state["last_check"] = stamp


def render_moves(moves, move_pct=MOVE_PCT):
    out = []
    for m in moves:
        flag = "MOVING" if abs(m["pct"]) >= move_pct else ""
        when = (" at %s IST" % to_ist(m["time"]).strftime("%H:%M")) if m.get("time") else ""
        out.append("%-10s Rs %s %+.2f%% vs yesterday's close Rs %s%s  %s" % (
            m["ticker"], "{:,.2f}".format(m["price"]), m["pct"], "{:,.2f}".format(m["prev_close"]),
            when, flag))
    return out


def render(items, errors, now, moves=None, move_pct=MOVE_PCT):
    out = render_moves(moves or [], move_pct)
    if out:
        out.append("")
    if not items:
        out.append("Nothing new.")
    for it in items:
        when = to_ist(it["time"]).strftime("%Y-%m-%d %H:%M IST") if it["time"] else "time unknown"
        mark = "!" if it.get("important") else " "
        who = ",".join(it["touches"]) or it["ticker"]
        out.append("%s %s  %-11s %-20s %s" % (mark, when, who, it["source"][:20], it["title"]))
        extra = []
        if it["tags"]:
            extra.append("tags: " + ", ".join(it["tags"]))
        extra.append(it["link"])
        out.append("      " + "  ".join(extra))
    for e in errors:
        out.append("note: %s" % e)
    out.append("Checked %s. Headlines are leads, not facts; open the story or the filing before acting. "
               "Not financial advice." % to_ist(now).strftime("%Y-%m-%d %H:%M IST"))
    return "\n".join(out) + "\n"


def _json_ready(items):
    out = []
    for it in items:
        d = dict(it)
        d["time"] = it["time"].isoformat() if it["time"] else None
        out.append(d)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tickers", nargs="*", help="default: watchlist + plan + portfolio")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--state", default="trader/state/news.json")
    ap.add_argument("--hours", type=float, default=48, help="ignore items older than this")
    ap.add_argument("--all", action="store_true", help="show seen items too")
    ap.add_argument("--no-nse", action="store_true", help="skip NSE / BSE corporate announcements")
    ap.add_argument("--loose", action="store_true",
                    help="keep headlines that do not name the stock (search noise: other companies, price pages)")
    ap.add_argument("--no-gnews", action="store_true", help="skip Google News")
    ap.add_argument("--universe", default="trader/universe.txt", help="SYMBOL|Name list for company names")
    ap.add_argument("--no-moves", action="store_true", help="skip the price line per ticker")
    ap.add_argument("--move-pct", type=float, default=MOVE_PCT, help="flag a move this big (percent)")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO time, for reproducible runs")
    ap.add_argument("--dry-run", action="store_true", help="do not update the state file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.tickers:
        watch = {t.upper().replace(".NS", ""): None for t in args.tickers}
        known = watch_from_files(args.portfolio, args.watchlist, args.plan)
        watch.update({t: known[t] for t in watch if known.get(t)})
    else:
        watch = watch_from_files(args.portfolio, args.watchlist, args.plan)
    if not watch:
        print("news: no symbols. Pass --tickers, or run /trader-scanner first (it writes "
              "trader/watchlist.json).", file=sys.stderr)
        return 2
    now = parse_time(args.now) if args.now else _dt.datetime.now(_dt.timezone.utc)
    state = load_json(args.state) or {}
    errors = []
    names = names_from_universe(args.universe)
    for t in watch:
        if not watch[t] and names.get(t):
            watch[t] = names[t]
    fetcher = Fetcher(offline=args.offline)
    items = collect(fetcher, watch, state, nse=not args.no_nse, errors=errors, gnews=not args.no_gnews)
    items = dedupe(tag(items, watch))
    off_topic = [i for i in items if not i.get("about_symbol", True)]
    if not args.loose and off_topic:
        items = [i for i in items if i.get("about_symbol", True)]
        errors.append("left out %d headline%s that did not name the stock (search noise; --loose shows them)"
                      % (len(off_topic), "" if len(off_topic) == 1 else "s"))
    shown = select(items, state, now, hours=args.hours, show_all=args.all)
    moves = [] if args.no_moves else collect_moves(fetcher, watch, errors)
    if args.json:
        mv = [dict(m, time=m["time"].isoformat() if m.get("time") else None,
                   moving=abs(m["pct"]) >= args.move_pct) for m in moves]
        print(json.dumps({"checked": now.isoformat(), "moves": mv, "items": _json_ready(shown),
                          "notes": errors}, indent=2))
    else:
        sys.stdout.write(render(shown, errors, now, moves, args.move_pct))
    if not args.dry_run:
        remember(items, state, now)
        folder = os.path.dirname(args.state)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
    return 0 if any(i["new"] for i in shown) else 1


if __name__ == "__main__":
    sys.exit(main())
