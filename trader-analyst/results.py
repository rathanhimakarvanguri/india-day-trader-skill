#!/usr/bin/env python3
"""Quarterly results reader for trader-analyst. Standard library only.

Pulls a listed company's quarterly results as filed with NSE (the XBRL file
every company must file with its results under SEBI's LODR Regulation 33) and
lays out what changed, quarter by quarter: revenue from operations, operating
profit and its margin, profit before tax, net profit and its margin, EPS, and
growth against the quarter before (QoQ) and the same quarter a year earlier
(YoY). Rupee figures print in crore (1 crore = 10 million).

    python3 results.py RELIANCE
    python3 results.py TCS INFY --quarters 8
    python3 results.py HDFCBANK --standalone          # the parent company alone
    python3 results.py RELIANCE --json
    python3 results.py RELIANCE TCS --metrics trader/metrics.json
    python3 results.py --xbrl saved-results.xml       # read one saved XBRL file

Sources (free, public; NSE's site sets cookies on its home page first, so the
tool opens https://www.nseindia.com/ once and keeps them):
  https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol=<SYM>&period=Quarterly
      the list of result filings: period, consolidated or standalone,
      audited or not, filing date and the link to each XBRL file
  each filing's XBRL (nsearchives.nseindia.com/corporate/xbrl/...)

How the quarters are built:
  - One filing per quarter end. Consolidated by default (the group, which is
    what results coverage and the market quote), standalone with --standalone;
    a company that files only one kind is read as filed. When a quarter was
    filed twice (a revision), the later filing wins.
  - In each XBRL file the tool keeps the facts whose context covers that
    quarter (about three months ending on the filing's period end), so
    year-to-date columns in the same file are not mixed in.
  - Concepts (Ind AS, NSE's in-capmkt taxonomy), read by name:
      revenue          RevenueFromOperations
      other income     OtherIncome
      total income     Income
      finance costs    FinanceCosts
      depreciation     DepreciationDepletionAndAmortisationExpense
      profit before tax ProfitBeforeTax
      net profit       ProfitLossForPeriod (the owners' share,
                       ProfitOrLossAttributableToOwnersOfParent, when filed)
      EPS              BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations
                       (or ...FromContinuingOperations), diluted likewise
    operating profit = profit before tax + finance costs - other income
    (an EBIT-style number; banks and NBFCs file a different schedule, so for
    them it can be blank and "revenue" means interest earned when filed).

--metrics FILE merges one row per symbol into a JSON file. Offline:
--offline DIR reads results-<SYM>.json and the XBRL files (by their file
name) from DIR. Numbers only: this tool never says whether a stock is a buy.
"""

import argparse
import datetime as _dt
import gzip
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

NSE_HOME = "https://www.nseindia.com/"
LIST_URL = "https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol=%s&period=Quarterly"
YAHOO_TS = ("https://%s.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/%s?symbol=%s"
            "&type=%s&period1=%d&period2=%d")
YAHOO_TYPES = {  # Yahoo's quarterly series -> our fields (Yahoo's own definitions, not NSE's XBRL)
    "quarterlyTotalRevenue": "revenue", "quarterlyOperatingIncome": "operating_profit",
    "quarterlyPretaxIncome": "pbt", "quarterlyNetIncomeCommonStockholders": "net_profit_owners",
    "quarterlyNetIncome": "net_profit_total", "quarterlyBasicEPS": "eps_basic", "quarterlyDilutedEPS": "eps_diluted",
    "quarterlyInterestExpense": "finance_costs",
}
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
CRORE = 1e7
CONCEPTS = {
    "revenue": ("RevenueFromOperations", "RevenueFromOperationsNet", "InterestEarned", "TotalRevenueFromOperations"),
    "other_income": ("OtherIncome",),
    "total_income": ("Income", "TotalIncome"),
    "finance_costs": ("FinanceCosts", "InterestExpended"),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense", "DepreciationAndAmortisationExpense"),
    "pbt": ("ProfitBeforeTax", "ProfitLossBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax"),
    "net_profit_total": ("ProfitLossForPeriod", "ProfitLossForThePeriod", "NetProfitLossForThePeriod"),
    "net_profit_owners": ("ProfitOrLossAttributableToOwnersOfParent", "ProfitLossAttributableToOwnersOfParent"),
    "eps_basic": ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                  "BasicEarningsLossPerShareFromContinuingOperations", "BasicEarningsPerShareAfterExtraordinaryItems",
                  "BasicEarningsLossPerShare"),
    "eps_diluted": ("DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                    "DilutedEarningsLossPerShareFromContinuingOperations",
                    "DilutedEarningsPerShareAfterExtraordinaryItems", "DilutedEarningsLossPerShare"),
}


