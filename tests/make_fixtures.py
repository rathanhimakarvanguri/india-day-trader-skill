#!/usr/bin/env python3
"""Builds the offline test fixtures in tests/fixtures/. Run it once; the files are committed.

Every fixture is SYNTHETIC: made-up companies (DEMOCO, DEMOSTEEL, DEMO01...) and made-up
people, shaped like the real NSE and Yahoo answers the tools read. Nothing here is real
market data, a real filing or a real person's trade.

    python3 tests/make_fixtures.py
"""

import datetime as dt
import gzip
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
IST = dt.timedelta(hours=5, minutes=30)
DAY = dt.date(2026, 11, 13)          # a Friday, an NSE trading day
OPEN = dt.time(9, 15)
BARS = 75                             # 9:15 to 15:30 in 5-minute bars
HOLIDAYS = {"2026-10-02", "2026-10-20", "2026-11-10", "2026-09-14"}


def ts(day, minutes_after_open):
    local = dt.datetime.combine(day, OPEN) + dt.timedelta(minutes=minutes_after_open)
    return int(((local - IST) - dt.datetime(1970, 1, 1)).total_seconds())


def chart(symbol, stamps, o, h, l, c, v, prev_close, interval="5m", rng="60d"):
    return {"chart": {"result": [{
        "meta": {"currency": "INR", "symbol": symbol + ".NS", "exchangeName": "NSI",
                 "regularMarketPrice": c[-1], "regularMarketTime": stamps[-1] + 300,
                 "previousClose": prev_close, "chartPreviousClose": prev_close,
                 "dataGranularity": interval, "range": rng, "exchangeTimezoneName": "Asia/Kolkata"},
        "timestamp": stamps,
        "indicators": {"quote": [{"open": o, "high": h, "low": l, "close": c, "volume": v}]}}],
        "error": None}}


def trading_days(end, n):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5 and d.isoformat() not in HOLIDAYS:
            out.append(d)
        d -= dt.timedelta(days=1)
    return sorted(out)


def r2(x):
    return round(x + 1e-9, 2)


def democo_day():
    """DEMOCO on Fri 2026-11-13: range 9:15-9:25 high 1508.90 low 1494.10; the 9:55 bar closes 1512.40."""
    o = [1500.00, 1503.50, 1499.20, 1504.00, 1505.10, 1503.80, 1506.20, 1507.00, 1508.10]
    h = [1505.00, 1508.90, 1503.00, 1507.50, 1507.90, 1506.60, 1508.50, 1508.80, 1513.00]
    l = [1494.10, 1498.40, 1496.30, 1501.20, 1502.40, 1502.00, 1504.90, 1505.60, 1507.20]
    c = [1503.40, 1499.10, 1502.70, 1505.00, 1503.90, 1506.10, 1506.90, 1508.20, 1512.40]
    v = [180000, 95000, 70000, 64000, 52000, 48000, 51000, 47000, 88000]
    # the rest of the morning, on the grid
    rnd = random.Random(7)
    p = c[-1]
    for _ in range(9, 30):
        nxt = r2(p + rnd.uniform(-2.2, 2.6))
        o.append(r2(p))
        h.append(r2(max(p, nxt) + rnd.uniform(0.2, 1.4)))
        l.append(r2(min(p, nxt) - rnd.uniform(0.2, 1.4)))
        c.append(nxt)
        v.append(rnd.randint(30000, 70000))
        p = nxt
    return o, h, l, c, v


def history(symbol, end_day, sessions, start_price, seed):
    rnd = random.Random(seed)
    days = trading_days(end_day, sessions)
    stamps, o, h, l, c, v = [], [], [], [], [], []
    p = start_price
    for d in days:
        if d == DAY and symbol == "DEMOCO":
            do, dh, dl, dc, dv = democo_day()
            for k in range(len(dc)):
                stamps.append(ts(d, 5 * k))
            o += do
            h += dh
            l += dl
            c += dc
            v += dv
            continue
        drift = rnd.uniform(-0.004, 0.004)
        for k in range(BARS):
            step = p * (drift / BARS + rnd.gauss(0, 0.0016))
            nxt = r2(p + step)
            stamps.append(ts(d, 5 * k))
            o.append(r2(p))
            h.append(r2(max(p, nxt) * (1 + abs(rnd.gauss(0, 0.0008)))))
            l.append(r2(min(p, nxt) * (1 - abs(rnd.gauss(0, 0.0008)))))
            c.append(nxt)
            v.append(rnd.randint(20000, 120000) * (3 if k == 0 else 1))
            p = nxt
    prev = c[-BARS - 1] if len(c) > BARS else start_price
    return chart(symbol, stamps, o, h, l, c, v, prev)


