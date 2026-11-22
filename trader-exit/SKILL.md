---
name: trader-exit
description: >-
  Exit Planner for NSE day trades. Sets your stop and your target before you
  enter, so you know when to get out. Reads the entry from trader-entry (or a
  price you give), puts the stop at the opening-range midpoint by default (or
  the range low, your price, a percent, or a multiple of the ATR), rounds it
  DOWN to NSE's tick size for that price band, and sets the target at 2R (or
  1R, or your price). Refuses a stop at or above the entry, a target at or
  below it, or a stop too tight to survive the spread. Flat by 3:10 PM IST by
  default, before the broker's intraday auto square-off. Writes
  trader/plan.json for the Time Machine, the Budget Manager and Price Alerts.
  Long side only. Use when the user says "where's my stop", "set my stop and
  target", "plan the exit", "stop loss", "what's my R", "risk reward", or
  right after /trader-entry triggers, before /trader-timemachine.
argument-hint: "[--stop or-mid|or-low|price:X|pct:X|atr:K] [--target 2R|1R|price:X]"
---

# trader-exit

The Exit Planner decides how a trade ends before it starts. The stop is where
the setup has failed. The target is where you take what you came for. Both
are set BEFORE the entry, written down and handed on, so nobody has to decide
anything in the middle of a fast move. A stop is a plan, not a guarantee: a
gap or a fast market can fill past it.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan                          # trader/entry.json: midpoint stop, 2R target
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop or-mid --target 1R --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop atr:1.5           # needs the session's bars (Yahoo or --offline)
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol RELIANCE --entry 1512.40 --or-high 1508.90 --or-low 1494.10
python3 "${CLAUDE_SKILL_DIR}/exit.py" show                          # the current trader/plan.json
```

Other flags: `--flat-by 15:10`, `--tick 0.05` (override the tick), `--json`,
`--now "2026-11-13 10:00"` (India time), `--setup level`, `--offline FILE`.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/entry.json` | the trigger from trader-entry: symbol, entry price, time, bar, opening range |
| `trader/config.json` | `flat_by` (15:10) and `min_reward_risk` (1.0: a note here, trader-risk enforces it) |
| `trader/plan.json` | with `--write`: entry, stop and its rule, target and its R, risk a share, reward:risk, tick, flat by |

## Stops and targets

| stop | where it goes |
| --- | --- |
| `or-mid` | the opening-range midpoint (the default for an opening-range breakout) |
| `or-low` | the opening-range low: wider, so fewer shares for the same max loss |
| `price:X` | your price |
| `pct:X` | X percent under the entry |
| `atr:K` | K times the 14-bar ATR under the entry, on the session's bars up to the entry bar |

- **NSE tick sizes.** Prices move in ticks that grow with the price band
  (NSE circular CMTR67133, from April 15 2025): under Rs 250 a tick is
  Rs 0.01; Rs 250 to 1,000 is Rs 0.05; to 5,000 Rs 0.10; to 10,000 Rs 0.50;
  to 20,000 Rs 1; above that Rs 5. The stop rounds DOWN to the tick (away from
  the entry); the target rounds half up to the tick. NSE resets each stock's
  tick monthly from its month-end close, so `--tick` overrides it when a
  stock sits near a band edge. A price off the tick grid is rejected by Kite.
- **Refused, with the reason.** A stop at or above the entry. A target at or
  below it. A risk under 0.05% of the price. An entry.json that has not
  triggered (unless you give `--entry`). A short.
- **Flat by.** 15:10 IST by default. Zerodha squares off open intraday (MIS)
  positions itself from about 3:20 PM, at market, and charges for it. Out by
  then, win or lose: no overnight hold.

## Steps

1. Run it right after `/trader-entry` triggers (or plan ahead with `--entry`).
2. Use the default stop for an opening-range breakout unless the user names
   another. A level setup needs one: ask.
3. `exit.py plan --write`. Read back the entry, the stop and its rule, the
   target and its rule, the risk a share, reward:risk and flat by.
4. Hand on to `/trader-timemachine`, then `/trader-budget`.

## Example (the test fixtures)

```
Exit plan: DEMOCO long, Fri 2026-11-13, opening-range breakout on 5-minute bars
  Entry         Rs 1,512.40 at 10:00 AM (bar 8)
  Stop          Rs 1,501.50  opening-range midpoint: (Rs 1,508.90 + Rs 1,494.10) / 2 = Rs 1501.5
  Target        Rs 1,534.20  2R (two times the risk)
  Risk a share  Rs 10.90 (0.72% of the entry)
  Reward:risk   2.0
  Flat by       15:10 IST, win or lose: no overnight hold
```

The entry is above Rs 1,000, so the tick is Rs 0.10: a midpoint of 1501.515
becomes 1501.50, and 1512.40 + 2 x 10.90 = 1534.20 is already on the grid.

## Rules

- Set before the entry. Never move a stop further away once in.
- Say the risk a share in rupees and as a percent.
- Never print a profit figure; reward:risk is a ratio, not a promise.

## What it never does

It never places an order, never sizes a position, never places the stop at
the broker (trader-broker does, after your yes), and never plans a short.

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
