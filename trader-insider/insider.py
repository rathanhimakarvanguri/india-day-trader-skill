#!/usr/bin/env python3
"""Insider and big-money tracker for trader-insider. Standard library only.

The Indian stand-in for the US "Pelosi tracker". India's MPs do not file
per-trade stock reports, but two public NSE feeds show who is buying and
selling a listed company's shares:

  pit     Insider trading disclosures under SEBI's Prohibition of Insider
          Trading (PIT) Regulations, 2015. Promoters, promoter-group members,
          directors, key managerial people and designated persons must tell
          the company within 2 trading days when their trades in a calendar
          quarter go over Rs 10 lakh, and the company tells the exchange
          within 2 trading days after that (Regulation 7(2)).
            https://www.nseindia.com/api/corporates-pit?index=equities&symbol=<SYM>
                &from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
  deals   Bulk deals (one client trades more than 0.5 % of a company's shares
          in a day) and block deals (large negotiated trades in the block
          window), reported by NSE at the end of each trading day.
            https://nsearchives.nseindia.com/content/equities/bulk.csv
            https://nsearchives.nseindia.com/content/equities/block.csv

    python3 insider.py pit --symbols RELIANCE,TCS              # last 30 days of insider trades
    python3 insider.py pit --watchlist --days 90 --buys        # buys only, every symbol you watch
    python3 insider.py pit --symbols INFY --promoters          # promoters and promoter group only
    python3 insider.py deals                                   # today's bulk and block deals
    python3 insider.py deals --kind block --symbols RELIANCE
    python3 insider.py new --watchlist                         # only what is new since last check

What it is, and is not:
  - Public filings, read quickly. Nothing here is inside information, and a
    promoter's buy is not a tip: they disclose days after the trade, and
    pledges, ESOP allotments and inter-se transfers are not market bets.
  - A bulk or block deal shows who traded, not why. A fund can be on both
    sides of a deal on the same day.

NSE's site sets cookies on its home page and turns away bare scripts, so this
opens https://www.nseindia.com/ once and keeps the cookies. If NSE still says
no (HTTP 401 / 403), it says so: open nseindia.com > Corporate filings >
Insider trading in a browser, download the CSV and pass --offline DIR.

State: `new` remembers what it showed in trader/state/insider.json, so each
filing alerts once. Offline: --offline DIR reads pit-<SYMBOL>.json, bulk.csv
and block.csv from DIR. The tests use it.
Exit code 0 when something was found, 1 when nothing was, 2 on an error.
"""

import argparse
import csv
import datetime as _dt
import gzip
import hashlib
import http.cookiejar
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

NSE_HOME = "https://www.nseindia.com/"
PIT_URL = ("https://www.nseindia.com/api/corporates-pit?index=equities&symbol=%s"
           "&from_date=%s&to_date=%s")
DEALS_URL = "https://nsearchives.nseindia.com/content/equities/%s.csv"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
IST = _dt.timedelta(hours=5, minutes=30)
KEEP_DAYS = 120
NOTE = ("Public filings, read quickly. Not inside information and not a tip: insiders disclose after "
        "the trade, and a deal shows who traded, not why.")

PROMOTER = re.compile(r"promoter", re.I)
MARKET_MODES = re.compile(r"market (purchase|sale)|open market|on market", re.I)
NOT_A_BET = re.compile(r"pledge|revok|invoc|esop|esos|allot|inter[- ]?se|gift|transmission|inherit|"
                       r"bonus|rights|conversion|merger|scheme", re.I)


class InsiderError(Exception):
    pass


# ---------------------------------------------------------------- small helpers

def ist_now():
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) + IST


def parse_day(text):
    """'13-Nov-2026', '13-11-2026', '2026-11-13', '13-NOV-2026 18:01' -> date or None."""
    t = (text or "").strip()
    if not t:
        return None
    t = t.split(" ")[0] if re.match(r"^\d{1,2}-[A-Za-z]{3}-\d{4}\s", t) else t
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d %b %Y", "%d-%B-%Y"):
        try:
            return _dt.datetime.strptime(t[:11].strip() if fmt == "%d-%b-%Y" else t, fmt).date()
        except ValueError:
            continue
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})", t)
    if m:
        try:
            return _dt.datetime.strptime("%s-%s-%s" % (m.group(1), m.group(2).title(), m.group(3)),
                                         "%d-%b-%Y").date()
        except ValueError:
            return None
    return None