def daily_spark(symbols, end_day, seed):
    """A Yahoo spark answer: 3 months of daily closes for each symbol."""
    rnd = random.Random(seed)
    days = trading_days(end_day, 62)
    result = []
    shapes = {}
    for i, s in enumerate(symbols):
        p = rnd.uniform(120, 3000)
        closes = []
        shape = ["breakout", "flag", "oversold", "flat"][i % 4]
        shapes[s] = shape
        for k, _ in enumerate(days):
            if shape == "breakout":
                p *= 1 + (0.012 if k == len(days) - 1 else rnd.uniform(-0.006, 0.005))
            elif shape == "flag":
                if len(days) - 16 <= k < len(days) - 5:
                    p *= 1.012
                elif k >= len(days) - 5:
                    p *= 1 + rnd.uniform(-0.004, 0.004)
                else:
                    p *= 1 + rnd.uniform(-0.004, 0.004)
            elif shape == "oversold":
                p *= 1 - (0.02 if k > len(days) - 15 else rnd.uniform(-0.004, 0.004))
            else:
                p *= 1 + rnd.uniform(-0.003, 0.003)
            closes.append(r2(p))
        stamps = [int(((dt.datetime.combine(d, dt.time(9, 15)) - IST) - dt.datetime(1970, 1, 1)).total_seconds())
                  for d in days]
        result.append({"symbol": s + ".NS", "response": [{
            "meta": {"symbol": s + ".NS", "currency": "INR", "regularMarketPrice": closes[-1],
                     "regularMarketVolume": 2500000 if i % 5 else 100000, "dataGranularity": "1d"},
            "timestamp": stamps, "indicators": {"quote": [{"close": closes}]}}]})
    return {"spark": {"result": result, "error": None}}, shapes


def orb_wall(symbols, seed):
    """Today's 5-minute bars to 10:00 for a handful of symbols; the even ones break out at the 9:45 bar."""
    rnd = random.Random(seed)
    out = {}
    for i, s in enumerate(symbols):
        p = rnd.uniform(200, 2500)
        stamps, o, h, l, c, v = [], [], [], [], [], []
        for k in range(9):          # 9:15 ... 9:55
            if k < 3:
                nxt = r2(p * (1 + rnd.uniform(-0.002, 0.002)))
            elif i % 2 == 0 and k == 6:
                nxt = r2(max(h[:3]) * 1.006)
            else:
                nxt = r2(min(p, max(h[:3]) * 0.998) if k >= 3 else p)
            stamps.append(ts(DAY, 5 * k))
            o.append(r2(p))
            h.append(r2(max(p, nxt) * 1.001))
            l.append(r2(min(p, nxt) * 0.999))
            c.append(nxt)
            v.append(rnd.randint(40000, 90000))
            p = nxt
        out[s] = chart(s, stamps, o, h, l, c, v, r2(p * 0.99), rng="1d")
    return out