class ResultsError(Exception):
    pass


# ---------------------------------------------------------------- dates and numbers

def parse_day(text):
    t = (text or "").strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return _dt.datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})", t)
    if m:
        try:
            return _dt.datetime.strptime("%s-%s-%s" % (m.group(1), m.group(2).title(), m.group(3)), "%d-%b-%Y").date()
        except ValueError:
            return None
    return None


def pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return round((a / b - 1) * 100 * (1 if b > 0 else -1), 1)


def margin(part, whole):
    if part is None or not whole:
        return None
    return round(100.0 * part / whole, 1)


def fy_label(end):
    """Quarter end -> Indian fiscal label: 2026-09-30 -> 'Q2 FY27' (April to March year)."""
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(end.month)
    fy = end.year + 1 if end.month >= 4 else end.year
    return ("Q%d FY%02d" % (q, fy % 100)) if q else end.strftime("%b %Y")


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, offline=None, pause=0.5):
        self.offline = offline
        self.pause = pause
        self._last = 0.0
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._warm = False

    def get(self, url, name, accept="*/*"):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise ResultsError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                data = fh.read()
            return gzip.decompress(data) if name.endswith(".gz") else data
        if not self._warm and "nseindia.com" in url:
            self._warm = True
            self.get(NSE_HOME, "", accept="text/html")
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        h = {"User-Agent": BROWSER_UA, "Accept": accept, "Accept-Encoding": "gzip",
             "Accept-Language": "en-IN,en;q=0.9", "Referer": NSE_HOME}
        try:
            with self._opener.open(urllib.request.Request(url, headers=h), timeout=40) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as e:
            raise ResultsError("HTTP %d for %s" % (e.code, url.split("?")[0]))
        except urllib.error.URLError as e:
            raise ResultsError("could not reach %s: %s" % (url.split("/")[2], e.reason))


# ---------------------------------------------------------------- the filings list

def parse_list(data, symbol):
    """NSE's corporates-financial-results JSON -> filings, newest period first."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except ValueError:
        raise ResultsError("the results list for %s is not JSON (NSE may have sent its block page)" % symbol)
    rows = doc.get("data", []) if isinstance(doc, dict) else doc
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        end = parse_day(r.get("toDate") or r.get("to_date") or r.get("periodEnded"))
        start = parse_day(r.get("fromDate") or r.get("from_date"))
        xbrl = str(r.get("xbrl") or r.get("xbrlFile") or "").strip()
        if not end or not xbrl or xbrl in ("-", "null"):
            continue
        cons = str(r.get("consolidated") or r.get("relatingTo") or "").lower()
        kind = "consolidated" if cons.startswith("consol") else ("standalone" if cons.startswith(("stand", "non"))
                                                                  else (cons or "standalone"))
        out.append({"symbol": symbol, "company": r.get("companyName") or symbol, "start": start, "end": end,
                    "kind": kind, "audited": str(r.get("audited") or "").strip(),
                    "period": str(r.get("period") or "Quarterly"),
                    "filed": parse_day(r.get("filingDate") or r.get("broadCastDate") or r.get("broadcastDate")),
                    "xbrl": xbrl, "bank": str(r.get("bank") or "").upper().startswith(("Y", "B"))})
    out.sort(key=lambda f: (f["end"], f["filed"] or _dt.date.min), reverse=True)
    return out


def pick_filings(filings, kind="consolidated", n=8):
    """One filing per quarter end: the asked-for kind if filed, else the other; the later filing wins."""
    by_end = {}
    for f in filings:
        if f["period"].lower().startswith(("annual", "half")):
            continue
        if f["start"] and not 75 <= (f["end"] - f["start"]).days <= 100:
            continue
        cur = by_end.get(f["end"])
        rank = (f["kind"] == kind, f["filed"] or _dt.date.min)
        if cur is None or rank > (cur["kind"] == kind, cur["filed"] or _dt.date.min):
            by_end[f["end"]] = f
    return [by_end[k] for k in sorted(by_end, reverse=True)][:n]


# ---------------------------------------------------------------- XBRL

def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def parse_xbrl(data):
    """XBRL instance -> {"contexts": {id: (start, end)}, "facts": {name: [(ctx, value)]}, "entity": str}."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ResultsError("the XBRL file is not valid XML: %s" % e)
    contexts, facts, entity, scenario = {}, {}, "", set()
    for el in root:
        name = _local(el.tag)
        if name == "context":
            start = end = None
            for c in el.iter():
                ln = _local(c.tag)
                if ln == "startDate":
                    start = parse_day((c.text or "").strip())
                elif ln in ("endDate", "instant"):
                    end = parse_day((c.text or "").strip())
                elif ln in ("explicitMember", "typedMember"):
                    scenario.add(el.get("id"))
            contexts[el.get("id")] = (start, end)
            continue
        ctx = el.get("contextRef")
        if not ctx:
            continue
        text = (el.text or "").strip()
        if name in ("NameOfTheCompany", "NameOfCompany", "EntityName") and text:
            entity = entity or text
        try:
            v = float(text.replace(",", ""))
        except ValueError:
            continue
        facts.setdefault(name, []).append((ctx, v))
    for cid in scenario:          # dimensional contexts (segments) are not the company total
        contexts.pop(cid, None)
    return {"contexts": contexts, "facts": facts, "entity": entity}