def num(x):
    """'1,23,456' / '1234.5' / 1234 / '-' -> float or None."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    t = str(x).replace(",", "").strip()
    if t in ("", "-", "NA", "N.A.", "nil", "Nil"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def inr_group(n):
    s = str(int(abs(n)))
    if len(s) > 3:
        head, tail, parts = s[:-3], s[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + s


def crore(x):
    """Rupees -> 'Rs 12.34 cr' or 'Rs 8.5 lakh' (how Indian filings and news say it)."""
    if not x:
        return "no value filed"
    if abs(x) >= 1e7:
        return "Rs %.2f cr" % (x / 1e7)
    if abs(x) >= 1e5:
        return "Rs %.1f lakh" % (x / 1e5)
    return "Rs %s" % inr_group(round(x))


def first(row, *keys):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def fingerprint(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def save_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


def watch_symbols(watchlist="trader/watchlist.json", plan="trader/plan.json", portfolio="trader/portfolio.json"):
    out = []
    for h in (load_json(watchlist) or {}).get("hits", []):
        if h.get("symbol"):
            out.append(h["symbol"].upper())
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.append(pl["symbol"].upper())
    for p in (load_json(portfolio) or {}).get("positions", []):
        s = p.get("ticker") or p.get("symbol")
        if s:
            out.append(s.upper())
    seen, uniq = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, offline=None, pause=0.4):
        self.offline = offline
        self.pause = pause
        self._last = 0.0
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._warm = False

    def _file(self, name):
        path = os.path.join(self.offline, name)
        if not os.path.isfile(path):
            raise InsiderError("offline: no file %s" % path)
        with open(path, "rb") as fh:
            data = fh.read()
        return gzip.decompress(data) if name.endswith(".gz") else data

    def get(self, url, name, accept="*/*", referer=None):
        if self.offline:
            return self._file(name)
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        h = {"User-Agent": BROWSER_UA, "Accept": accept, "Accept-Language": "en-IN,en;q=0.9",
             "Accept-Encoding": "gzip"}
        if referer:
            h["Referer"] = referer
        try:
            with self._opener.open(urllib.request.Request(url, headers=h), timeout=30) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as e:
            raise InsiderError("HTTP %d for %s" % (e.code, url.split("?")[0]))
        except urllib.error.URLError as e:
            raise InsiderError("could not reach %s: %s" % (url.split("/")[2], e.reason))

    def nse_api(self, url, name):
        if not self.offline and not self._warm:
            self.get(NSE_HOME, "", accept="text/html")
            self._warm = True
        return self.get(url, name, accept="application/json", referer=NSE_HOME)


# ---------------------------------------------------------------- PIT disclosures

def parse_pit(data, symbol=None):
    """NSE corporates-pit JSON ({"data": [...]} or a list) -> clean rows.
    The field names NSE uses (acqName, personCategory, secAcq, secVal, tdpTransactionType,
    acqMode, acqfromDt, acqtoDt, intimDt, date, befAcqSharesPer, afterAcqSharesPer) are read
    with fallbacks, since NSE renames fields from time to time."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except ValueError:
        raise InsiderError("the insider-trading answer for %s is not JSON (NSE may have sent its block page)"
                           % (symbol or "the query"))
    rows = doc.get("data", []) if isinstance(doc, dict) else doc
    if not isinstance(rows, list):
        raise InsiderError("the insider-trading answer is not the shape this tool knows")
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = str(first(r, "symbol", "SYMBOL") or symbol or "").upper()
        who = " ".join(str(first(r, "acqName", "personName", "name") or "unknown").split())
        cat = " ".join(str(first(r, "personCategory", "category") or "").split())
        txn = " ".join(str(first(r, "tdpTransactionType", "transactionType", "acqType") or "").split())
        mode = " ".join(str(first(r, "acqMode", "modeOfAcq", "mode") or "").split())
        shares = num(first(r, "secAcq", "noOfShareAcq", "quantity"))
        value = num(first(r, "secVal", "valueOfSecurity", "value"))
        sec_type = str(first(r, "secType", "securityType") or "Equity Shares")
        t_from = parse_day(first(r, "acqfromDt", "fromDate", "acqFromDate"))
        t_to = parse_day(first(r, "acqtoDt", "toDate", "acqToDate")) or t_from
        told_co = parse_day(first(r, "intimDt", "intimationDate"))
        filed = parse_day(first(r, "date", "broadcastDate", "disclosureDate")) or told_co
        before = num(first(r, "befAcqSharesPer", "beforeAcqPer"))
        after = num(first(r, "afterAcqSharesPer", "afterAcqPer"))
        side = "buy" if re.search(r"buy|acqui|purchase", txn + " " + mode, re.I) else \
            ("sell" if re.search(r"sell|sale|dispos", txn + " " + mode, re.I) else (txn.lower() or "other"))
        if re.search(r"pledge", txn + " " + mode, re.I):
            side = "pledge" if not re.search(r"revok|release", txn + " " + mode, re.I) else "pledge released"
        price = round(value / shares, 2) if value and shares else None
        lag = (filed - t_to).days if filed and t_to else None
        out.append({
            "symbol": sym, "company": first(r, "company", "companyName") or sym, "person": who,
            "category": cat, "side": side, "transaction": txn, "mode": mode, "security": sec_type,
            "shares": int(shares) if shares is not None else None, "value_inr": value, "avg_price": price,
            "traded_from": t_from.isoformat() if t_from else None, "traded_to": t_to.isoformat() if t_to else None,
            "filed": filed.isoformat() if filed else None, "days_to_disclose": lag,
            "holding_before_pct": before, "holding_after_pct": after,
            "promoter": bool(PROMOTER.search(cat)), "market_trade": bool(MARKET_MODES.search(mode)),
            "not_a_bet": bool(NOT_A_BET.search(mode + " " + txn)),
            "xbrl": first(r, "xbrl", "attachment"),
            "id": fingerprint(sym, who, txn, mode, shares, value, t_from, filed),
        })
    return out


