---
name: trader-budget
description: >-
  Budget Manager for NSE day trades. Sizes every position to your budget and
  your max loss per trade, in rupees and whole shares. Reads the plan from
  trader-exit (entry, stop, target), takes the smallest of four limits (max
  loss at the stop, position cap, max order, cash after the buffer), never
  uses MIS leverage unless you allow margin, estimates the round trip's
  charges at Zerodha's rates (brokerage, STT, exchange, SEBI, stamp duty,
  GST), and writes one bracket order to trader/orders.json: a LIMIT buy
  (product MIS), then an SL-M stop-loss and a LIMIT target once it fills.
  Refuses a trade whose stop is too far for your max loss. Use when the user
  says "how many shares", "size this trade", "position size", "how much can
  I risk", "set my budget", "what's my max loss", or after /trader-timemachine,
  before /trader-risk.
argument-hint: "[--budget RUPEES] [--limit PRICE | --market]"
---

# trader-budget

The Budget Manager turns a plan into a number of shares. The stop decides
the risk a share; your max loss per trade decides how many shares that risk
allows. Everything else (the position cap, the max order and your cash) can
only make it smaller. It never sends anything: trader-risk checks the order
and trader-broker asks you yes or no.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                          # trader/plan.json + trader/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write                  # write trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --budget 100000 --write  # override the budget (rupees)
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit 1512.00          # a LIMIT entry at your price
python3 "${CLAUDE_SKILL_DIR}/size.py" --market                 # a MARKET entry instead
python3 "${CLAUDE_SKILL_DIR}/size.py" --json
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | from trader-exit: symbol, date, entry, stop, target, flat by |
| `trader/config.json` | your rules (copy `config.example.json` from this folder) |
| `trader/portfolio.json` | if it exists, its cash caps the size |
| `trader/prices.json` | with `--market`: a fresh price above the plan's entry sizes the trade at that price |
| `trader/orders.json` | with `--write`: one proposed bracket order |

## Step 1: set the rules once

Copy `config.example.json` to `trader/config.json` and ask the user for their
numbers. The defaults are a Rs 1,00,000 budget, Rs 500 max loss per trade
(0.5 % of the budget), Rs 1,500 max daily loss, 3 trades a day, Rs 50,000 max
order, entries 09:30 to 14:45 IST, flat by 15:10, product MIS, paper true.
Ask; never guess a budget.

## Step 2: size the trade

```
shares = floor of the smallest of
  max loss       max_loss_per_trade_inr / risk per share (entry minus stop)
  position cap   budget x max_position_pct / entry
  max order      max_order_inr / entry
  cash           (budget minus the cash buffer) / entry   (and no more than portfolio cash)
```

- **Whole shares** only: NSE has no fractional shares.
- **No leverage.** Zerodha lends up to about 5x on intraday (MIS) positions.
  This pack sizes against your own cash; leverage multiplies losses as fast
  as gains, and SEBI's peak-margin rules can change what the broker allows
  mid-day.
- **LIMIT entries by default**, at the plan's entry. A market order can fill
  well past the price, and brokers wrap API market orders in "market
  protection" under NSE's 2026 algo rules anyway. `--market` if you want one.
- **Charges.** The report estimates the round trip's charges at the target
  and at the stop, and the all-in loss at the stop. On small trades the costs
  are a big share of the reward: trader-risk blocks a trade whose charges are
  over 25 % of its gross reward (`max_cost_pct_of_reward`).
- **Refused, with the reason:** zero shares (the stop is too far for your max
  loss), a reward:risk under `min_reward_risk`, an order under
  `min_order_inr`, a plan for another day, a symbol on your blocked list.

## Step 3: show the user

Read back the size, the binding limit, the cost, the max loss at the stop,
the charges, and the three Kite orders it becomes. Then hand it to
`/trader-risk`. Nothing has been placed.

## Example (the test fixtures)

```
Limits (whole shares; the smallest one wins):
  max loss      Rs 500 max loss / 10.90 risk a share                        45 shares
  position cap  75% of Rs 1,00,000 = Rs 75,000 / 1512.40                    49 shares
  max order     Rs 50,000 / 1512.40                                         33 shares  <- binds
  cash          budget Rs 1,00,000 minus the Rs 10,000 cash buffer = Rs 90,000 / 1512.40  59 shares

Size: 33 shares of DEMOCO = Rs 49,909.20 at 1512.40. Max loss at the stop: 33 x 10.90 = Rs 359.70.
Charges (Zerodha rates, MIS): about Rs 53.51 if it hits the target (7% of the Rs 719.40 gross reward), Rs 52.81 at the stop, so the loss at the stop is about Rs 412.51 all in.

Proposed bracket (nothing has been placed). On Kite it is three orders:
  1. BUY 33 DEMOCO, NSE, MIS, LIMIT 1512.40, DAY
  2. SELL 33 DEMOCO, SL-M trigger 1501.50 (the stop), once the buy fills
  3. SELL 33 DEMOCO, LIMIT 1534.20 (the target), once the buy fills
```

## Rules

- The stop decides the size. Never widen a stop to fit more shares.
- Say the binding limit and the max loss in rupees, every time.
- Never print a profit figure as a promise. The reward at the target is a
  "gross reward if it gets there", before charges.

## What it never does

It never places an order, never borrows (no MIS leverage, no margin) unless
the config allows it, and never sizes a trade without a stop.

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
