import json
import os
import re
import unittest

from _load import ROOT

SKILLS = ["trader-scanner", "trader-news", "trader-entry", "trader-exit", "trader-timemachine",
          "trader-risk", "trader-budget", "trader-broker", "trader-alerts", "trader-analyst",
          "trader-insider"]
ABOUT = ("11 Claude skills for day trading on NSE: scan hundreds of charts, track news and NSE filings, time "
         "every entry and exit in IST, and replay every outcome before you risk a rupee.")
# words from the US edition that must not survive in the India edition's tools and skills
US_ONLY = [r"\bNYSE\b", r"\bAlpaca\b", r"\bTSLA\b", r"New York", r"\bFINRA\b", r"pattern-day-trader rule applies",
           r"\bSEC EDGAR\b", r"\b8-K\b", r"place_stock_order", r"\$\d", r"_usd\b", r"nasdaqtrader"]


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


def files(exts=(".md", ".py", ".json")):
    for s in SKILLS:
        for f in sorted(os.listdir(os.path.join(ROOT, s))):
            if f.endswith(exts):
                yield os.path.join(s, f)


class Repo(unittest.TestCase):
    def test_eleven_skill_folders_at_the_root(self):
        found = sorted(d for d in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))

    def test_frontmatter_name_and_description(self):
        for s in SKILLS:
            fm, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertRegex(fm, r"description: ", s)
            self.assertGreater(len(fm), 300, "%s description is too thin" % s)
            self.assertGreater(len(text.splitlines()), 60, s)

    def test_every_skill_carries_the_safety_block(self):
        for s in SKILLS:
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            self.assertIn("not financial advice", low, s)
            self.assertIn("explicit yes", low, s)
            self.assertIn("needs approval", low, s)
            self.assertIn("never in the chat", low, s)

    def test_no_us_edition_leftovers(self):
        for rel in files():
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for rx in US_ONLY:
                self.assertIsNone(re.search(rx, text), "%s still says %s" % (rel, rx))

    def test_plugin_manifest(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as fh:
            plugin = json.load(fh)
        self.assertEqual(plugin["name"], "india-day-trader-skill")
        self.assertEqual(plugin["skills"], "./")
        self.assertEqual(plugin["description"], ABOUT)
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as fh:
            market = json.load(fh)
        self.assertEqual(market["plugins"][0]["name"], "india-day-trader-skill")

    def test_readme(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = " ".join(fh.read().split())
        self.assertTrue(readme.startswith("# The India Day Trader skill"))
        self.assertIn(ABOUT, readme)
        self.assertIn("Jakeschincariol/day-trader-skill", readme)          # credit the original (MIT)
        for s in SKILLS:
            self.assertIn("/" + s, readme, s)

    def test_license_keeps_the_original_copyright(self):
        with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("MIT License", text)
        self.assertIn("Jake Schincariol", text)

    def test_no_em_dashes(self):
        for rel in list(files()) + ["README.md"]:
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                self.assertNotIn("—", fh.read(), rel)

    def test_every_tool_runs_on_python_3_8(self):
        for rel in files((".py",)):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                src = fh.read()
            for bad in ("import zoneinfo", "from zoneinfo", ".removeprefix(", ".removesuffix("):
                self.assertNotIn(bad, src, rel)
            self.assertNotRegex(src, r"(?m)^\s+match \w+.*:$", rel)
            for g in ("list[", "dict[", "tuple["):
                self.assertNotRegex(src, r"(?<![\w.\"'])%s" % re.escape(g), rel)

    def test_example_config_is_india_and_safe(self):
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        for k in ("max_loss_per_trade_inr", "max_daily_loss_inr", "max_trades_per_day", "min_reward_risk",
                  "require_stop", "no_entries_after", "flat_by", "max_cost_pct_of_reward"):
            self.assertIn(k, cfg, k)
        self.assertIs(cfg["paper"], True)
        self.assertIs(cfg["require_stop"], True)
        for k in ("allow_short", "allow_margin", "allow_options"):
            self.assertIs(cfg[k], False, k)
        self.assertEqual((cfg["broker"], cfg["product"], cfg["flat_by"]), ("zerodha", "MIS", "15:10"))

    def test_kite_config_example_has_no_real_keys(self):
        with open(os.path.join(ROOT, "trader-broker", "claude_desktop_config.example.json")) as fh:
            cfg = json.load(fh)
        env = cfg["mcpServers"]["kite"]["env"]
        self.assertIn("NEVER_IN_CHAT", env["KITE_API_KEY"])
        self.assertIn("NEVER_IN_CHAT", env["KITE_API_SECRET"])

    def test_fixtures_are_synthetic(self):
        fix = os.path.join(ROOT, "tests", "fixtures")
        for base, _, names in os.walk(fix):
            for n in names:
                self.assertTrue(n.startswith(("DEMO", "pit-DEMO", "results-DEMO", "gnews-DEMO", "yahoo-DEMO",
                                              "nse-DEMO", "chart-DEMO", "daily-spark", "wall5m", "shapes",
                                              "EQUITY_L", "ind_nifty500", "bulk", "block", "yahoo-ts-DEMO", "bse-DEMO",
                                              "bse-scrips")), n)


if __name__ == "__main__":
    unittest.main()