def select_pit(rows, since=None, buys=False, sells=False, promoters=False, market_only=False, min_value=None):
    out = []
    for r in rows:
        if since and r["filed"] and r["filed"] < since.isoformat():
            continue
        if buys and r["side"] != "buy":
            continue
        if sells and r["side"] != "sell":
            continue
        if promoters and not r["promoter"]:
            continue
        if market_only and not r["market_trade"]:
            continue
        if min_value and (r["value_inr"] or 0) < min_value:
            continue
        out.append(r)
    out.sort(key=lambda r: (r["filed"] or "", r["value_inr"] or 0), reverse=True)
    return out


def describe_pit(r):
    shares = ("%s shares" % inr_group(r["shares"])) if r["shares"] is not None else "shares n/a"
    at = (" at about Rs %.2f" % r["avg_price"]) if r["avg_price"] else ""
    when = r["traded_from"] or "?"
    if r["traded_to"] and r["traded_to"] != r["traded_from"]:
        when += " to " + r["traded_to"]
    hold = ""
    if r["holding_before_pct"] is not None and r["holding_after_pct"] is not None:
        hold = ", holding %.2f%% -> %.2f%%" % (r["holding_before_pct"], r["holding_after_pct"])
    lag = (", disclosed %d day%s later" % (r["days_to_disclose"], "" if r["days_to_disclose"] == 1 else "s")) \
        if r["days_to_disclose"] is not None else ""
    flag = ""
    if r["not_a_bet"]:
        flag = "  (not a market bet: %s)" % (r["mode"] or r["transaction"])
    elif r["promoter"] and r["side"] == "buy" and r["market_trade"]:
        flag = "  <- promoter buying in the market"
    return ("%-10s %-4s %s, %s (%s): %s %s%s, %s, traded %s%s%s%s"
            % (r["symbol"], r["side"].upper()[:4], r["person"][:40], r["category"] or "insider",
               r["mode"] or r["transaction"] or "mode n/a", r["side"], shares, at, crore(r["value_inr"]),
               when, hold, lag, flag))


# ---------------------------------------------------------------- bulk and block deals

