---
name: trader-alerts
description: >-
  Price Alerts and the NSE clock. Rings when a price, a stop, a target, a
  percent move, the 9:15 AM opening bell or a time (like your 3:10 PM flat-by,
  before the broker's intraday auto square-off) hits, each once. Turns
  trader/plan.json into stop, target and flat-by alerts for that day, reads
  free delayed Yahoo quotes for SYMBOL.NS, writes trader/prices.json for
  trader-budget and trader-risk, and knows NSE's session (9:15 AM to 3:30 PM
  IST, pre-open 9:00 to 9:08) and the 2026 NSE holidays. When the stop or
  target rings on a Zerodha trade it reminds you to cancel the other exit
  order, which Kite does not cancel by itself. Use when the user says "alert
  me", "ring me when", "watch my stop", "is the market open", "NSE holiday",
  "what time does the market open", "remind me to get out", "set alerts
  from my plan", or right after /trader-exit and while a trade is open.
argument-hint: "[add --from-plan | check | clock | quote SYMBOL]"
---

# trader-alerts

Price Alerts watches the levels you set so you do not stare at a chart. It
rings each alert once, says what happened in one line, and goes quiet. An
alert is information, not an order: when the stop rings, it tells you, and on
a live trade your SL-M order at Zerodha is what actually gets you out.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock                      # is NSE open? next open / close
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote RELIANCE --write     # quotes -> trader/prices.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write   # every symbol in your portfolio and plan
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan            # stop, target and flat-by from trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol RELIANCE --stop 1501.50
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol INFY --pct 3
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --at 15:10 --label "flat by"
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                      # rings what hit, once
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "${CLAUDE_SKILL_DIR}/alerts.py" reset reliance-plan-stop
```

`--now "2026-11-13 15:10"` pins the clock (India time); `--offline DIR` reads
saved quote files (`yahoo-<SYMBOL>.json`) instead of the network.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | the trade from trader-exit, for `add --from-plan` |
| `trader/alerts.json` | the rules (`alerts.example.json` in this folder) |
| `trader/state/alerts.json` | which rules rang and when, so each rings once |
| `trader/prices.json` | the latest quotes, merged in, for trader-budget and trader-risk |
| `trader/portfolio.json` | the symbols held, for `quote --holdings` |
| `trader/holidays.json` | optional: next year's NSE holidays, `{"2027-01-26": "Republic Day"}` |

## Rule types

| type | rings when | rings again |
| --- | --- | --- |
| `above` / `target` | price at or above `price` | after `reset`, or on its own if `"rearm": true` and the price fell back |
| `below` / `stop` | price at or below `price` | same |
| `pct_move` | moved `pct` percent from the previous close (or `ref`), optional `direction` up or down | once per day at most |
| `time` | the IST clock passed `at` ("15:10") on a trading day | once per trading day |
| `opening_bell` | NSE is open (9:15 AM) | once per trading day |

A rule with `"date"` is watched on that IST date only; `--from-plan` rules
carry the plan's date, so yesterday's stop never rings today.

## Quotes

- Yahoo: `query2.finance.yahoo.com/v8/finance/chart/<SYMBOL>.NS`, an
  unofficial free JSON endpoint, one request per symbol, half a second apart,
  `query1` as the fallback. NSE prices on Yahoo are delayed (often a few
  minutes). Fine for alerts and for checking a size, not for timing an order.
  trader-risk only uses a price under 15 minutes old.
- For a live price, read it from the Kite connector (`get_ltp` or
  `get_quotes`, read only) and write it into `trader/prices.json` as
  `{"as_of": "...Z", "prices": {"RELIANCE": 1512.4}}`.

## The NSE clock

Pre-open call auction 9:00 to 9:08 AM, regular session 9:15 AM to 3:30 PM IST,
Monday to Friday. India has no daylight saving time. Closed on the 2026 NSE
equity holidays from NSE's circular: Jan 15 (Maharashtra municipal
elections), Jan 26, Mar 3 (Holi), Mar 26, Mar 31, Apr 3, Apr 14, May 1,
May 28, Jun 26, Sep 14, Oct 2, Oct 20, Nov 10 (Diwali Balipratipada), Nov 24
and Dec 25. Muhurat trading (a short evening session on Diwali) is announced
by NSE each year and is not in the calendar. NSE publishes the next year's
list each December: add it to `trader/holidays.json`. For a year with no list,
the clock says the holiday list is unknown.

## Steps

1. Right after trader-exit writes the plan, run `add --from-plan`. Confirm the
   three alerts back to the user: the stop, the target and the flat-by time.
2. Run `check` while the trade is open: every few minutes from a Claude
   scheduled task or `/loop`. A check reads the latest delayed quote; a price
   can pass a level between two checks.
3. Tell the user what rang in one line each.
   - **Stop or target** on a live trade: the SL-M or the LIMIT exit has
     probably filled at Zerodha, and the OTHER exit is still open. Check
     `get_orders`, cancel the other one, and record the fill with
     trader-broker. On a paper trade, record the simulated sell.
   - **Flat by**: close anything still open before Zerodha's own MIS
     square-off at about 3:20 PM: trader-broker `flatten`, then trader-risk,
     then the user's yes. Never act for them.

## Example (the test fixtures)

DEMOCO, plan stop 1501.50, target 1534.20, flat by 15:10. A `check` at 3:10 PM
with a saved quote of 1500.90:

```
NSE OPEN (2026-11-13 15:10 India (IST), regular session).
ALERT DEMOCO is Rs 1500.90: at or below your stop Rs 1501.50 (plan stop: opening-range midpoint). On Kite the target order does not cancel itself: cancel it now (get_orders, cancel_order).
ALERT Flat by (before the MIS square-off): it is 15:10 India (IST) (set for 15:10), the market closes at 15:30. ...
```

## Rules

- An alert is a fact about a price or the clock. Say it as a fact.
- Never present a quote as live. Free quotes are delayed and unofficial.
- Confirm every new rule back to the user: symbol, type, level, day.

## What it never does

It never places, cancels or changes an order, never claims a quote is live,
and never predicts where a price is going.

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