def quarter_values(x, end, start=None):
    """The concept values for the quarter ending `end` (a context of 75 to 100 days)."""
    good = set()
    for cid, (s, e) in x["contexts"].items():
        if e != end or s is None:
            continue
        days = (e - s).days
        if (start and s == start) or 75 <= days <= 100:
            good.add(cid)
    out = {}
    for key, names in CONCEPTS.items():
        for n in names:
            vals = [v for c, v in x["facts"].get(n, []) if c in good]
            if vals:
                out[key] = vals[0]
                break
        else:
            out[key] = None
    return out


def row_from(vals, end, filing=None):
    rev = vals.get("revenue")
    net = vals["net_profit_owners"] if vals.get("net_profit_owners") is not None else vals.get("net_profit_total")
    op = None
    if vals.get("pbt") is not None and vals.get("finance_costs") is not None:
        op = vals["pbt"] + vals["finance_costs"] - (vals.get("other_income") or 0.0)
    return {"end": end.isoformat(), "fiscal": fy_label(end), "kind": (filing or {}).get("kind", ""),
            "audited": (filing or {}).get("audited", ""),
            "filed": (filing or {}).get("filed").isoformat() if (filing or {}).get("filed") else None,
            "revenue": rev, "other_income": vals.get("other_income"), "operating_profit": op,
            "pbt": vals.get("pbt"), "net_profit": net, "eps_basic": vals.get("eps_basic"),
            "eps_diluted": vals.get("eps_diluted"), "operating_margin": margin(op, rev),
            "net_margin": margin(net, rev), "xbrl": (filing or {}).get("xbrl")}


def with_growth(rows):
    """Adds QoQ and YoY growth by matching quarter ends (about 3 and 12 months back)."""
    by = {r["end"]: r for r in rows}

    def back(end, months):
        d = _dt.date.fromisoformat(end)
        for r_end in by:
            e = _dt.date.fromisoformat(r_end)
            if abs((d - e).days - months * 30.44) <= 20:
                return by[r_end]
        return None
    for r in rows:
        p, y = back(r["end"], 3), back(r["end"], 12)
        for k in ("revenue", "operating_profit", "net_profit", "eps_basic"):
            r[k + "_qoq"] = pct(r[k], p[k]) if p else None
            r[k + "_yoy"] = pct(r[k], y[k]) if y else None
        r["operating_margin_prev"] = p["operating_margin"] if p else None
        r["net_margin_prev"] = p["net_margin"] if p else None
    return rows


