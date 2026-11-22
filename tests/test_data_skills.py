"""The data skills on synthetic NSE-shaped fixtures: scanner, news, insider, analyst."""

import datetime
import json
import os
import unittest

from _load import FIX, load

scan = load("trader-scanner", "scan")
news = load("trader-news", "news")
insider = load("trader-insider", "insider")
results = load("trader-analyst", "results")


def read(*parts):
    with open(os.path.join(FIX, *parts), "rb") as fh:
        return fh.read()


class Scanner(unittest.TestCase):
    def test_universe_keeps_eq_series_only(self):
        kept, counts = scan.build_universe(read("trader-scanner", "EQUITY_L.csv").decode())
        self.assertEqual([s for s, _ in kept], ["DEMOCO", "DEMOSTEEL", "M&M-DEMO"])
        self.assertEqual(counts["series BE (no intraday)"], 1)
        self.assertEqual(counts["series SM (no intraday)"], 1)
        self.assertEqual(counts["not a plain NSE symbol"], 1)

    def test_universe_reads_an_index_list(self):
        kept, _ = scan.build_universe(read("trader-scanner", "ind_nifty500list.csv").decode())
        self.assertEqual(kept, [("DEMOCO", "Demo Company Ltd."), ("DEMOSTEEL", "Demo Steel Ltd.")])

    def test_daily_setups(self):
        data, _ = scan.load_offline(os.path.join(FIX, "trader-scanner", "daily-spark-2026-11-12.json"))
        shapes = json.loads(read("trader-scanner", "shapes.json"))
        hits, counts, last = scan.scan_daily(data, sorted(data), scan.parse_now("2026-11-13 08:30"), 50, 500000)
        self.assertEqual(last, datetime.date(2026, 11, 12))
        self.assertEqual(counts["fetched"], 12)
        by = {h["symbol"]: h["setups"] for h in hits}
        for sym, shape in shapes.items():
            if sym not in by:
                continue
            if shape == "oversold":
                self.assertIn("oversold", by[sym], sym)
            if shape == "flat":
                self.fail("a flat chart matched %s" % by[sym])

    def test_orb_at_ten(self):
        data, _ = scan.load_offline(os.path.join(FIX, "trader-scanner", "wall5m-2026-11-13.json"))
        day, cutoff = scan.orb_window(scan.parse_now("2026-11-13 10:00"), None, 15, datetime.time(14, 45))
        hits, counts, _ = scan.scan_orb(data, sorted(data), day, cutoff, 15)
        self.assertEqual(counts["scanned"], 8)
        self.assertEqual(sorted(h["symbol"] for h in hits), ["DEMO01", "DEMO03", "DEMO05", "DEMO07"])
        self.assertTrue(all(h["at"] == "9:50 AM" for h in hits))

    def test_orb_refuses_before_the_first_bar_and_on_holidays(self):
        with self.assertRaises(scan.ScanError) as e:
            scan.orb_window(scan.parse_now("2026-11-13 09:32"), None, 15, None)
        self.assertIn("9:15", str(e.exception))
        with self.assertRaises(scan.ScanError) as e:
            scan.orb_window(scan.parse_now("2026-11-10 10:00"), None, 15, None)
        self.assertIn("Diwali", str(e.exception))


class News(unittest.TestCase):
    def test_google_news_titles_lose_the_source_suffix(self):
        items = news.parse_rss(read("trader-news", "gnews-DEMOCO.xml"), "DEMOCO", "Google News")
        self.assertEqual(items[0]["title"], "Demo Company Q2 results: net profit rises 12% YoY to Rs 1,240 crore")
        self.assertEqual(items[0]["source"], "GNews/Demo Business Daily")

    def test_nse_announcements(self):
        items = news.parse_nse(read("trader-news", "nse-DEMOCO.json"), "DEMOCO")
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0]["important"])                # financial results
        self.assertFalse(items[1]["important"])               # trading window closure
        self.assertEqual(items[0]["time"], datetime.datetime(2026, 11, 12, 13, 2, 10, tzinfo=datetime.timezone.utc))
        self.assertTrue(items[1]["link"].startswith("https://nsearchives.nseindia.com/corporate/"))

    def test_tags_and_dedupe(self):
        f = news.Fetcher(offline=os.path.join(FIX, "trader-news"))
        watch = {"DEMOCO": "Demo Company Limited"}
        items = news.dedupe(news.tag(news.collect(f, watch, {}), watch))
        titles = [i["title"] for i in items]
        self.assertEqual(sum("net profit rises" in t for t in titles), 1)   # Google and Yahoo carry the same story
        tags = {i["title"]: i["tags"] for i in items}
        self.assertIn("analyst", tags["Brokerage upgrades Demo Company to buy, raises target price"])
        self.assertIn("macro", tags["RBI keeps repo rate unchanged; Nifty steady"])
        self.assertIn("earnings", tags["Demo Company Limited: Financial Result Updates"])

    def test_gnews_query_uses_the_company_name(self):
        self.assertIn("%22Demo+Company%22", news.gnews_query("DEMOCO", "Demo Company Limited"))
        self.assertIn("%22DEMOCO%22", news.gnews_query("DEMOCO"))