def xbrl(company, start, end, revenue, other_income, finance, depn, pbt, net, owners, eps):
    """An NSE-style results XBRL instance (in-capmkt names) with a quarter and a year-to-date context."""
    ytd_start = dt.date(end.year if end.month >= 4 else end.year - 1, 4, 1)

    def fact(name, ctx, v, unit="INR"):
        return '  <in-capmkt:%s contextRef="%s" unitRef="%s" decimals="-5">%s</in-capmkt:%s>' % (
            name, ctx, unit, v, name)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
             'xmlns:in-capmkt="http://www.sebi.gov.in/xbrl/2023-10-31/in-capmkt" '
             'xmlns:xbrldi="http://xbrl.org/2006/xbrldi">']
    for cid, s, e in (("OneD", start, end), ("FourD", ytd_start, end)):
        lines.append('  <xbrli:context id="%s"><xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">'
                     'DEMOCO</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>%s</xbrli:startDate>'
                     '<xbrli:endDate>%s</xbrli:endDate></xbrli:period></xbrli:context>' % (cid, s, e))
    lines.append('  <xbrli:context id="OneI"><xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">'
                 'DEMOCO</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>%s</xbrli:instant>'
                 '</xbrli:period></xbrli:context>' % end)
    lines.append('  <xbrli:context id="Seg1"><xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">'
                 'DEMOCO</xbrli:identifier><xbrli:segment><xbrldi:explicitMember dimension="in-capmkt:SegmentsAxis">'
                 'in-capmkt:RetailMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period>'
                 '<xbrli:startDate>%s</xbrli:startDate><xbrli:endDate>%s</xbrli:endDate></xbrli:period>'
                 '</xbrli:context>' % (start, end))
    lines.append('  <in-capmkt:NameOfTheCompany contextRef="OneD">%s</in-capmkt:NameOfTheCompany>' % company)
    lines.append(fact("RevenueFromOperations", "Seg1", int(revenue * 0.4)))   # a segment: must be ignored
    for ctx, k in (("OneD", 1), ("FourD", 2.4)):
        lines += [fact("RevenueFromOperations", ctx, int(revenue * k)),
                  fact("OtherIncome", ctx, int(other_income * k)),
                  fact("Income", ctx, int((revenue + other_income) * k)),
                  fact("FinanceCosts", ctx, int(finance * k)),
                  fact("DepreciationDepletionAndAmortisationExpense", ctx, int(depn * k)),
                  fact("ProfitBeforeTax", ctx, int(pbt * k)),
                  fact("ProfitLossForPeriod", ctx, int(net * k)),
                  fact("ProfitOrLossAttributableToOwnersOfParent", ctx, int(owners * k)),
                  fact("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", ctx, round(eps * k, 2),
                       "INRPerShare"),
                  fact("DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations", ctx,
                       round(eps * k * 0.99, 2), "INRPerShare")]
    lines.append("</xbrli:xbrl>")
    return "\n".join(lines) + "\n"


