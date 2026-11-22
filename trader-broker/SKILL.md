---
name: trader-broker
description: >-
  Order Executor for Zerodha (Kite). Sends approved orders to your broker,
  paper trading by default, never without your yes. Shows each order as a
  plain ticket in rupees (a bracket shows its SL-M stop-loss, LIMIT target
  and the max loss at the stop) plus the exact arguments for the Kite MCP
  server's place_order tool (Kite Connect fields: exchange, tradingsymbol,
  transaction_type, quantity, product MIS, order_type, price,
  trigger_price), records your yes word for word, then Claude's own Allow
  once / Deny card asks again. Places the stop-loss and target after the buy
  fills and reminds you to cancel the other one when one fills (Kite does not
  link them). Builds the sell ticket that closes a day trade before the MIS
  auto square-off, records fills, and logs each trade's max loss for
  trader-risk. Covers setting up Zerodha's Kite MCP server, SEBI's static-IP
  rule, and "Needs approval". Use when the user says "place the order", "buy
  it", "execute", "send it to Zerodha", "close my position", "flatten", "get
  me out", "connect Kite", "set up paper trading", or after /trader-risk passes.
argument-hint: "[order number]"
---

# trader-broker

The Order Executor is the only skill in this pack that can lead to a real
order, so it is the strictest. An order reaches NSE only after three separate
gates, every time, for every order:

1. **trader-risk passed this exact order today** (matched by fingerprint).
2. **The user typed an explicit yes for this one order** in the chat.
3. **The user clicked Allow once** on Claude's own permission card, which
   appears because the Kite `place_order` tool is set to "Needs approval".

Two yeses from the user, one PASS from the rules. No yes, no order.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                     # every ticket, READY or not
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --broker-id 251113000123456 --filled-qty 33 --filled-price 1512.40
python3 "${CLAUDE_SKILL_DIR}/ticket.py" exits --index 1          # the SL-M stop and LIMIT target, after the fill
python3 "${CLAUDE_SKILL_DIR}/ticket.py" fill --symbol RELIANCE --side sell --qty 33 --price 1534.20
python3 "${CLAUDE_SKILL_DIR}/ticket.py" flatten --symbol RELIANCE --qty 33
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`ticket.py` never talks to a broker. It renders tickets, checks that a reply
is a real yes for that order, builds the exit and flatten tickets, and keeps
the log in `trader/state/broker.json`. `--now "2026-11-13 10:00"` pins the
clock (India time).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget writes it; `flatten` replaces it) |
| `trader/state/risk.json` | trader-risk's verdicts; only a PASS from today is READY |
| `trader/state/broker.json` | every yes, no, placed, failed and filled, with each entry's max loss |
| `trader/portfolio.json` | cash and shares, updated by `fill` and by `result --filled-qty` |
| `trader/plan.json` | the flat-by time and product for `flatten` |

## Paper mode (the default)

Zerodha has no paper-trading account. With `"paper": true` nothing is ever
sent: after the user's yes, Claude records a simulated fill with `ticket.py
result --status placed --filled-qty Q --filled-price P` (the plan's entry, or
the price trader-alerts shows), and trader-alerts watches the stop and target
in place of real orders. Use this for weeks before going live.

## Setup: Zerodha's Kite MCP server (live, optional)

Zerodha publishes an official MCP server, github.com/zerodha/kite-mcp-server
(MIT). Two ways to run it (also in `claude_desktop_config.example.json` here):

- **Hosted, read-only for orders.** `npx mcp-remote https://mcp.kite.trade/mcp`.
  Zerodha's hosted copy leaves out `place_order`, `modify_order` and
  `cancel_order`, so it can show positions, orders, margins and quotes but
  cannot trade. Good for paper mode: live quotes and a real view of the account.
- **Self-hosted, can trade.** The user builds the server on their own computer
  (`git clone https://github.com/zerodha/kite-mcp-server`, then `go build`),
  makes a Kite Connect app at developers.kite.trade for an API key and secret,
  and types them into the Claude Desktop config `env` block (`KITE_API_KEY`,
  `KITE_API_SECRET`, `"APP_MODE": "stdio"`). Check the current Kite Connect
  plans and fees on developers.kite.trade before signing up.

Then, in this order:

1. **Static IP (SEBI rule, from April 1, 2026).** Orders sent through any
   broker API are accepted only from a static IP the user registered on the
   Kite developer console (IP whitelist). A home connection usually needs a
   static IP from the ISP. Exchange rules allow one change a week. Without
   it, Kite rejects the order. Reading data does not need it.
2. **Log in every day.** A Kite access token expires each morning. The
   server's login tool gives a link; the user signs in on kite.zerodha.com in
   their own browser. **Never** ask for or type the Zerodha password, PIN,
   TOTP code, API secret or access token in the chat. If the user pastes one,
   tell them to delete that message and regenerate it.