def parse_yahoo_ts(data, symbol):
    """Yahoo fundamentals-timeseries JSON -> {quarter end date: {field: value}}."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except ValueError:
        raise ResultsError("Yahoo's quarterly figures for %s are not JSON" % symbol)
    res = ((doc.get("timeseries") or {}).get("result")) or []
    out = {}
    for item in res:
        typ = ((item.get("meta") or {}).get("type") or [None])[0]
        field = YAHOO_TYPES.get(typ)
        if not field:
            continue
        for pt in item.get(typ) or []:
            if not pt or pt.get("periodType") not in (None, "3M"):
                continue
            d = parse_day(pt.get("asOfDate"))
            raw = (pt.get("reportedValue") or {}).get("raw")
            if d and raw is not None:
                out.setdefault(d, {})[field] = float(raw)
    return out


def analyse_yahoo(fetcher, symbol, quarters=6, now=None):
    """Quarterly figures from Yahoo Finance (consolidated, as Yahoo reports them) for when NSE blocks the script.
    Yahoo usually has the last 5 to 8 quarters."""
    now = now or _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    p2 = int((now - _dt.datetime(1970, 1, 1)).total_seconds())
    p1 = p2 - 3 * 366 * 86400
    ysym = urllib.parse.quote(symbol.upper() + ".NS", safe=".-")
    url = YAHOO_TS % ("query2", ysym, ysym, ",".join(YAHOO_TYPES), p1, p2)
    try:
        data = fetcher.get(url, "yahoo-ts-%s.json" % symbol, accept="application/json")
    except ResultsError as e:
        if "HTTP" in str(e) and not fetcher.offline:
            data = fetcher.get(url.replace("://query2.", "://query1."), "", accept="application/json")
        else:
            raise
    by_end = parse_yahoo_ts(data, symbol)
    if not by_end:
        raise ResultsError("Yahoo has no quarterly figures for %s.NS" % symbol)
    rows = []
    for end in sorted(by_end, reverse=True):
        v = dict((k, None) for k in CONCEPTS)
        v.update(by_end[end])
        r = row_from(v, end, {"kind": "consolidated (Yahoo)", "audited": "", "filed": None,
                              "xbrl": "https://finance.yahoo.com/quote/%s.NS/financials" % symbol})
        if v.get("operating_profit") is not None:
            r["operating_profit"] = v["operating_profit"]
            r["operating_margin"] = margin(v["operating_profit"], r["revenue"])
        rows.append(r)
    with_growth(rows)
    return {"symbol": symbol, "entity": universe_name(symbol) or symbol, "rows": rows[:quarters],
            "kind": "consolidated (Yahoo Finance)",
            "bank": False, "ttm": ttm(rows), "source": "yahoo"}


def universe_name(symbol, path="trader/universe.txt"):
    """The company name from trader-scanner's universe file, if it is there."""
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                sym, _, name = ln.rstrip("\n").partition("|")
                if sym.strip().upper() == symbol.upper() and name.strip():
                    return name.strip()
    except OSError:
        pass
    return None


def blocked(e):
    return bool(re.search(r"HTTP (401|403|429)|not JSON|could not reach www\.nseindia|block page", str(e)))


def analyse(fetcher, symbol, quarters=6, kind="consolidated", errors=None, source="auto"):
    errors = [] if errors is None else errors
    if source == "yahoo":
        return analyse_yahoo(fetcher, symbol, quarters)
    try:
        return analyse_nse(fetcher, symbol, quarters, kind, errors)
    except ResultsError as e:
        if source != "auto" or not blocked(e):
            raise
        errors.append("NSE turned the script away (%s), so these are Yahoo Finance's quarterly figures "
                      "(consolidated, Yahoo's own line items; operating profit is Yahoo's, not "
                      "PBT + finance costs - other income)" % e)
        return analyse_yahoo(fetcher, symbol, quarters)


def analyse_nse(fetcher, symbol, quarters=6, kind="consolidated", errors=None):
    errors = [] if errors is None else errors
    filings = parse_list(fetcher.get(LIST_URL % urllib.parse.quote(symbol), "results-%s.json" % symbol,
                                     accept="application/json"), symbol)
    if not filings:
        raise ResultsError("NSE lists no quarterly result filings with XBRL for %s" % symbol)
    picked = pick_filings(filings, kind, quarters + 4)
    rows, entity = [], filings[0]["company"]
    for f in picked:
        name = f["xbrl"].rsplit("/", 1)[-1]
        try:
            x = parse_xbrl(fetcher.get(f["xbrl"], name, accept="application/xml"))
        except ResultsError as e:
            errors.append("%s %s: %s" % (fy_label(f["end"]), f["kind"], e))
            continue
        entity = x["entity"] or entity
        vals = quarter_values(x, f["end"], f["start"])
        if all(v is None for v in vals.values()):
            errors.append("%s: no quarter figures found in %s" % (fy_label(f["end"]), name))
            continue
        rows.append(row_from(vals, f["end"], f))
    with_growth(rows)
    kinds = {r["kind"] for r in rows[:quarters]}
    return {"symbol": symbol, "entity": entity, "rows": rows[:quarters], "kind": "/".join(sorted(kinds)) or kind,
            "bank": any(f["bank"] for f in picked), "ttm": ttm(rows), "source": "nse"}