def write(rel, data, gz=False):
    path = os.path.join(FIX, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(data, (dict, list)):
        data = json.dumps(data, separators=(",", ":"))
    if gz:
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(data)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(data)


def main():
    # scanner: an NSE list, a daily spark and an orb wall
    write("trader-scanner/EQUITY_L.csv",
          "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
          "DEMOCO,Demo Company Limited,EQ,01-JAN-2001,10,1,INE000A01001,10\n"
          "DEMOSTEEL,Demo Steel Limited,EQ,01-JAN-2002,1,1,INE000A01002,1\n"
          "M&M-DEMO,Demo Motors & Machines Limited,EQ,01-JAN-2003,5,1,INE000A01003,5\n"
          "DEMOT2T,Demo Trade For Trade Limited,BE,01-JAN-2004,10,1,INE000A01004,10\n"
          "DEMOSME,Demo SME Limited,SM,01-JAN-2005,10,1,INE000A01005,10\n"
          "BAD SYMBOL,Broken Row Limited,EQ,01-JAN-2006,10,1,INE000A01006,10\n")
    write("trader-scanner/ind_nifty500list.csv",
          "Company Name,Industry,Symbol,Series,ISIN Code\n"
          "Demo Company Ltd.,Oil Gas & Consumable Fuels,DEMOCO,EQ,INE000A01001\n"
          "Demo Steel Ltd.,Metals & Mining,DEMOSTEEL,EQ,INE000A01002\n")
    names = ["DEMO%02d" % i for i in range(1, 13)]
    spark, shapes = daily_spark(names, dt.date(2026, 11, 12), 11)
    write("trader-scanner/daily-spark-2026-11-12.json", spark)
    write("trader-scanner/shapes.json", shapes)
    write("trader-scanner/wall5m-2026-11-13.json", orb_wall(names[:8], 5))

    # entry, exit, time machine, alerts: DEMOCO
    write("trader-timemachine/DEMOCO-60d5m.json.gz", history("DEMOCO", DAY, 45, 1490.0, 3), gz=True)
    full = history("DEMOCO", DAY, 45, 1490.0, 3)
    day_only = json.loads(json.dumps(full))
    res = day_only["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    start = ts(DAY, 0)
    keep = [i for i, t in enumerate(res["timestamp"]) if t >= start]
    res["timestamp"] = [res["timestamp"][i] for i in keep]
    for k in q:
        q[k] = [q[k][i] for i in keep]
    res["meta"]["range"] = "1d"
    write("trader-entry/DEMOCO-2026-11-13-5m.json", day_only)

    alerts = {"chart": {"result": [{"meta": {"symbol": "DEMOCO.NS", "currency": "INR", "regularMarketPrice": 1500.9,
                                              "regularMarketTime": ts(DAY, 330), "previousClose": 1497.0,
                                              "regularMarketDayHigh": 1518.0, "regularMarketDayLow": 1494.1},
                                     "timestamp": [ts(DAY, 0)],
                                     "indicators": {"quote": [{"open": [1500.0], "close": [1500.9]}]}}]}}
    write("trader-alerts/yahoo-DEMOCO.json", alerts)

    # news
    write("trader-news/gnews-DEMOCO.xml", """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>"Demo Company" NSE - Google News</title>
<item><title>Demo Company Q2 results: net profit rises 12% YoY to Rs 1,240 crore - Demo Business Daily</title>
<link>https://news.example.com/demo-company-q2</link><guid>gn-1</guid>
<pubDate>Fri, 13 Nov 2026 02:40:00 GMT</pubDate><source url="https://news.example.com">Demo Business Daily</source></item>
<item><title>Brokerage upgrades Demo Company to buy, raises target price - Demo Markets</title>
<link>https://news.example.com/demo-upgrade</link><guid>gn-2</guid>
<pubDate>Fri, 13 Nov 2026 04:10:00 GMT</pubDate><source url="https://markets.example.com">Demo Markets</source></item>
<item><title>RBI keeps repo rate unchanged; Nifty steady - Demo Wire</title>
<link>https://news.example.com/rbi</link><guid>gn-3</guid>
<pubDate>Wed, 04 Nov 2026 05:00:00 GMT</pubDate><source url="https://wire.example.com">Demo Wire</source></item>
</channel></rss>
""")
    write("trader-news/yahoo-DEMOCO.xml", """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Yahoo! Finance: DEMOCO.NS News</title>
<item><title>Demo Company Q2 results: net profit rises 12% YoY to Rs 1,240 crore</title>
<link>https://news.example.com/demo-company-q2</link><guid>y-1</guid>
<pubDate>Fri, 13 Nov 2026 02:41:00 +0000</pubDate><description>Demo Company Limited (NSE: DEMOCO) reported...</description></item>
</channel></rss>
""")
    write("trader-news/nse-DEMOCO.json", [
        {"symbol": "DEMOCO", "desc": "Financial Result Updates", "sm_name": "Demo Company Limited",
         "attchmntText": "Demo Company Limited has informed the Exchange about the Financial Results for the "
                         "quarter ended September 30, 2026", "attchmntFile": "https://nsearchives.nseindia.com/"
         "corporate/DEMOCO_13112026_results.pdf", "an_dt": "12-Nov-2026 18:32:10",
         "sort_date": "2026-11-12 18:32:10", "seq_id": "9001"},
        {"symbol": "DEMOCO", "desc": "Trading Window-XBRL", "sm_name": "Demo Company Limited",
         "attchmntText": "Closure of trading window", "attchmntFile": "DEMOCO_tw.pdf",
         "an_dt": "10-Nov-2026 11:00:00", "sort_date": "2026-11-10 11:00:00", "seq_id": "9000"}])
    write("trader-news/chart-DEMOCO.json", alerts)
    # the BSE fallback, for when NSE turns the script away
    write("trader-news/bse-scrips.json", [
        {"SCRIP_CD": "590001", "scrip_id": "DEMOCO", "Scrip_Name": "Demo Company Ltd", "ISIN_NUMBER": "INE000A01001"},
        {"SCRIP_CD": "590002", "scrip_id": "DEMOTWO", "Scrip_Name": "Demo Two Ltd", "ISIN_NUMBER": "INE000A01007"}])
    write("trader-news/bse-DEMOCO.json", {"Table": [
        {"NEWSID": "b-1", "SCRIP_CD": 590001, "NEWSSUB": "Demo Company Ltd - 590001 - Board Meeting Outcome for "
         "Financial Results For The Quarter Ended September 30, 2026", "HEADLINE": "Outcome of the board meeting "
         "held on November 12, 2026", "CATEGORYNAME": "Result", "SUBCATNAME": "Financial Results",
         "NEWS_DT": "2026-11-12T18:31:05.12", "ATTACHMENTNAME": "demo-b1.pdf", "SLONGNAME": "Demo Company Ltd"},
        {"NEWSID": "b-2", "SCRIP_CD": 590001, "NEWSSUB": "Demo Company Ltd - 590001 - Closure of Trading Window",
         "HEADLINE": "", "CATEGORYNAME": "Company Update", "SUBCATNAME": "",
         "NEWS_DT": "2026-11-10T11:00:00", "ATTACHMENTNAME": "", "SLONGNAME": "Demo Company Ltd"}]})

    # insider: PIT disclosures and deals (fictional people and funds)
    write("trader-insider/pit-DEMOCO.json", {"data": [
        {"symbol": "DEMOCO", "company": "Demo Company Limited", "acqName": "Demo Promoter Holdings Private Limited",
         "personCategory": "Promoter Group", "secType": "Equity Shares", "secAcq": "50000", "secVal": "75620000",
         "tdpTransactionType": "Buy", "acqMode": "Market Purchase", "acqfromDt": "10-Nov-2026",
         "acqtoDt": "11-Nov-2026", "intimDt": "12-Nov-2026", "date": "13-Nov-2026 18:01",
         "befAcqSharesPer": "41.20", "afterAcqSharesPer": "41.21"},
        {"symbol": "DEMOCO", "company": "Demo Company Limited", "acqName": "A Demo Director", "personCategory": "Director",
         "secType": "Equity Shares", "secAcq": "2000", "secVal": "3010000", "tdpTransactionType": "Sell",
         "acqMode": "Market Sale", "acqfromDt": "05-Nov-2026", "acqtoDt": "05-Nov-2026", "intimDt": "06-Nov-2026",
         "date": "07-Nov-2026 12:00"},
        {"symbol": "DEMOCO", "company": "Demo Company Limited", "acqName": "A Demo Employee",
         "personCategory": "Designated Person", "secType": "Equity Shares", "secAcq": "1500", "secVal": "0",
         "tdpTransactionType": "Buy", "acqMode": "ESOP", "acqfromDt": "01-Nov-2026", "acqtoDt": "01-Nov-2026",
         "date": "03-Nov-2026 10:00"},
        {"symbol": "DEMOCO", "company": "Demo Company Limited", "acqName": "Demo Promoter Holdings Private Limited",
         "personCategory": "Promoter Group", "secType": "Equity Shares", "secAcq": "300000", "secVal": "0",
         "tdpTransactionType": "Pledge Creation", "acqMode": "Pledge Creation", "acqfromDt": "20-Sep-2026",
         "acqtoDt": "20-Sep-2026", "date": "22-Sep-2026 17:00"}]})
    write("trader-insider/bulk.csv",
          "Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
          "13-NOV-2026,DEMOSTEEL,Demo Steel Limited,DEMO MUTUAL FUND A/C DEMO FLEXI CAP,BUY,\"1,25,00,000\",168.42,-\n"
          "13-NOV-2026,DEMOCO,Demo Company Limited,DEMO CAPITAL LLP,SELL,4500000,1512.10,-\n"
          "13-NOV-2026,DEMOSTEEL,Demo Steel Limited,DEMO QUANT DESK LLP,BUY,\"60,00,000\",168.40,-\n"
          "13-NOV-2026,DEMOSTEEL,Demo Steel Limited,DEMO QUANT DESK LLP,SELL,\"58,50,000\",168.46,-\n")
    write("trader-insider/block.csv",
          "Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price\n"
          "13-NOV-2026,DEMO01,Demo One Limited,DEMO GLOBAL FUND PTE,BUY,2000000,1601.50\n"
          "13-NOV-2026,DEMOCO,Demo Company Limited,DEMO CAPITAL LLP,SELL,4500000,1512.10\n")

    # analyst: 8 quarters of DEMOCO results
    quarters = [dt.date(2024, 12, 31), dt.date(2025, 3, 31), dt.date(2025, 6, 30), dt.date(2025, 9, 30),
                dt.date(2025, 12, 31), dt.date(2026, 3, 31), dt.date(2026, 6, 30), dt.date(2026, 9, 30)]
    listing = []
    rev0 = 2.0e11            # Rs 20,000 crore a quarter
    for k, end in enumerate(quarters):
        m = end.month - 2
        start = dt.date(end.year if m > 0 else end.year - 1, m if m > 0 else m + 12, 1)
        rev = rev0 * (1.03 ** k)
        other = 9.0e9
        fin = 6.0e9
        dep = 8.0e9
        pbt = rev * 0.11 + other - fin
        net = pbt * 0.75
        owners = net * 0.96
        eps = owners / 1.0e9            # 100 crore shares
        name = "DEMOCO_%s_cons.xml" % end.strftime("%d%m%Y")
        write("trader-analyst/" + name, xbrl("Demo Company Limited", start, end, rev, other, fin, dep, pbt, net,
                                             owners, eps))
        listing.append({"symbol": "DEMOCO", "companyName": "Demo Company Limited", "audited": "Un-Audited",
                        "cumulative": "Non-cumulative", "consolidated": "Consolidated", "period": "Quarterly",
                        "fromDate": start.strftime("%d-%b-%Y"), "toDate": end.strftime("%d-%b-%Y"),
                        "filingDate": (end + dt.timedelta(days=40)).strftime("%d-%b-%Y %H:%M"),
                        "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/" + name, "bank": "-"})
        listing.append(dict(listing[-1], consolidated="Non-Consolidated",
                            xbrl="https://nsearchives.nseindia.com/corporate/xbrl/missing_standalone.xml"))
    write("trader-analyst/results-DEMOCO.json", listing)
    # the Yahoo fallback: fundamentals-timeseries for a made-up DEMOTWO.NS, 5 quarters
    ends = ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]
    series = {"quarterlyTotalRevenue": [6.0e10, 6.2e10, 6.1e10, 6.5e10, 6.9e10],
              "quarterlyOperatingIncome": [9.0e9, 9.6e9, 9.1e9, 1.0e10, 1.1e10],
              "quarterlyPretaxIncome": [9.5e9, 1.0e10, 9.6e9, 1.05e10, 1.16e10],
              "quarterlyNetIncomeCommonStockholders": [7.0e9, 7.4e9, 7.1e9, 7.8e9, 8.6e9],
              "quarterlyNetIncome": [7.1e9, 7.5e9, 7.2e9, 7.9e9, 8.7e9],
              "quarterlyBasicEPS": [14.0, 14.8, 14.2, 15.6, 17.2], "quarterlyDilutedEPS": [13.9, 14.7, 14.1, 15.5, 17.1]}
    result = []
    for typ, vals in series.items():
        pts = [{"dataId": 1, "asOfDate": d, "periodType": "3M", "currencyCode": "INR",
                "reportedValue": {"raw": v, "fmt": str(v)}} for d, v in zip(ends, vals)]
        result.append({"meta": {"symbol": ["DEMOTWO.NS"], "type": [typ]}, "timestamp": [0] * len(ends), typ: pts})
    result.append({"meta": {"symbol": ["DEMOTWO.NS"], "type": ["quarterlyInterestExpense"]}, "timestamp": []})
    write("trader-analyst/yahoo-ts-DEMOTWO.json", {"timeseries": {"result": result, "error": None}})
    print("wrote fixtures to", FIX)


if __name__ == "__main__":
    main()