3. **Tool permissions.** Customize > Connectors, open kite, and set:
   - `place_order`: **Needs approval**. Never Always allow.
   - `modify_order`, `cancel_order`: Needs approval.
   - GTT tools (`place_gtt_order` and friends): Blocked (the example config
     leaves them out); GTT does not cover intraday MIS orders.
   - read-only tools (`get_profile`, `get_margins`, `get_positions`,
     `get_holdings`, `get_orders`, `get_trades`, `get_quotes`, `get_ltp`):
     Always allow is fine.
   In Claude Code, keep order tools under `"ask"` in `.claude/settings.json`.
4. Check it: ask for the margins (read only) and confirm the account in the
   Kite app. Then, and only if the user says so, they set `"paper": false`.

## How a bracket works on Kite

Zerodha no longer offers bracket orders for equity, and GTT orders do not
cover intraday positions. So one bracket from trader-budget becomes three
Kite orders:

1. the entry: BUY, product MIS, LIMIT at the plan's entry, DAY;
2. after it fills, the stop-loss: SELL, SL-M with `trigger_price` at the stop;
3. and the target: SELL, LIMIT at the target.

Orders 2 and 3 do **not** cancel each other. When one fills, cancel the other
at once (`get_orders`, then `cancel_order` with its order_id), or a later fill
of the second sell leaves the user short. trader-alerts rings with that
reminder. The entry's yes covers 2 and 3 (they only reduce the position), but
each still goes through Claude's Allow once card.

## Steps: the entry

1. `ticket.py show`. Only READY tickets go to the user.
2. Show ONE ticket and ask: "Place this order? Reply yes or no." One order per
   question. Never offer "yes to all".
3. `ticket.py approve --index N --reply "<the user's reply, word for word>"`.
   "Not recorded" means the reply was not an explicit yes for this order. Ask
   again. Never turn a reply into a yes yourself.
4. Paper: record the simulated fill. Live: call `place_order` with exactly the
   arguments the ticket printed; Claude's card appears (Allow once / Deny).
5. Record what happened: `ticket.py result --index N --status placed
   --broker-id <Kite order_id> --filled-qty Q --filled-price P` (from
   `get_orders` / `get_trades`), or `--status denied`, or `--status failed`
   with `--note` (a static-IP rejection says so). A failed order is not
   retried without a new check and a new yes.
6. Once the buy has filled: `ticket.py exits --index N` and place the two
   exit orders it prints (live), or let trader-alerts watch them (paper).

## Steps: while it is open, and out by flat_by

- trader-alerts watches the stop, the target and the flat-by time.
- When the stop-loss or the target fills: cancel the other exit order, then
  `ticket.py fill --symbol SYM --side sell --qty Q --price P`.
- By `flat_by` (15:10 IST), anything still open gets closed, before Zerodha's
  own MIS auto square-off at about 3:20 PM (which fills at market and charges
  a fee):
  1. `get_positions` (read only) for the quantity.
  2. Cancel the open SL-M and LIMIT exits first (`cancel_order`, Needs approval).
  3. `ticket.py flatten --symbol SYM --qty Q` writes a market sell.
  4. `/trader-risk` (an exit is never blocked by the entry limits), then
     `ticket.py show` and the user's yes, as above.

## Example (the test fixtures, paper mode)

```
ORDER 1 of 1, PAPER (no real order: record a simulated fill), Zerodha Kite
  BUY 33 DEMOCO on NSE, MIS (intraday), limit 1512.40, good for today
  stop-loss 1501.50
  take-profit 1534.20
  max loss about Rs 359.70 if the stop fills at 1501.50 (it can fill worse in a fast market)
  READY: trader-risk PASS, waiting for your yes
  Once the buy fills, two exit orders (ticket.py exits --index 1):
    SELL 33 DEMOCO, stop-loss SL-M trigger 1501.50
    SELL 33 DEMOCO, target LIMIT 1534.20
  Kite does not link them: when one fills, cancel the other straight away.
```

Live, the entry's `place_order` arguments are:

```json
{"variety": "regular", "exchange": "NSE", "tradingsymbol": "DEMOCO", "quantity": 33, "product": "MIS",
 "validity": "DAY", "tag": "idts", "transaction_type": "BUY", "order_type": "LIMIT", "price": 1512.4}
```

## What it never does

- Never places an order without all three gates, and never two entries on one yes.
- Never places orders from a scheduled or background task: nobody is there to say yes.
- Never asks for, reads, stores or repeats API keys, secrets, tokens, passwords, PINs or TOTP codes.
- Never switches `"paper"` to false. The user does that themselves.
- Never places F&O, GTT, AMO or leveraged orders on its own.
- Never promises a fill price: a market order and an SL-M fill at whatever the market gives.

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
