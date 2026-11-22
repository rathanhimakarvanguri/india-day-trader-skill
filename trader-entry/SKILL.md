---
name: trader-entry
description: >-
  Entry Timer for NSE stocks. Watches a setup bar by bar and tells you the
  moment to get in. Reads free Yahoo 1-minute or 5-minute bars for SYMBOL.NS,
  builds the opening range (the first 15 minutes from 9:15 AM IST by default)
  and calls the entry on the first completed bar that CLOSES above the range
  high, or above a level you give it (like a 20-day high from the scanner),
  with an optional volume check. Says waiting and how far, triggered with the
  time and the rupee price, expired, or not open yet, and writes
  trader/entry.json for /trader-exit. Long side only. It never places an
  order. Use when the user says "tell me when to get in", "watch RELIANCE",
  "has it broken out", "did it break the opening range", "entry signal",
  "time my entry", "check my watchlist", or after /trader-scanner and
  /trader-news, before /trader-exit.
argument-hint: "[SYMBOL] [--setup orb|level] [--interval 5m|1m]"
---

# trader-entry

The Entry Timer turns a setup into one moment: the bar that confirms it. It
reads bars, 1-minute or 5-minute, and waits for each one to finish. A price
that pokes above the high in the middle of a bar is not an entry. A bar that
CLOSES above it is. Then it says the time and the price, writes them down for
the Exit Planner, and stops. It never buys anything. Most intraday traders in
India lose money (SEBI's FY2023 study: 7 in 10), and a clean signal does not
change that.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE              # 15-minute opening range, 5-minute bars
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE --write      # also save trader/entry.json
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE --setup level --level 1520.50
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE --interval 1m --min-volume-x 1.5
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch RELIANCE --until 14:45  # one line per closed bar
python3 "${CLAUDE_SKILL_DIR}/entry.py" watchlist                   # every hit in trader/watchlist.json
```

Other flags: `--or-minutes N` (default 15), `--json`, `--offline FILE` (a
saved Yahoo chart JSON, or a folder of `<SYMBOL>.json`), `--now "2026-11-13
10:00"` (India time) to replay a day. `watch` with `--now` or `--offline`
runs on a simulated clock and replays the day without waiting.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/watchlist.json` | the scanner's hits (`hits[].symbol`), for `watchlist` |
| `trader/config.json` | `no_entries_before` (09:30) and `no_entries_after` (14:45), IST. Optional |
| Yahoo chart API | today's bars for `SYMBOL.NS`, `range=1d&interval=5m` (or `1m`): free, unofficial, can lag |
| `trader/entry.json` | with `check --write`, or when `watch` triggers: symbol, setup, status, time, bar, price, level, opening range |

## The rule

- **Opening range (orb).** The high and low of the first 15 minutes of NSE's
  session: the 9:15, 9:20 and 9:25 five-minute bars, or fifteen 1-minute bars.
  The pre-open auction (9:00 to 9:08) sets the open but is not a bar.
- **Level.** A price you give, like a 20-day high from `/trader-scanner`.
- **The trigger** is the first completed bar after the range that CLOSES
  above the level. A wick above is not a trigger. A close exactly at the
  level is not above it.
- **The time** is that bar's close time (the 9:55 bar closes at 10:00 AM).
  The price is its close, in rupees.
- **Only closed bars count.** Yahoo's live tick is never a bar.
- **Volume, if you want it.** `--min-volume-x 1.5` also needs the trigger
  bar's volume at 1.5 times the range bars' average.
- **Time limits.** No entries before 9:30 or after 14:45 (config). The late
  cutoff leaves room before the broker squares intraday (MIS) positions off
  by itself at about 3:20 PM.
- **What it says.** Waiting (and how far), triggered, expired, or no data.
  Before 9:15: not open yet. Before 9:30: the range is still forming.
  Weekends and NSE holidays: the market is closed.

## Steps

1. Get the symbol from the user, or run `entry.py watchlist` after
   `/trader-scanner`. Check `/trader-news` for it first.
2. Run `entry.py check SYMBOL`. Tell the user the status in one line.
3. To wait for it, Claude can run `entry.py watch SYMBOL --until 14:45` in the
   background, or `entry.py check SYMBOL --write` on a `/loop` every 5 minutes.
   Keep the computer awake while it watches.
4. When it triggers, say the time and the price, and that nothing was placed.
   If the trigger is more than a bar old, say so: a late entry is a different trade.
5. Hand off to `/trader-exit` to set the stop and the target BEFORE anything is bought.

## Example (the test fixtures)

DEMOCO, a made-up NSE stock in the tests, Fri 2026-11-13, 5-minute bars:

```
DEMOCO  Fri 2026-11-13 10:01 IST  opening-range breakout (15-minute range) on 5-minute bars (Yahoo, free, can lag)
Opening range 9:15-9:30: high Rs 1508.90, low Rs 1494.10 (3 of 3 bars).
TRIGGERED 10:00 AM at Rs 1512.40: the 9:55 bar (bar 8) closed above the range high Rs 1508.90 (+0.23%).
This is the moment to get in, if you take the trade. Nothing was placed.
```

At 9:58 the same file says WAITING: the 9:55 bar was still forming.

## Rules

- Bar by bar, on free Yahoo bars. They are unofficial and lag NSE by minutes.
  Say so when a minute matters, and check Kite's own chart before acting.
- A signal is information, not an order, and not a promise.
- Long side only. Intraday shorting exists in India, but this pack plans longs only.
- One trigger per setup per day: the first close above.
- A stock at its upper circuit cannot be bought: say so if the price is pinned.

## What it never does

It never places an order, never sizes a position, never sets the stop (that
is `/trader-exit`), never moves the level after the fact, and never counts a
bar that has not closed. It never runs `/trader-broker` from a background
watch: nobody is there to say yes.

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