def parse_deals(data, kind):
    """NSE's bulk.csv / block.csv -> rows. Columns: Date, Symbol, Security Name, Client Name,
    Buy/Sell, Quantity Traded, Trade Price / Wght. Avg. Price, Remarks."""
    text = data.decode("utf-8-sig", "replace") if isinstance(data, bytes) else data
    rdr = csv.reader(io.StringIO(text.replace("\r", "")))
    try:
        hdr = [" ".join(h.strip().upper().split()) for h in next(rdr)]
    except StopIteration:
        return []

    def col(*names):
        for n in names:
            for i, h in enumerate(hdr):
                if h.startswith(n):
                    return i
        return None
    ci = {"date": col("DATE"), "symbol": col("SYMBOL"), "name": col("SECURITY NAME", "SECURITY"),
          "client": col("CLIENT NAME", "CLIENT"), "side": col("BUY/SELL", "BUY / SELL", "BUY"),
          "qty": col("QUANTITY TRADED", "QUANTITY"), "price": col("TRADE PRICE", "PRICE", "WGHT")}
    if ci["symbol"] is None or ci["qty"] is None:
        raise InsiderError("%s.csv is not NSE's deals file (header %s)" % (kind, ",".join(hdr)[:80]))
    out = []
    for rec in rdr:
        if not rec or not any(x.strip() for x in rec):
            continue

        def g(k):
            i = ci[k]
            return rec[i].strip() if i is not None and i < len(rec) else ""
        if "NO RECORD" in " ".join(rec).upper():
            continue
        qty, price = num(g("qty")), num(g("price"))
        d = parse_day(g("date"))
        side = g("side").strip().upper()
        out.append({"kind": kind, "date": d.isoformat() if d else None, "symbol": g("symbol").upper(),
                    "company": g("name"), "client": " ".join(g("client").split()),
                    "side": "buy" if side.startswith("B") else ("sell" if side.startswith("S") else side.lower()),
                    "shares": int(qty) if qty is not None else None, "price": price,
                    "value_inr": round(qty * price, 2) if qty and price else None,
                    "id": fingerprint(kind, d, g("symbol"), g("client"), side, qty, price)})
    return out


def consolidate_deals(rows, round_trip_pct=10.0):
    """Group deals by (symbol, client).
    - The same trade often appears in BOTH bulk.csv and block.csv (a block trade that is also over
      0.5 % of the company): same date, symbol, client, side, qty and price -> one row, kind "bulk+block".
    - A client who bought AND sold within round_trip_pct of the same quantity that day is a round trip:
      market makers and high-frequency desks do this all day. It is shown once, with the net, apart.
    Returns (one_sided, round_trips), each biggest first."""
    seen, uniq = {}, []
    for r in rows:
        key = (r["date"], r["symbol"], r["client"].upper(), r["side"], r["shares"], r["price"])
        if key in seen:
            k = seen[key]
            if r["kind"] not in k["kind"].split("+"):
                k["kind"] = "+".join(sorted(k["kind"].split("+") + [r["kind"]]))
            continue
        r = dict(r)
        seen[key] = r
        uniq.append(r)
    groups = {}
    for r in uniq:
        groups.setdefault((r["symbol"], r["client"].upper()), []).append(r)
    one_sided, trips = [], []
    for (sym, client), g in groups.items():
        bq = sum(x["shares"] or 0 for x in g if x["side"] == "buy")
        sq = sum(x["shares"] or 0 for x in g if x["side"] == "sell")
        bv = sum(x["value_inr"] or 0 for x in g if x["side"] == "buy")
        sv = sum(x["value_inr"] or 0 for x in g if x["side"] == "sell")
        if bq and sq and abs(bq - sq) <= round_trip_pct / 100.0 * max(bq, sq):
            trips.append({"kind": "/".join(sorted({x["kind"] for x in g})), "symbol": sym, "client": g[0]["client"],
                          "date": g[0]["date"], "bought": bq, "sold": sq, "net_shares": bq - sq,
                          "bought_inr": round(bv, 2), "sold_inr": round(sv, 2), "gross_inr": round(bv + sv, 2),
                          "company": g[0]["company"], "round_trip": True})
        else:
            one_sided.extend(g)
    one_sided.sort(key=lambda r: -(r["value_inr"] or 0))
    trips.sort(key=lambda r: -r["gross_inr"])
    return one_sided, trips


def describe_trip(r):
    return ("%-10s %-11s %s bought %s and sold %s shares the same day (net %s%s), Rs %.2f cr each way"
            % (r["symbol"], r["kind"], r["client"][:44], inr_group(r["bought"]), inr_group(r["sold"]),
               "+" if r["net_shares"] >= 0 else "-", inr_group(abs(r["net_shares"])),
               (r["bought_inr"] + r["sold_inr"]) / 2 / 1e7))


