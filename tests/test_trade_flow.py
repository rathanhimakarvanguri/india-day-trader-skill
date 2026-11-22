"""One NSE day trade end to end, offline: scan -> entry -> exit -> time machine -> budget -> risk -> broker -> alerts."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from _load import FIX, ROOT, load

scan = load("trader-scanner", "scan")
size = load("trader-budget", "size")
risk = load("trader-risk", "check")
ticket = load("trader-broker", "ticket")


def run(tool, *args, cwd):
    p = subprocess.run([sys.executable, os.path.join(ROOT, tool)] + list(args), cwd=cwd,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    return p.returncode, p.stdout + p.stderr


class Flow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.dir, "trader"))
        with open(os.path.join(cls.dir, "trader", "config.json"), "w") as fh:
            json.dump({"budget": 100000, "paper": True}, fh)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def j(self, name):
        with open(os.path.join(self.dir, "trader", name)) as fh:
            return json.load(fh)

    def test_1_the_whole_trade(self):
        d = self.dir
        day = os.path.join(FIX, "trader-entry", "DEMOCO-2026-11-13-5m.json")
        code, out = run("trader-entry/entry.py", "check", "DEMOCO", "--now", "2026-11-13 09:58", "--offline", day,
                        cwd=d)
        self.assertEqual(code, 1, out)
        self.assertIn("WAITING", out)
        self.assertIn("The 9:55 bar is still forming", out)

        code, out = run("trader-entry/entry.py", "check", "DEMOCO", "--now", "2026-11-13 10:01", "--offline", day,
                        "--write", cwd=d)
        self.assertEqual(code, 0, out)
        self.assertIn("TRIGGERED 10:00 AM at Rs 1512.40", out)
        self.assertIn("Opening range 9:15-9:30: high Rs 1508.90, low Rs 1494.10", out)
        self.assertEqual(self.j("entry.json")["symbol"], "DEMOCO")

        code, out = run("trader-exit/exit.py", "plan", "--now", "2026-11-13 10:01", "--write", cwd=d)
        self.assertEqual(code, 0, out)
        plan = self.j("plan.json")
        self.assertEqual((plan["entry"], plan["stop"], plan["target"]), (1512.4, 1501.5, 1534.2))
        self.assertEqual((plan["risk_per_share"], plan["tick"], plan["flat_by"]), (10.9, 0.1, "15:10"))
        self.assertEqual(plan["currency"], "INR")

        code, out = run("trader-timemachine/timemachine.py", "run", "--offline",
                        os.path.join(FIX, "trader-timemachine", "DEMOCO-60d5m.json.gz"),
                        "--now", "2026-11-13 10:01", "--write", cwd=d)
        self.assertEqual(code, 0, out)
        self.assertIn("10:00 AM to 3:10 PM (62 five-minute bars), seed 19", out)
        mc = self.j("timemachine.json")["mc"]
        self.assertAlmostEqual(mc["p_target"] + mc["p_stop"] + mc["p_neither"], 1.0, 6)
        self.assertEqual(mc["until"], "15:10")
        code2, out2 = run("trader-timemachine/timemachine.py", "run", "--offline",
                          os.path.join(FIX, "trader-timemachine", "DEMOCO-60d5m.json.gz"),
                          "--now", "2026-11-13 10:01", "--json", cwd=d)
        self.assertEqual(json.loads(out2)["mc"]["p_target"], mc["p_target"])      # same seed, same numbers

        code, out = run("trader-budget/size.py", "--now", "2026-11-13 10:01", "--write", cwd=d)
        self.assertEqual(code, 0, out)
        self.assertIn("Size: 33 shares of DEMOCO = Rs 49,909.20", out)
        self.assertIn("1. BUY 33 DEMOCO, NSE, MIS, LIMIT 1512.40, DAY", out)
        self.assertIn("2. SELL 33 DEMOCO, SL-M trigger 1501.50", out)
        order = self.j("orders.json")["orders"][0]
        self.assertEqual((order["qty"], order["product"], order["type"], order["limit_price"]),
                         (33, "MIS", "limit", 1512.4))

        code, out = run("trader-risk/check.py", "--now", "2026-11-13 10:02", cwd=d)
        self.assertEqual(code, 0, out)
        self.assertIn("PASS  #1 buy DEMOCO 33 shares, entry", out)
        self.assertIn("max loss Rs 359.70 (limit Rs 500)", out)

        code, out = run("trader-broker/ticket.py", "show", "--now", "2026-11-13 10:02", cwd=d)
        self.assertEqual(code, 0, out)
        self.assertIn("READY", out)
        self.assertIn("PAPER", out)
        code, out = run("trader-broker/ticket.py", "approve", "--index", "1", "--reply", "yes to all",
                        "--now", "2026-11-13 10:02", cwd=d)
        self.assertEqual(code, 1, out)
        code, out = run("trader-broker/ticket.py", "approve", "--index", "1", "--reply", "yes, 33 DEMOCO",
                        "--now", "2026-11-13 10:02", cwd=d)
        self.assertEqual(code, 0, out)
        code, out = run("trader-broker/ticket.py", "exits", "--index", "1", "--now", "2026-11-13 10:02", cwd=d)
        self.assertEqual(code, 1, out)                       # not before the entry is placed
        code, out = run("trader-broker/ticket.py", "result", "--index", "1", "--status", "placed",
                        "--filled-qty", "33", "--filled-price", "1512.40", "--now", "2026-11-13 10:03", cwd=d)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.j("portfolio.json")["cash"], 50090.8)
        code, out = run("trader-broker/ticket.py", "exits", "--index", "1", "--json", "--now", "2026-11-13 10:03",
                        cwd=d)
        legs = json.loads(out)["exit_orders"]
        self.assertEqual([l["order_type"] for l in legs], ["SL-M", "LIMIT"])
        self.assertEqual((legs[0]["trigger_price"], legs[1]["price"]), (1501.5, 1534.2))
        state = self.j("state/broker.json")
        self.assertTrue(state["orders"][0]["at"].endswith("+05:30"))

        code, out = run("trader-alerts/alerts.py", "add", "--from-plan", cwd=d)
        self.assertEqual(code, 0, out)
        code, out = run("trader-alerts/alerts.py", "check", "--now", "2026-11-13 15:10", "--offline",
                        os.path.join(FIX, "trader-alerts"), cwd=d)
        self.assertEqual(code, 0, out)
        self.assertIn("at or below your stop Rs 1501.50", out)
        self.assertIn("the target order does not cancel itself", out)
        self.assertIn("ALERT Flat by", out)

        code, out = run("trader-broker/ticket.py", "flatten", "--symbol", "DEMOCO", "--now", "2026-11-13 15:10",
                        cwd=d)
        self.assertEqual(code, 0, out)
        code, out = run("trader-risk/check.py", "--now", "2026-11-13 15:11", cwd=d)
        self.assertEqual(code, 0, out)                       # an exit is never blocked by the window
        self.assertIn("sell DEMOCO 33 shares, exit", out)


class Sizing(unittest.TestCase):
    PLAN = {"symbol": "DEMOCO", "side": "buy", "date": "2026-11-13", "entry": 1512.4, "stop": 1501.5,
            "target": 1534.2, "setup": "orb", "flat_by": "15:10"}

    def test_max_loss_binds_with_a_bigger_order_cap(self):
        s = size.size_trade(self.PLAN, {"budget": 300000, "max_order_inr": 200000}, limit=1512.4, today="2026-11-13")
        self.assertEqual((s["qty"], s["bound_by"], s["max_loss"]), (45, "max loss", 490.5))

    def test_stop_too_far_is_refused(self):
        plan = dict(self.PLAN, stop=900.0, target=2800.0)
        s = size.size_trade(plan, {"budget": 100000}, limit=1512.4, today="2026-11-13")
        self.assertEqual(s["qty"], 0)
        self.assertIn("more than your Rs 500 max loss", s["refusal"])

    def test_charges_match_zerodha_intraday_rates(self):
        # buy 33 at 1512.40 (49,909.20), sell at 1534.20 (50,628.60)
        c = size.charges(33, 1512.4, 1534.2)
        buy, sell = 49909.2, 50628.6
        brok = min(buy * 0.0003, 20) + min(sell * 0.0003, 20)
        txn = (buy + sell) * 0.0000297
        sebi = ipft = (buy + sell) * 10 / 1e7
        want = brok + sell * 0.00025 + buy * 0.00003 + txn + sebi + ipft + 0.18 * (brok + txn + sebi + ipft)
        self.assertAlmostEqual(c, round(want, 2), 2)
        self.assertEqual(c, risk.charges(33, 1512.4, 1534.2))
        self.assertGreater(size.charges(33, 1512.4, 1534.2, "CNC"), c)       # delivery STT is 0.1% both sides


class RiskBlocks(unittest.TestCase):
    NOW = risk.parse_now("2026-11-13 10:02")
    BASE = {"symbol": "DEMOCO", "exchange": "NSE", "product": "MIS", "side": "buy", "qty": 33, "type": "limit",
            "time_in_force": "day", "limit_price": 1512.4, "order_class": "bracket",
            "take_profit_limit_price": 1534.2, "stop_loss_stop_price": 1501.5}
    CFG = {"budget": 100000}

    def verdict(self, order, now=None, cfg=None):
        res = risk.check([order], cfg or self.CFG, now=now or self.NOW, today=None)
        return res["results"][0]

    def test_the_base_order_passes(self):
        self.assertEqual(self.verdict(self.BASE)["verdict"], "PASS")

    def test_blocks(self):
        cases = [
            (dict(self.BASE, qty=None, notional=5000), "whole shares only"),
            (dict(self.BASE, qty=10.5), "whole number of shares"),
            (dict(self.BASE, symbol="NIFTY26NOVFUT"), "F&O contract"),
            (dict(self.BASE, product="NRML"), "product must be MIS"),
            (dict(self.BASE, time_in_force="gtc"), "validity must be day or ioc"),
            (dict(self.BASE, qty=60), "max loss"),
        ]
        for order, why in cases:
            r = self.verdict(order)
            self.assertEqual(r["verdict"], "BLOCK", why)
            self.assertIn(why, " ".join(r["reasons"]), why)

    def test_window_holiday_and_square_off(self):
        r = self.verdict(self.BASE, now=risk.parse_now("2026-11-13 09:20"))
        self.assertIn("no new entries before 09:30", " ".join(r["reasons"]))
        r = self.verdict(self.BASE, now=risk.parse_now("2026-11-24 10:00"))
        self.assertIn("NSE holiday", " ".join(r["reasons"]))
        r = self.verdict(self.BASE, now=risk.parse_now("2026-11-13 15:12"), cfg=dict(self.CFG, no_entries_after=None))
        self.assertIn("square-off", " ".join(r["reasons"]))

    def test_costs_eat_a_tiny_trade(self):
        tiny = dict(self.BASE, qty=1, limit_price=168.42, symbol="DEMOSTEEL", take_profit_limit_price=168.9,
                    stop_loss_stop_price=168.1)
        r = self.verdict(tiny, cfg=dict(self.CFG, min_order_inr=0))
        self.assertIn("costs:", " ".join(r["reasons"]))

    def test_cash_without_margin(self):
        r = self.verdict(dict(self.BASE, qty=40, limit_price=1512.4), cfg={"budget": 30000, "max_loss_per_trade_inr": 5000})
        self.assertIn("MIS leverage", " ".join(r["reasons"]))


class KiteTickets(unittest.TestCase):
    def test_entry_arguments_are_kite_connect_fields(self):
        o = RiskBlocks.BASE
        self.assertEqual(ticket.tool_input(o), {
            "variety": "regular", "exchange": "NSE", "tradingsymbol": "DEMOCO", "quantity": 33, "product": "MIS",
            "validity": "DAY", "tag": "idts", "transaction_type": "BUY", "order_type": "LIMIT", "price": 1512.4})
        mkt = dict(o, type="market")
        mkt.pop("limit_price")
        self.assertEqual(ticket.tool_input(mkt)["order_type"], "MARKET")
        self.assertNotIn("price", ticket.tool_input(mkt))

    def test_fingerprint_matches_risk(self):
        self.assertEqual(ticket.fingerprint(RiskBlocks.BASE), risk.fingerprint(RiskBlocks.BASE))
        self.assertNotEqual(ticket.fingerprint(RiskBlocks.BASE),
                            ticket.fingerprint(dict(RiskBlocks.BASE, product="CNC")))

    def test_a_yes_must_be_explicit(self):
        o = RiskBlocks.BASE
        self.assertTrue(ticket.parse_yes("yes", o)[0])
        self.assertTrue(ticket.parse_yes("Yes, 33 shares", o)[0])
        for reply in ("ok", "sure", "yes to all", "yes but wait", "yes?", "yes 50", "yes DEMOSTEEL"):
            self.assertFalse(ticket.parse_yes(reply, o, ["DEMOCO", "DEMOSTEEL"])[0], reply)


if __name__ == "__main__":
    unittest.main()