class Insider(unittest.TestCase):
    def test_pit_rows(self):
        rows = insider.parse_pit(read("trader-insider", "pit-DEMOCO.json"), "DEMOCO")
        buy = rows[0]
        self.assertEqual((buy["side"], buy["shares"], buy["avg_price"], buy["days_to_disclose"]), ("buy", 50000, 1512.4, 2))
        self.assertTrue(buy["promoter"] and buy["market_trade"] and not buy["not_a_bet"])
        self.assertEqual(rows[2]["mode"], "ESOP")
        self.assertTrue(rows[2]["not_a_bet"])
        self.assertEqual(rows[3]["side"], "pledge")
        self.assertIn("promoter buying in the market", insider.describe_pit(buy))

    def test_filters(self):
        rows = insider.parse_pit(read("trader-insider", "pit-DEMOCO.json"), "DEMOCO")
        since = datetime.date(2026, 10, 15)
        self.assertEqual(len(insider.select_pit(rows, since)), 3)
        self.assertEqual(len(insider.select_pit(rows, since, buys=True, market_only=True)), 1)
        self.assertEqual(len(insider.select_pit(rows, None, promoters=True)), 2)

    def test_deals(self):
        bulk = insider.parse_deals(read("trader-insider", "bulk.csv"), "bulk")
        self.assertEqual(bulk[0]["shares"], 12500000)                   # "1,25,00,000"
        self.assertEqual(insider.crore(bulk[0]["value_inr"]), "Rs 210.53 cr")
        self.assertEqual(insider.crore(3010000), "Rs 30.1 lakh")
        block = insider.parse_deals(read("trader-insider", "block.csv"), "block")
        self.assertEqual((block[0]["symbol"], block[0]["side"]), ("DEMO01", "buy"))


class Analyst(unittest.TestCase):
    def test_quarters_growth_and_segments_ignored(self):
        f = results.Fetcher(offline=os.path.join(FIX, "trader-analyst"))
        res = results.analyse(f, "DEMOCO", 6)
        cur = res["rows"][0]
        self.assertEqual((cur["end"], cur["fiscal"], cur["kind"]), ("2026-09-30", "Q2 FY27", "consolidated"))
        self.assertAlmostEqual(cur["revenue"] / 1e7, 24597.4, 0)        # not the segment figure, not year to date
        self.assertEqual(cur["revenue_yoy"], 12.6)
        self.assertEqual(cur["revenue_qoq"], 3.0)
        self.assertEqual(cur["operating_margin"], 11.0)
        self.assertEqual(len(res["rows"]), 6)
        self.assertEqual(len(res["ttm"]), 4)

    def test_indian_fiscal_labels(self):
        self.assertEqual(results.fy_label(datetime.date(2026, 6, 30)), "Q1 FY27")
        self.assertEqual(results.fy_label(datetime.date(2026, 12, 31)), "Q3 FY27")
        self.assertEqual(results.fy_label(datetime.date(2027, 3, 31)), "Q4 FY27")


if __name__ == "__main__":
    unittest.main()