def ttm(rows):
    last4 = rows[:4]
    if len(last4) < 4:
        return {}
    out = {}
    for k in ("revenue", "operating_profit", "net_profit", "eps_basic"):
        vals = [r[k] for r in last4]
        out[k] = round(sum(vals), 2) if all(v is not None for v in vals) else None
    return out


# ---------------------------------------------------------------- output

def cr(v):
    return "-" if v is None else "{:,.0f}".format(v / CRORE) if abs(v) >= 100 * CRORE else "%.1f" % (v / CRORE)


def _p(v):
    return "-" if v is None else "%+.1f%%" % v


def _pm(v):
    return "-" if v is None else "%.1f%%" % v


def changes(result):
    rows = result["rows"]
    if not rows:
        return []
    cur, out = rows[0], []
    line = "%s (quarter ended %s): revenue Rs %s cr" % (cur["fiscal"], cur["end"], cr(cur["revenue"]))
    if cur["revenue_yoy"] is not None:
        line += " (%s YoY" % _p(cur["revenue_yoy"])
        line += (", %s QoQ)" % _p(cur["revenue_qoq"])) if cur["revenue_qoq"] is not None else ")"
    line += ", net profit Rs %s cr" % cr(cur["net_profit"])
    if cur["net_profit_yoy"] is not None:
        line += " (%s YoY)" % _p(cur["net_profit_yoy"])
    if cur["eps_basic"] is not None:
        line += ", EPS Rs %.2f" % cur["eps_basic"]
        if cur["eps_basic_yoy"] is not None:
            line += " (%s YoY)" % _p(cur["eps_basic_yoy"])
    out.append(line + ".")
    for key, prev, name in (("operating_margin", "operating_margin_prev", "Operating margin"),
                            ("net_margin", "net_margin_prev", "Net margin")):
        if cur[key] is None:
            continue
        s = "%s %.1f%%" % (name, cur[key])
        if cur[prev] is not None:
            s += " (%+.1f points vs the quarter before)" % (cur[key] - cur[prev])
        out.append(s + ".")
    if cur["other_income"] and cur["pbt"] and cur["other_income"] > 0.25 * cur["pbt"]:
        out.append("Other income is %.0f%% of profit before tax: a big part of the profit is not from the "
                   "business itself (treasury gains, interest). Check the results notes." %
                   (100.0 * cur["other_income"] / cur["pbt"]))
    if cur["revenue_yoy"] is not None and cur["net_profit_yoy"] is not None \
            and cur["revenue_yoy"] < 0 < cur["net_profit_yoy"]:
        out.append("Profit grew while revenue fell: look for one-offs, tax credits or cost cuts in the notes.")
    if result.get("bank"):
        out.append("A bank or NBFC: revenue here is interest earned when filed, and operating profit may be blank.")
    return out


def render(result, errors):
    src = "Yahoo Finance quarterly financials" if result.get("source") == "yahoo" else "NSE XBRL filings"
    out = ["%s (NSE: %s), %s results. Rs crore except EPS (Rs). Source: %s." % (
        result["entity"], result["symbol"], result["kind"] or "quarterly", src), ""]
    out.append("%-8s %-10s %10s %8s %10s %7s %10s %8s %7s %8s %8s" % (
        "quarter", "ended", "revenue", "rev yoy", "op profit", "op mgn", "net profit", "net yoy", "net mgn",
        "EPS", "EPS yoy"))
    for r in result["rows"]:
        out.append("%-8s %-10s %10s %8s %10s %7s %10s %8s %7s %8s %8s" % (
            r["fiscal"], r["end"], cr(r["revenue"]), _p(r["revenue_yoy"]), cr(r["operating_profit"]),
            _pm(r["operating_margin"]), cr(r["net_profit"]), _p(r["net_profit_yoy"]), _pm(r["net_margin"]),
            "-" if r["eps_basic"] is None else "%.2f" % r["eps_basic"], _p(r["eps_basic_yoy"])))
    t = result["ttm"]
    if t:
        out.append("")
        out.append("Last 4 quarters: revenue Rs %s cr, net profit Rs %s cr, EPS Rs %s." % (
            cr(t.get("revenue")), cr(t.get("net_profit")),
            "%.2f" % t["eps_basic"] if t.get("eps_basic") is not None else "-"))
    out.append("")
    out.append("What changed:")
    for line in changes(result):
        out.append("  - " + line)
    if result["rows"] and result["rows"][0].get("filed"):
        r0 = result["rows"][0]
        out.append("")
        out.append("Latest filing: %s %s, filed %s  %s" % (r0["fiscal"], r0["kind"] + (" (" + r0["audited"] + ")"
                                                                                   if r0["audited"] else ""),
                                                           r0["filed"], r0["xbrl"]))
    for e in errors:
        out.append("note: " + e)
    out.append("Numbers as filed; they say nothing about whether the stock is a buy.")
    return "\n".join(out) + "\n"


