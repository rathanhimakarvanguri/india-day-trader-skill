"""India market basics shared by every tool: IST, the NSE calendar, Yahoo symbols, rupees, ticks."""

import datetime
import os
import unittest

from _load import FIX, load

scan = load("trader-scanner", "scan")
entry = load("trader-entry", "entry")
exitp = load("trader-exit", "exit")
tm = load("trader-timemachine", "timemachine")
risk = load("trader-risk", "check")
alerts = load("trader-alerts", "alerts")


class IST(unittest.TestCase):
    def test_ist_is_utc_plus_five_thirty_all_year(self):
        for month in (1, 4, 7, 11):
            utc = datetime.datetime(2026, month, 13, 3, 45)
            self.assertEqual(scan.to_ist(utc), datetime.datetime(2026, month, 13, 9, 15))
            self.assertEqual(scan.ist_to_utc(datetime.datetime(2026, month, 13, 9, 15)), utc)

    def test_now_without_an_offset_is_india_time(self):
        self.assertEqual(scan.parse_now("2026-11-13 10:00"), datetime.datetime(2026, 11, 13, 4, 30))
        self.assertEqual(entry.parse_now("2026-11-13 10:00"), datetime.datetime(2026, 11, 13, 4, 30))
        self.assertEqual(scan.parse_now("2026-11-13T04:30:00Z"), datetime.datetime(2026, 11, 13, 4, 30))

    def test_aware_times_convert(self):
        aware = datetime.datetime(2026, 11, 13, 4, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(alerts.to_ist(aware), datetime.datetime(2026, 11, 13, 10, 0))


class Calendar(unittest.TestCase):
    def test_session_is_915_to_1530(self):
        self.assertEqual(scan.session(datetime.date(2026, 11, 13)),
                         (datetime.time(9, 15), datetime.time(15, 30)))
        self.assertEqual(tm.SESSION_BARS, 75)

    def test_nse_holidays_2026(self):
        for d, name in (("2026-01-26", "Republic Day"), ("2026-11-10", "Diwali"), ("2026-11-24", "Guru Nanak"),
                        ("2026-10-20", "Dussehra"), ("2026-03-03", "Holi")):
            ok, why = scan.trading_day(datetime.date.fromisoformat(d))
            self.assertFalse(ok, d)
            self.assertIn(name, why)
        self.assertTrue(scan.trading_day(datetime.date(2026, 11, 13))[0])
        self.assertFalse(scan.trading_day(datetime.date(2026, 11, 14))[0])      # a Saturday

    def test_every_tool_has_the_same_holiday_list(self):
        for mod in (entry, exitp, risk, alerts):
            self.assertEqual(mod.NSE_HOLIDAYS, scan.NSE_HOLIDAYS, mod.__name__)

    def test_alerts_clock_on_a_holiday_and_before_the_open(self):
        st = alerts.market_status(alerts.parse_now("2026-11-24 10:00"))
        self.assertFalse(st["open"])
        self.assertIn("Guru Nanak", st["reason"])
        self.assertEqual(st["next_open"], "2026-11-25 09:15")
        st = alerts.market_status(alerts.parse_now("2026-11-13 09:04"))
        self.assertIn("pre-open", st["reason"])
        self.assertTrue(alerts.market_status(alerts.parse_now("2026-11-13 15:29"))["open"])
        self.assertFalse(alerts.market_status(alerts.parse_now("2026-11-13 15:30"))["open"])


class Symbols(unittest.TestCase):
    def test_yahoo_symbols(self):
        self.assertEqual(scan.to_yahoo("RELIANCE"), "RELIANCE.NS")
        self.assertEqual(scan.to_yahoo("M&M"), "M%26M.NS")
        self.assertEqual(scan.to_yahoo("BAJAJ-AUTO"), "BAJAJ-AUTO.NS")
        self.assertEqual(scan.from_yahoo("M%26M.NS"), "M&M")
        self.assertEqual(scan.from_yahoo("TCS.NS"), "TCS")
        self.assertEqual(entry.yahoo_symbol("INFY"), "INFY.NS")
        self.assertEqual(tm.yahoo_symbol("SBIN"), "SBIN.NS")


class Rupees(unittest.TestCase):
    def test_indian_digit_grouping(self):
        self.assertEqual(scan.money(1234567.5), "Rs 12,34,567.50")
        self.assertEqual(scan.money(999), "Rs 999.00")
        self.assertEqual(exitp.money(1512.4), "Rs 1,512.40")
        self.assertEqual(risk.money(150000), "Rs 1,50,000")
        self.assertEqual(risk.money(359.7), "Rs 359.70")
        self.assertEqual(risk.money(-1500), "-Rs 1,500")


class Ticks(unittest.TestCase):
    def test_nse_tick_bands(self):
        D = exitp.D
        for price, tick in (("168.42", "0.01"), ("249.99", "0.01"), ("250", "0.05"), ("999", "0.05"),
                            ("1512.40", "0.10"), ("7400", "0.50"), ("15000", "1.00"), ("30000", "5.00")):
            self.assertEqual(exitp.tick_for(D(price)), D(tick), price)
            self.assertAlmostEqual(tm.tick_for(float(price)), float(tick), 9, price)

    def test_rounding_to_the_tick(self):
        D = exitp.D
        self.assertEqual(exitp.floor_tick(D("1501.515"), D("0.10")), D("1501.50"))
        self.assertEqual(exitp.round_tick(D("1534.25"), D("0.10")), D("1534.30"))
        self.assertEqual(exitp.floor_tick(D("166.7358"), D("0.01")), D("166.73"))
        self.assertEqual(tm.cents_away(1501.515, True), 1501.5)
        self.assertEqual(tm.cents_away(1501.515, False), 1501.6)


class Fixtures(unittest.TestCase):
    def test_fixtures_exist(self):
        for rel in ("trader-entry/DEMOCO-2026-11-13-5m.json", "trader-timemachine/DEMOCO-60d5m.json.gz",
                    "trader-scanner/EQUITY_L.csv", "trader-analyst/results-DEMOCO.json"):
            self.assertTrue(os.path.exists(os.path.join(FIX, rel)), rel)


if __name__ == "__main__":
    unittest.main()