def describe_deal(r):
    return ("%-10s %-11s %-4s %s %s shares at Rs %s = %s, %s"
            % (r["symbol"], r["kind"], r["side"].upper(), r["client"][:44],
               inr_group(r["shares"]) if r["shares"] is not None else "?",
               ("%.2f" % r["price"]) if r["price"] is not None else "?", crore(r["value_inr"]), r["date"] or ""))


# ---------------------------------------------------------------- commands

def _symbols(a):
    syms = []
    if a.symbols:
        syms = [s.strip().upper().replace(".NS", "") for s in re.split(r"[,\s]+", a.symbols) if s.strip()]
    if a.watchlist:
        syms += [s for s in watch_symbols() if s not in syms]
    return syms


def fetch_pit(fetcher, syms, days, today, errors):
    rows = []
    frm, to = (today - _dt.timedelta(days=days)).strftime("%d-%m-%Y"), today.strftime("%d-%m-%Y")
    for s in syms:
        try:
            rows += parse_pit(fetcher.nse_api(PIT_URL % (urllib.parse.quote(s), frm, to), "pit-%s.json" % s), s)
        except InsiderError as e:
            errors.append("insider trades for %s: %s" % (s, e))
            if re.search(r"HTTP (401|403)", str(e)):
                errors.append("NSE turned the script away. Open nseindia.com > Corporate filings > Insider "
                              "trading in a browser, or save the JSON as pit-<SYMBOL>.json and use --offline DIR")
                break
    return rows


def fetch_deals(fetcher, kinds, errors):
    rows = []
    for k in kinds:
        try:
            rows += parse_deals(fetcher.get(DEALS_URL % k, "%s.csv" % k, accept="text/csv"), k)
        except InsiderError as e:
            errors.append("%s deals: %s" % (k, e))
    return rows


def cmd_pit(a, fetcher, today):
    syms = _symbols(a)
    if not syms:
        raise InsiderError("which stocks? --symbols RELIANCE,TCS or --watchlist (trader/watchlist.json, plan, portfolio)")
    errors = []
    rows = fetch_pit(fetcher, syms, a.days, today, errors)
    since = today - _dt.timedelta(days=a.days)
    sel = select_pit(rows, since, a.buys, a.sells, a.promoters, a.market_only, a.min_value)
    if a.json:
        print(json.dumps({"symbols": syms, "days": a.days, "rows": sel, "notes": errors, "note": NOTE}, indent=2))
        return 0 if sel else 1
    print("Insider trades (SEBI PIT disclosures on NSE) for %s, filed in the last %d days%s:"
          % (", ".join(syms), a.days, _filters(a)))
    for r in sel[:a.show]:
        print("  " + describe_pit(r))
    if not sel:
        print("  none")
    elif len(sel) > a.show:
        print("  ... and %d more (--show N)." % (len(sel) - a.show))
    _summary(sel)
    for e in errors:
        print("note: " + e)
    print(NOTE)
    return 0 if sel else 1


def _filters(a):
    f = []
    if a.buys:
        f.append("buys")
    if a.sells:
        f.append("sells")
    if a.promoters:
        f.append("promoters")
    if a.market_only:
        f.append("market trades")
    if a.min_value:
        f.append("over %s" % crore(a.min_value))
    return (" (" + ", ".join(f) + ")") if f else ""


def _summary(rows):
    by = {}
    for r in rows:
        if r["not_a_bet"] or r["side"] not in ("buy", "sell") or r["value_inr"] is None:
            continue
        b = by.setdefault(r["symbol"], {"buy": 0.0, "sell": 0.0})
        b[r["side"]] += r["value_inr"]
    for s, b in sorted(by.items()):
        net = b["buy"] - b["sell"]
        print("  %s: insiders bought %s and sold %s in the market (net %s%s)."
              % (s, crore(b["buy"]), crore(b["sell"]), "+" if net >= 0 else "-", crore(abs(net))))


