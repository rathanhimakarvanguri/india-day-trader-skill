---
name: trader-risk
description: >-
  Risk Manager for NSE day trades. Checks every proposed order against your
  limits and stops anything over them, in rupees and India time: max loss per
  trade at the stop, daily loss limit, trades and orders per day,
  reward:risk, the entry window (9:30 AM to 2:45 PM IST by default, closed on
  NSE holidays), the intraday square-off time, position size and cash (no MIS
  leverage unless you allow margin), whole-share qty, MIS or CNC product, no
  F&O unless allowed, and whether the round trip's charges (brokerage, STT,
  exchange, SEBI, stamp duty, GST at Zerodha's rates) eat too much of the
  reward. PASS or BLOCK with the reason, recorded so trader-broker only shows
  an order as ready if THIS exact order passed today. Use when the user says
  "check this trade", "is this within my limits", "risk check", "can I take
  this", "what's my max loss", "am I over my daily limit", or after
  /trader-budget, before /trader-broker.
argument-hint: "[--orders trader/orders.json]"
---

# trader-risk

The Risk Manager is the gate between a plan and an order. It does not have
opinions about the trade. It checks numbers against the limits you set when
you were calm, and blocks anything over them. A PASS is a rules check, not a
recommendation. SEBI's FY2023 study found that 7 in 10 individual intraday
traders in Indian equities lost money, and that for loss-makers, trading costs
added about 57% on top of their trading losses. The costs check is here for
that reason.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"                                # the trader/ files -> trader/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --now "2026-11-13 10:00"       # pin the clock (IST)
python3 "${CLAUDE_SKILL_DIR}/check.py" --orders trader/orders.json --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write                     # check without recording
```

Exit code 0 when every order passes, 1 when any is blocked. No network.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget, or trader-broker's flatten ticket) |
| `trader/config.json` | your limits, in rupees (see trader-budget's `config.example.json`) |
| `trader/portfolio.json` | cash and positions (missing: a fresh account funded with the budget) |
| `trader/prices.json` | prices from trader-alerts, used only if under 15 minutes old |
| `trader/state/broker.json` | what trader-broker placed today: trades, orders and loss already at risk |
| `trader/state/risk.json` | the verdicts, with a fingerprint of each exact order |

## Entries and exits

An ENTRY opens or adds to a position. An EXIT only reduces what you hold.
Getting out must always be possible: an exit is checked for format, asset and
short sales only; every other rule turns into a warning for it.

## The checks

| check | blocks when |
| --- | --- |
| format | no whole-share `qty` (NSE has no fractional shares, so no rupee notional orders), a limit order with no price, validity other than DAY / IOC, product other than MIS / CNC, exchange other than NSE / BSE, a bracket that misses its stop or target |
| asset | an F&O contract (`NIFTY24NOVFUT`, `...CE`, `...PE`) unless `"allow_options": true`; anything that is not an NSE / BSE cash symbol |
| short | selling more than you hold, unless `"allow_short": true` |
| blocked | a symbol on your `blocked` list |
| size | under `min_order_inr` (Rs 500), over `max_order_inr` (Rs 50,000) |
| position | the stock would be over `max_position_pct` (75 %) of the account |
| cash | the buy needs more than your cash, or dips into the `cash_buffer_pct` (10 %). Zerodha lends up to about 5x on MIS; that is margin, and it is off unless `"allow_margin": true` |
| stop | no stop while `"require_stop": true`, or a stop on the wrong side |
| loss | qty x (entry - stop) over `max_loss_per_trade_inr` (Rs 500) |
| reward:risk | under `min_reward_risk` (1.0) |
| costs | the round trip's charges at the target are over `max_cost_pct_of_reward` (25 %) of the gross reward |
| daily loss | today's entries' max losses plus this one over `max_daily_loss_inr` (Rs 1,500) |
| trades | `max_trades_per_day` (3) entries already placed today |
| window | before `no_entries_before` (09:30) or after `no_entries_after` (14:45) IST, or NSE is closed (weekend, holiday, outside 9:15 AM to 3:30 PM) |
| square-off | an MIS entry at or after `flat_by` (15:10): no time left before the broker's auto square-off at about 3:20 PM |
| duplicate / daily limit | the same symbol and side twice, or `max_orders_per_day` (10) reached |

**Charges** use Zerodha's published equity rates by default: brokerage 0.03%
or Rs 20 an executed order (whichever is lower) for intraday, Rs 0 for
delivery; STT 0.025% on the intraday sell side (0.1% both sides for
delivery); NSE transaction charge 0.00297%; SEBI Rs 10 a crore; stamp duty
0.003% on the intraday buy (0.015% delivery); GST 18% on brokerage, exchange
and SEBI charges. Rates change: check zerodha.com/charges and override any of
them under `"charges"` in the config.

There is no pattern-day-trader rule in India. A CNC order for a day trade
gets a warning: it is delivery, settled T+1, with 0.1% STT on both sides.

## Steps

1. Run `check.py` after `/trader-budget` writes `trader/orders.json`.
2. Tell the user each verdict in one line, with the reasons for a BLOCK
   exactly as printed, and the charges line.
3. A BLOCK goes back to the user: change the plan, the size or the rules. Do
   not edit the rules to make an order pass unless the user asks for that change.
4. A PASS goes to `/trader-broker`, which still asks the user yes or no.

## Example (the test fixtures)

```
PASS  #1 buy DEMOCO 33 shares, entry
          charges about Rs 53.51 if it hits the target, Rs 52.81 at the stop (Zerodha rates, MIS)
          entry 1512.40 (the limit price), stop 1501.50, target 1534.20: risk 10.90 a share
          max loss Rs 359.70 (limit Rs 500), reward:risk 2.00 (min 1)
          today before this: 0 of 3 trades, Rs 0 of Rs 1,500 daily loss
```

## Rules

- Never change the user's limits to make an order pass.
- Say a BLOCK plainly, with the number that broke the rule.
- A PASS is not advice to take the trade.

## What it never does

It never places, changes or cancels an order, never reaches the network, and
never passes an order it has not seen in full.

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