def metrics_row(result):
    cur = result["rows"][0] if result["rows"] else {}
    t = result["ttm"]
    return {"symbol": result["symbol"], "name": result["entity"], "period_end": cur.get("end"),
            "fiscal": cur.get("fiscal"), "basis": cur.get("kind"),
            "revenue_ttm_cr": round(t["revenue"] / CRORE, 2) if t.get("revenue") is not None else None,
            "net_profit_ttm_cr": round(t["net_profit"] / CRORE, 2) if t.get("net_profit") is not None else None,
            "eps_ttm": t.get("eps_basic"), "revenue_growth_yoy": cur.get("revenue_yoy"),
            "net_profit_growth_yoy": cur.get("net_profit_yoy"), "eps_growth_yoy": cur.get("eps_basic_yoy"),
            "operating_margin": cur.get("operating_margin"), "net_margin": cur.get("net_margin"),
            "source": "Yahoo Finance" if result.get("source") == "yahoo" else "NSE XBRL results filings"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Quarterly results from NSE filings (trader-analyst).")
    ap.add_argument("symbols", nargs="*", help="NSE symbols, e.g. RELIANCE TCS")
    ap.add_argument("--quarters", type=int, default=6)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--standalone", action="store_true", help="the parent company alone")
    g.add_argument("--consolidated", action="store_true", help="the group (the default)")
    ap.add_argument("--xbrl", metavar="FILE", help="read one saved XBRL results file instead")
    ap.add_argument("--end", help="with --xbrl: the quarter end YYYY-MM-DD (default: the latest in the file)")
    ap.add_argument("--source", choices=["auto", "nse", "yahoo"], default="auto",
                    help="auto (default): NSE filings, Yahoo Finance if NSE turns the script away")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--metrics", metavar="FILE", help="merge one row per symbol into this JSON file")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.xbrl:
            with open(a.xbrl, "rb") as fh:
                x = parse_xbrl(fh.read())
            ends = sorted({e for s, e in x["contexts"].values() if s and e and 75 <= (e - s).days <= 100})
            if not ends:
                raise ResultsError("no quarter (about 3 months) context in %s" % a.xbrl)
            end = _dt.date.fromisoformat(a.end) if a.end else ends[-1]
            row = row_from(quarter_values(x, end), end)
            res = {"symbol": os.path.basename(a.xbrl), "entity": x["entity"] or "?", "rows": with_growth([row]),
                   "kind": "", "bank": False, "ttm": {}}
            print(json.dumps(res, indent=2, default=str) if a.json else render(res, []))
            return 0
        if not a.symbols:
            raise ResultsError("which company? results.py RELIANCE (an NSE symbol)")
        fetcher = Fetcher(offline=a.offline)
        kind = "standalone" if a.standalone else "consolidated"
        results, code = [], 0
        for sym in a.symbols:
            sym = sym.upper().replace(".NS", "")
            errors = []
            try:
                res = analyse(fetcher, sym, a.quarters, kind, errors, a.source)
            except ResultsError as e:
                print("results.py: %s: %s" % (sym, e), file=sys.stderr)
                if blocked(e) and a.source == "nse":
                    print("NSE turned the script away: open nseindia.com > Corporate filings > Financial results "
                          "in a browser, save the list and XBRL files, then use --offline DIR.", file=sys.stderr)
                code = 1
                continue
            results.append((res, errors))
            if not a.json:
                sys.stdout.write(render(res, errors))
                if sym != a.symbols[-1]:
                    print()
        if a.json:
            print(json.dumps([dict(r, notes=e) for r, e in results], indent=2, default=str))
        if a.metrics and results:
            doc = {}
            if os.path.isfile(a.metrics):
                with open(a.metrics, encoding="utf-8") as fh:
                    doc = json.load(fh)
            doc.setdefault("rows", {})
            for r, _ in results:
                doc["rows"][r["symbol"]] = metrics_row(r)
            doc["updated"] = _dt.date.today().isoformat()
            d = os.path.dirname(a.metrics)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(a.metrics, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2)
                fh.write("\n")
        return code if results else 1
    except ResultsError as e:
        print("results.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