def cmd_deals(a, fetcher, today):
    kinds = ["bulk", "block"] if a.kind == "both" else [a.kind]
    errors = []
    rows = fetch_deals(fetcher, kinds, errors)
    syms = _symbols(a)
    if syms:
        rows = [r for r in rows if r["symbol"] in syms]
    if a.min_value:
        rows = [r for r in rows if (r["value_inr"] or 0) >= a.min_value]
    one, trips = consolidate_deals(rows)
    if a.all:
        one, trips = sorted(rows, key=lambda r: -(r["value_inr"] or 0)), []
    if a.json:
        print(json.dumps({"kinds": kinds, "symbols": syms, "rows": one, "round_trips": trips, "notes": errors,
                          "note": NOTE}, indent=2))
        return 0 if (one or trips) else 1
    dates = sorted({r["date"] for r in rows if r["date"]})
    print("NSE %s deals%s%s: %d one-sided, biggest first%s."
          % (" and ".join(kinds), (" for " + ", ".join(syms)) if syms else "",
             (" (%s)" % ", ".join(dates)) if dates else "", len(one),
             (", then %d same-day round trip%s" % (len(trips), "" if len(trips) == 1 else "s")) if trips else ""))
    for r in one[:a.show]:
        print("  " + describe_deal(r))
    if not one:
        print("  none")
    elif len(one) > a.show:
        print("  ... and %d more (--show N)." % (len(one) - a.show))
    if trips:
        print("Round trips (bought and sold about the same quantity the same day: usually market makers or "
              "high-frequency desks, not a view on the stock):")
        for r in trips[:a.show]:
            print("  " + describe_trip(r))
        if len(trips) > a.show:
            print("  ... and %d more (--show N)." % (len(trips) - a.show))
    for e in errors:
        print("note: " + e)
    print(NOTE)
    return 0 if (one or trips) else 1


def cmd_new(a, fetcher, today):
    syms = _symbols(a)
    errors = []
    state = load_json(a.state) or {}
    seen = state.setdefault("seen", {})
    first_run = not seen
    fresh = []
    if syms:
        for r in select_pit(fetch_pit(fetcher, syms, a.days, today, errors), today - _dt.timedelta(days=a.days)):
            if r["id"] not in seen:
                fresh.append(("pit", r))
    for r in fetch_deals(fetcher, ["bulk", "block"], errors):
        if syms and r["symbol"] not in syms:
            continue
        if r["id"] not in seen:
            fresh.append(("deal", r))
    stamp = today.isoformat()
    for _, r in fresh:
        seen[r["id"]] = stamp
    cutoff = (today - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
    state["last_check"] = stamp
    if not a.dry_run:
        save_json(a.state, state)
    if a.json:
        print(json.dumps({"new": [dict(r, source=k) for k, r in fresh], "first_run": first_run, "notes": errors},
                         indent=2))
        return 0 if fresh else 1
    if first_run and fresh:
        print("First check: everything below is marked seen now; next time only new filings show.")
    print("%d new since the last check%s:" % (len(fresh), (" for " + ", ".join(syms)) if syms else " (deals: all NSE)"))
    for k, r in fresh[:a.show]:
        print("  " + (describe_pit(r) if k == "pit" else describe_deal(r)))
    for e in errors:
        print("note: " + e)
    print(NOTE)
    return 0 if fresh else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Insider trades and bulk / block deals on NSE (trader-insider).")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--symbols", help="comma-separated NSE symbols")
        p.add_argument("--watchlist", action="store_true",
                       help="add every symbol in trader/watchlist.json, plan.json and portfolio.json")
        p.add_argument("--offline", metavar="DIR", help="read pit-<SYM>.json, bulk.csv, block.csv from DIR")
        p.add_argument("--today", help="YYYY-MM-DD (default: today in India)")
        p.add_argument("--min-value", type=float, help="only trades worth at least this many rupees")
        p.add_argument("--show", type=int, default=40)
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("pit", help="insider trades (SEBI PIT disclosures)")
    common(p)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--buys", action="store_true")
    p.add_argument("--sells", action="store_true")
    p.add_argument("--promoters", action="store_true", help="promoters and promoter group only")
    p.add_argument("--market-only", action="store_true", help="market purchases and sales only")
    p = sub.add_parser("deals", help="today's bulk and block deals")
    common(p)
    p.add_argument("--kind", choices=["bulk", "block", "both"], default="both")
    p.add_argument("--all", action="store_true", help="every row as NSE lists it: no netting, no de-duplication")
    p = sub.add_parser("new", help="only what is new since the last check")
    common(p)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--state", default="trader/state/insider.json")
    p.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        today = _dt.date.fromisoformat(a.today) if a.today else ist_now().date()
        fetcher = Fetcher(offline=a.offline)
        return {"pit": cmd_pit, "deals": cmd_deals, "new": cmd_new}[a.cmd](a, fetcher, today)
    except (InsiderError, ValueError) as e:
        print("insider.py: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
