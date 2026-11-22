# The India Day Trader skill

11 Claude skills for day trading on NSE: scan hundreds of charts, track news and NSE filings, time every entry and exit in IST, and replay every outcome before you risk a rupee.

An Indian-market version of [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT), rebuilt for the National Stock Exchange: NSE symbols, the 9:15 AM to
3:30 PM IST session and NSE's holiday list, rupees with lakh and crore,
NSE tick sizes, Zerodha's charges (brokerage, STT, stamp duty, GST), intraday
(MIS) square-off, SEBI's insider-trading disclosures, NSE bulk and block
deals, results XBRL filings, and Zerodha's Kite MCP server as the broker.

Free, MIT, no signup, no API key for the data. The tools are plain Python
that read free public data: Yahoo Finance charts (`SYMBOL.NS`), NSE's own
CSV files and APIs, and Google News.

And no trade goes through until you say yes. Nothing in this pack can place
an order on its own. Paper trading is the default.

## Install

Paste this into Claude:

```
https://github.com/rathanhimakarvanguri/india-day-trader-skill

install skill
```

Or as a plugin, in Claude Code:

```
/plugin marketplace add rathanhimakarvanguri/india-day-trader-skill
/plugin install india-day-trader-skill@india-day-trader-skill
```

Or copy the folders, for plain `/trader-scanner` names:

```bash
git clone https://github.com/rathanhimakarvanguri/india-day-trader-skill.git
cp -r india-day-trader-skill/trader-* ~/.claude/skills/
```

The tools need Python 3.8 or newer. Nothing to pip install.

Or let the setup script do it all (checks Python, runs the tests, copies the
skills into `~/.claude/skills`, writes `trader/config.json` from the example,
and downloads the Nifty 500 list):

```bash
cd india-day-trader-skill && bash setup.sh
```

## What's new in 1.1

From the first live run on NSE:

- **When NSE blocks scripts** (HTTP 403 on www.nseindia.com), results come from
  Yahoo Finance's quarterly financials and company filings from BSE. NSE's file
  archive (the stock lists and bulk / block deals) still works directly.
- **News** keeps only headlines that name the stock.
- **Opening-range scan** needs a close at least 0.25 % over the range high, on
  at least the range bars' average volume, and ranks by the size of the break.
- **Bulk / block deals** merge the trade NSE lists twice, and set apart the
  same-day round trips of market makers and high-frequency desks.

## The eleven

| command | job | what it does |
| --- | --- | --- |
| `/trader-scanner` | Chart Scanner | Scans Nifty 500 (or every NSE EQ stock) for setups: opening-range breakouts, 20-day breakouts, flags, oversold bounces. |
| `/trader-news` | News Monitor | Google News, Yahoo and NSE corporate announcements on every stock you watch, tagged, in IST. |
| `/trader-entry` | Entry Timer | Watches a setup bar by bar from 9:15 AM and tells you the moment to get in. |
| `/trader-exit` | Exit Planner | Sets your stop and target on NSE's tick grid before you enter; flat by 3:10 PM. |
| `/trader-timemachine` | Time Machine | Replays every possible outcome of a trade before you risk a rupee: 10,000 simulated sessions plus every past time the setup fired. |
| `/trader-risk` | Risk Manager | Checks every trade against your rupee limits, the IST entry window, MIS square-off and the charges. |
| `/trader-budget` | Budget Manager | Sizes every position to your budget and max loss, whole shares, no leverage, with Zerodha's charges. |
| `/trader-broker` | Order Executor | Zerodha Kite orders (entry, SL-M stop, LIMIT target), paper by default, never without your yes. |
| `/trader-alerts` | Price Alerts | Rings when a price, a stop, the 9:15 bell or your flat-by time hits; knows NSE holidays. |
| `/trader-analyst` | Results Analyst | Reads quarterly results from NSE XBRL filings: revenue, profit, margins, EPS, QoQ and YoY, in crore. |
| `/trader-insider` | Insider Tracker | SEBI insider-trading disclosures (promoters, directors) and NSE bulk / block deals. |

## How to use it

