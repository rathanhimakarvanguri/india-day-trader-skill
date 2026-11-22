---
name: trader-scanner
description: >-
  Chart Scanner for the Indian market (NSE). Scans hundreds of NSE charts for
  setups: opening-range breakouts, 20-day breakouts, bull flags, oversold
  bounces. Builds the list of NSE EQ-series stocks (Nifty 500 by default, or
  every NSE equity) from NSE's own CSV files, runs a pre-market scan of daily
  closes and an intraday opening-range breakout scan on 5-minute bars in
  India time (9:15 AM to 3:30 PM IST), and writes trader/watchlist.json for
  trader-news and trader-entry. Free Yahoo data (SYMBOL.NS). Use when the user
  says "scan the market", "scan NSE", "find me setups", "what is breaking
  out", "opening range breakouts", "Nifty 500 scan", "scan for bull flags",
  "oversold stocks", "pre-market scan", "build my watchlist", "what should I
  look at today", or at the start of an Indian trading day before /trader-news.
argument-hint: "[universe | daily | orb] [--at HH:MM] [--index nifty500|all]"
---

# trader-scanner

The Chart Scanner is the first step of a day trade on NSE. It reads hundreds
of free charts and lists the ones that match a rule. That is all it does. A
scan is a list of charts that match a rule, not a list of stocks to buy, and a
setup on a chart is not a prediction. SEBI's own study of FY2023 found that
about 7 in 10 individual intraday traders in Indian equities lost money; the
scanner does not change that. It only saves you from flipping through 500
charts by hand.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                          # Nifty 500 -> trader/universe.txt
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe --index all              # every NSE EQ-series stock
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                             # before 9:15 AM -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols RELIANCE,TCS,INFY # or --watchlist FILE, --limit 200
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                               # after 9:35 AM IST -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 10:00                    # cut the clock at 10:00 AM IST
```

Flags: `--min-price 50` (rupees) and `--min-volume` (daily 5,00,000 shares,
orb 0), `--or-minutes 15`, `--min-break-pct 0.25` and `--min-volume-x 1.0`
(orb: how far and on how much volume the breakout must close), `--max-confirm 200`, `--now "2026-11-13 10:00"`
(India time) to pin the clock, `--offline PATH` to read saved files,
`--no-write`, `--show N`, `--json`. Exit code 0 when the scan found
something, 1 when it found nothing or could not run (the reason is one line).

## What it reads and writes

| file | what |
| --- | --- |
| NSE CSV | `universe`: `nsearchives.nseindia.com/content/indices/ind_nifty500list.csv` (or nifty50, nifty100, nifty200, midcap150, smallcap250), or `content/equities/EQUITY_L.csv` with `--index all` |
| `trader/universe.txt` | written by `universe`: one `SYMBOL\|Name` a line, read by `daily`, `orb` and trader-news (for company names) |
| `trader/watchlist.json` | written by `daily` and `orb`: `mode`, `as_of`, `universe`, `scanned`, `failed`, `hits[]` |
| `trader/config.json` | read by `orb`: `no_entries_after` (default 14:45) |

## The universe

Only **EQ series** stays. EQ is NSE's rolling-settlement segment, where you
can buy and sell the same stock on the same day. BE and BZ are trade-for-trade
(every trade must be delivered, so no intraday square-off), and SM / ST are
the SME boards. A row also needs a plain NSE symbol (capitals, digits, `&`,
`-`). Nifty 500 is the default because it is about 500 liquid names; the full
EQ list is about 2,000 and most of the extra names are thin.

NSE's site turns away scripts now and then (HTTP 403). If it does, open the CSV
link in a browser, save it, and run `universe --offline FILE`.

## The daily scan (before the open)

Yahoo's spark endpoint returns closes for 20 symbols a request, so Nifty 500
takes 25 requests (well under a minute with the polite pause). NSE stocks are
`SYMBOL.NS` on Yahoo (`M&M.NS`, `BAJAJ-AUTO.NS`). Liquidity comes from the
spark meta: last price at least `--min-price` (Rs 50) and last session's
volume at least `--min-volume`. Run it before 9:15 AM or after 3:30 PM IST.

| setup | the rule on closes |
| --- | --- |
| `breakout_20d` | the last close is above every close of the 20 sessions before it |
| `bull_flag` | up more than 10 % over the 10 sessions before the last 5, then the last 5 closes inside a 5 % range |
| `reclaim_ma20` | the close before was under its 20-day average, the last close is above it |
| `oversold` | RSI 14 (Wilder) under 30 |
| `oversold_bounce` | RSI 14 was under 30 yesterday and today closed up |

## The opening-range breakout scan (during the session)

NSE's session is 9:15 AM to 3:30 PM IST, after a pre-open call auction from
9:00 to 9:08. The opening range is the first `--or-minutes` (15): the 9:15,
9:20 and 9:25 five-minute bars. A hit is the first completed 5-minute bar to
CLOSE at least `--min-break-pct` (0.25 %) above the range high, on at least
`--min-volume-x` (1.0) times the range bars' average volume, at that bar's
close time. Without those two filters a strong morning flags most of the
Nifty 500 (a test on Fri 2026-11-20 found 138 of 200 charts a paisa or two
over their high), which is no list at all. `--min-break-pct 0 --min-volume-x 0`
gives the bare rule. Hits print biggest break first, with the volume multiple. The first possible hit
closes at 9:35 AM; 10:00 AM is a sensible first look.

1. Stage 1, every symbol: spark closes of today's 5-minute bars. A chart goes
   on only if a completed bar after the range closed at or above the highest
   close of the range (a necessary condition, so no breakout is lost).
2. Stage 2, each candidate: the v8 chart with real highs and lows, at most
   `--max-confirm` (200), the most traded first. PARTIAL is said out loud.

A chart is usable only when every 5-minute bar from 9:15 to the cutoff is
there; a missing bar means a circuit freeze or a thin stock. A stock locked at
its upper circuit cannot be bought at all, so check the price band before
acting on a hit. Before 9:35 AM, on a weekend or NSE holiday, after the close,
or after `no_entries_after`, it prints one line and writes nothing.

## Data and limits

- Yahoo's chart and spark endpoints are free, unofficial and can lag (NSE data
  on Yahoo is usually a few minutes behind). Bars, never ticks.
- Partial results are said as partial. Never round a partial scan up to "the
  whole market".
- NSE holidays for 2026 from NSE's circular. NSE publishes next year's list
  each December: put it in `trader/holidays.json` (`{"2027-01-26": "Republic Day"}`).

## Steps

1. Once a week or so: `scan.py universe`.
2. Before the open: `scan.py daily`. Tell the user the counts (fetched,
   liquid, scanned, hits) and the top few by setup.
3. After 9:35 AM IST (10:00 is a good first look): `scan.py orb`. Tell the
   user how many usable charts broke their range and when.
4. The user picks one chart. Hand it on: `/trader-news SYMBOL`, then
   `/trader-entry SYMBOL`. Never pick for them.

## Example (the test fixtures)

The tests replay a made-up wall of eight NSE-style charts (DEMO01 to DEMO08,
synthetic data) at 10:00 AM on Fri 2026-11-13:

```
Opening-range breakout scan, Fri 2026-11-13 10:00 AM IST: 15-minute range (9:15 to 9:30 AM), 5-minute bars, Yahoo (NSE).
Fetched 8 of 8 charts; 8 usable; 4 candidates, 4 confirmed with real highs and lows.
4 of 8 charts closed above their opening-range high by 10:00 AM:
   9:50 AM  DEMO01 Rs 1,649.62  range 1,631.04 to 1,639.78  +0.60% over
```

## Rules

- Say what was scanned: how many symbols, how many charts came back, how many
  were usable, and the time of the data.
- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Never print a P&L, a return or a profit figure.
- A hit is stale once the price has moved on. Re-run before acting on it.

## What it never does

It never places, sizes or checks an order, never says which stock to buy,
never calls data real time, and never promises that a setup works.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`): Zerodha has no paper account, so paper mode never sends
  anything; it records simulated fills. Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user clicked Allow once on Claude's own card because the Kite `place_order` tool is set to "Needs
  approval". Never set an order tool to "Always allow".
- No F&O, MIS leverage, short selling or margin unless the config allows it and the user confirms.
- Kite API keys, secrets, access tokens, passwords and TOTP codes live in the user's own Claude Desktop
  config or environment variables, never in the chat.
- SEBI's retail algo rules (from April 1, 2026): API orders must come from the static IP the user
  registered on the Kite developer console. This pack never tries to get around that.