class Fixes(unittest.TestCase):
    """The fixes after the first live run on NSE (2026-11-22)."""

    def test_orb_filters_cut_the_noise(self):
        data, _ = scan.load_offline(os.path.join(FIX, "trader-scanner", "wall5m-2026-11-13.json"))
        day, cutoff = scan.orb_window(scan.parse_now("2026-11-13 10:00"), None, 15, datetime.time(14, 45))
        loose, _, _ = scan.scan_orb(data, sorted(data), day, cutoff, 15)
        strict, _, _ = scan.scan_orb(data, sorted(data), day, cutoff, 15, min_break_pct=0.25, min_volume_x=0)
        none, _, _ = scan.scan_orb(data, sorted(data), day, cutoff, 15, min_break_pct=5.0)
        self.assertEqual(len(strict), len(loose))            # these fixture breaks are 0.6 %: they pass 0.25
        self.assertTrue(all(h["pct_over"] >= 0.25 for h in strict))
        self.assertEqual(none, [])
        self.assertTrue(all("volume_x" in h for h in loose))
        huge, _, _ = scan.scan_orb(data, sorted(data), day, cutoff, 15, min_volume_x=50)
        self.assertEqual(huge, [])

    def test_deals_net_round_trips_and_merge_duplicates(self):
        rows = insider.parse_deals(read("trader-insider", "bulk.csv"), "bulk") + \
            insider.parse_deals(read("trader-insider", "block.csv"), "block")
        one, trips = insider.consolidate_deals(rows)
        kinds = {(r["symbol"], r["client"]): r["kind"] for r in one}
        self.assertEqual(kinds[("DEMOCO", "DEMO CAPITAL LLP")], "block+bulk")      # listed twice by NSE, once here
        self.assertEqual(len(one), 3)
        self.assertEqual(len(trips), 1)
        self.assertEqual((trips[0]["client"], trips[0]["net_shares"]), ("DEMO QUANT DESK LLP", 150000))
        self.assertIn("same day", insider.describe_trip(trips[0]))

    def test_news_drops_headlines_that_do_not_name_the_stock(self):
        p = news.mention_patterns({"TCS": "Tata Consultancy Services Ltd.", "RELIANCE": "Reliance Industries Ltd."})
        self.assertTrue(p["TCS"].search("TCS Share Price Today"))
        self.assertTrue(p["TCS"].search("Tata Consultancy wins a deal"))
        self.assertFalse(p["TCS"].search("Delaplex's (NSE:DELAPLEX) Shareholders Have More To Worry"))
        self.assertTrue(p["RELIANCE"].search("Reliance Jio plans"))
        self.assertFalse(p["RELIANCE"].search("HDFC Bank Market Capitalisation Reclaims Rs 13 Lakh Crore"))

    def test_news_falls_back_to_bse_filings(self):
        f = news.Fetcher(offline=os.path.join(FIX, "trader-news"))
        errs = []
        items = news.collect_bse(f, {"DEMOCO": "Demo Company Limited", "NOPE": None}, errs)
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0]["important"])
        self.assertEqual(items[0]["source"], "BSE filing")
        self.assertEqual(items[0]["time"], datetime.datetime(2026, 11, 12, 13, 1, 5, tzinfo=datetime.timezone.utc))
        self.assertTrue(items[0]["link"].endswith("/AttachLive/demo-b1.pdf"))
        self.assertTrue(any("trader/bse_codes.json" in e for e in errs))

    def test_results_fall_back_to_yahoo_when_nse_blocks(self):
        class Blocked(results.Fetcher):
            def get(self, url, name, accept="*/*"):
                if "nseindia.com" in url:
                    raise results.ResultsError("HTTP 403 for https://www.nseindia.com/")
                return results.Fetcher.get(self, url, name, accept)
        errs = []
        res = results.analyse(Blocked(offline=os.path.join(FIX, "trader-analyst")), "DEMOTWO", 6, errors=errs)
        self.assertEqual(res["source"], "yahoo")
        cur = res["rows"][0]
        self.assertEqual((cur["end"], cur["fiscal"]), ("2026-09-30", "Q2 FY27"))
        self.assertEqual(cur["revenue_yoy"], 15.0)
        self.assertEqual(cur["net_profit"], 8.6e9)                 # the shareholders' line, not total net income
        self.assertEqual(cur["operating_margin"], 15.9)
        self.assertTrue(any("Yahoo" in e for e in errs))
        with self.assertRaises(results.ResultsError):
            results.analyse(Blocked(offline=os.path.join(FIX, "trader-analyst")), "DEMOTWO", 6, source="nse")