Everything lands in a `trader/` folder in your project, and each skill reads
what the last one wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one trade)
alerts: stop, target, flat by 3:10 PM                                         (while it is open)
news / analyst / insider                                                       (on a schedule)
```

An example on the test fixtures (DEMOCO is a made-up stock; every fixture is
synthetic data):

1. **`/trader-scanner`** at 10:00 AM IST: which charts closed above their
   15-minute opening range (9:15 to 9:30).
2. **`/trader-news`**: DEMOCO's headlines and its NSE "Financial Result
   Updates" filing from the evening before.
3. **`/trader-entry`**: at 9:58 waiting (the 9:55 bar was still forming); at
   10:00 triggered, the first 5-minute close above the range, Rs 1,512.40.
4. **`/trader-exit`**: stop at the range midpoint rounded down to the Rs 0.10
   tick, Rs 1,501.50, so Rs 10.90 a share at risk; target 2R, Rs 1,534.20;
   flat by 3:10 PM, before Zerodha's own MIS square-off at about 3:20.
5. **`/trader-timemachine`**: 10,000 replays of the rest of the day from the
   stock's own 5-minute bars: target first 22.5 %, stop first 59.4 %. Leans
   toward the stop. That is the point of looking before you risk a rupee.
6. **`/trader-budget`** with a Rs 1,00,000 account and a Rs 500 max loss: 33
   shares (bound by the Rs 50,000 max order), Rs 359.70 at the stop, about
   Rs 53 of charges for the round trip.
7. **`/trader-risk`**: PASS or BLOCK, with the reason.
8. **`/trader-broker`**: the ticket in plain words, your yes for that exact
   order, then Claude's own Allow once / Deny card. On Kite it is three orders:
   the LIMIT buy (MIS), then an SL-M stop and a LIMIT target once it fills.
9. **`/trader-alerts`**: rings on the stop, the target and at 3:10 PM, and
   reminds you that Kite does not cancel the other exit by itself.

## The tools

All standard-library Python.

```bash
python3 trader-scanner/scan.py universe                             # Nifty 500, from NSE's CSV
python3 trader-scanner/scan.py daily                                # pre-market setups
python3 trader-scanner/scan.py orb --at 10:00                       # opening-range breakouts so far
python3 trader-news/news.py --tickers RELIANCE --hours 12           # headlines, NSE filings, today's move
python3 trader-entry/entry.py check RELIANCE --setup orb            # waiting / triggered / expired
python3 trader-exit/exit.py plan --stop or-mid --target 2R --write  # -> trader/plan.json
python3 trader-timemachine/timemachine.py run --write               # 10,000 replays + the history
python3 trader-budget/size.py --write                               # -> trader/orders.json
python3 trader-risk/check.py                                        # PASS / BLOCK per order
python3 trader-broker/ticket.py show                                # the tickets, READY or not
python3 trader-alerts/alerts.py add --from-plan                     # stop, target, flat by
python3 trader-analyst/results.py TCS                               # quarters, growth, EPS
python3 trader-insider/insider.py pit --symbols RELIANCE            # insider trades
python3 trader-insider/insider.py deals                             # bulk and block deals
```

```bash
python3 -m unittest discover -s tests -v
```

The tests run offline on synthetic fixtures built by `tests/make_fixtures.py`
(made-up companies, people and funds, shaped like NSE's and Yahoo's answers).

## Fine print

**Not financial advice.** This is software that reads public data and does
arithmetic. It does not know your situation and it cannot see the future.
SEBI's study of FY2023 found that 7 in 10 individual intraday traders in the
equity cash segment lost money. You can lose money. Decide for yourself, and
talk to a SEBI-registered investment adviser if you need advice.

**No trade goes through until you say yes.** Only `/trader-broker` can lead to
an order, and only after `/trader-risk` passes that exact order and you type
yes for it in the chat. Set the Kite `place_order` tool to "Needs approval" in
Claude, never "Always allow". No F&O, MIS leverage, short selling or margin
unless you turn them on.

**Paper first.** `"paper": true` is the default. Zerodha has no paper account,
so paper mode sends nothing: it records simulated fills and lets the alerts
watch your stop and target. Zerodha's hosted Kite MCP server cannot place
orders at all; trading needs your own self-hosted server and Kite Connect
keys, typed into your Claude Desktop config, never into the chat.

**SEBI's retail algo rules (from April 1, 2026).** Orders sent through a
broker API must come from a static IP you registered with the broker (the
Kite developer console). This pack never tries to get around that.

**Intraday square-off.** Zerodha closes open MIS positions itself from about
3:20 PM, at market, for a fee. The pack plans to be flat by 3:10 PM.

**Two exits that do not know about each other.** Zerodha has no equity
bracket orders, and GTT does not cover MIS. The stop (SL-M) and the target
(LIMIT) are separate orders: when one fills, cancel the other.

**Costs.** Charges use Zerodha's published equity rates; they change, so
check zerodha.com/charges and set your own under `"charges"` in the config.

**The Time Machine is a simulation, not a prediction.** It is built from the
stock's own last 60 days of 5-minute bars. Results days, news, circuit limits
and expiry days can do things those 60 days never did.

**A stop is a plan, not a guarantee.** In a fast market, across a gap or at a
circuit limit, a stop can fill well past its price, or not at all.

**The data is free and unofficial.** Yahoo's NSE data lags by minutes and can
change or rate-limit you. NSE's site sometimes turns scripts away; every tool
then says so and takes a saved file instead (`--offline`). Check anything that
matters in Kite before you act.

**Insider filings are public, not inside information.** They arrive days after
the trade. A bulk or block deal shows who traded, not why.

**Holidays.** The 2026 NSE holiday list is built in. NSE publishes next year's
list each December: add it to `trader/holidays.json`.

**Taxes.** Intraday equity gains are speculative business income in India.
Nothing here is tax advice.

## Files

```
trader-scanner/     SKILL.md, scan.py
trader-news/        SKILL.md, news.py
trader-entry/       SKILL.md, entry.py
trader-exit/        SKILL.md, exit.py
trader-timemachine/ SKILL.md, timemachine.py
trader-risk/        SKILL.md, check.py
trader-budget/      SKILL.md, size.py, config.example.json
trader-broker/      SKILL.md, ticket.py, claude_desktop_config.example.json
trader-alerts/      SKILL.md, alerts.py, alerts.example.json
trader-analyst/     SKILL.md, results.py, metrics.example.json
trader-insider/     SKILL.md, insider.py
tests/              unittest suite, make_fixtures.py, synthetic fixtures
setup.sh            one-time setup: tests, install the skills, trader/config.json
```

MIT. India edition by [Rathan Himakar Vanguri](https://www.linkedin.com/in/rathan-himakar-vanguri/),
built on the original Day Trader skill by [Jake Schincariol](https://opusjake.ai) (MIT).
