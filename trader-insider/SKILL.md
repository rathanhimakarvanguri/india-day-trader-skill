---
name: trader-insider
description: >-
  Insider and Big-Money Tracker for NSE stocks: the Indian stand-in for the US
  "Pelosi tracker". Reads the insider trading disclosures that promoters,
  promoter-group entities, directors and key managerial people must file
  under SEBI's PIT Regulations (Regulation 7(2): trades over Rs 10 lakh in a
  quarter, disclosed within 2 trading days), and NSE's daily bulk and block
  deals. Shows who bought or sold, how many shares, at about what price, the
  rupee value in lakh or crore, the holding before and after, how many days
  it took to disclose, a flag on promoters buying in the market, and which
  entries are not market bets (pledges, ESOPs, inter-se transfers). Alerts
  once per new filing. Use when the user says "are promoters buying",
  "insider trading in RELIANCE", "insider buying", "bulk deals today", "block
  deals", "who bought TATASTEEL", "promoter selling", "smart money", "track
  the Pelosi of India", or "run the insider skill".
argument-hint: "[pit | deals | new] [--symbols SYM,...] [--watchlist]"
---

# trader-insider

In the US, members of Congress file reports of their stock trades, and the
"Pelosi tracker" reads them. India has no per-trade filing for MPs. What it
does have are two public feeds that show who is buying and selling a listed
company's shares:

- **Insider trading disclosures** (SEBI Prohibition of Insider Trading
  Regulations, 2015). Promoters, the promoter group, directors, key
  managerial people and designated persons must tell the company within 2
  trading days when their trades in a calendar quarter go over Rs 10 lakh,
  and the company passes it to the exchange within 2 trading days.
- **Bulk and block deals.** A bulk deal is one client trading more than
  0.5 % of a company's listed shares in a day; a block deal is a large
  negotiated trade in the special block window. NSE lists both each evening.

It is fast. It is not early. A disclosure arrives days after the trade, and a
deal shows who traded, not why. There is no inside information here: only
public filings, read quickly. Say that every time.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/insider.py" pit --symbols RELIANCE,TCS            # last 30 days
python3 "${CLAUDE_SKILL_DIR}/insider.py" pit --watchlist --days 90 --buys --promoters
python3 "${CLAUDE_SKILL_DIR}/insider.py" pit --symbols INFY --market-only --min-value 1000000
python3 "${CLAUDE_SKILL_DIR}/insider.py" deals                                 # today's bulk and block deals
python3 "${CLAUDE_SKILL_DIR}/insider.py" deals --kind bulk --symbols TATASTEEL
python3 "${CLAUDE_SKILL_DIR}/insider.py" new --watchlist                       # only what is new
```

Flags: `--offline DIR` (reads `pit-<SYMBOL>.json`, `bulk.csv`, `block.csv`),
`--today YYYY-MM-DD`, `--show N`, `--json`. Exit 0 when something was found,
1 when nothing was, 2 on an error.

## What it reads and writes

| source | what |
| --- | --- |
| NSE PIT API | `www.nseindia.com/api/corporates-pit?index=equities&symbol=<SYM>&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY` |
| NSE deals CSV | `nsearchives.nseindia.com/content/equities/bulk.csv` and `block.csv` (the latest trading day) |
| `trader/watchlist.json`, `plan.json`, `portfolio.json` | the symbols for `--watchlist` |
| `trader/state/insider.json` | what `new` has shown (120 days), so each filing alerts once |

**Deals work from a script; insider filings often do not.** The bulk and
block files come from NSE's file archive (nsearchives.nseindia.com), which
answers scripts. The insider-trading API is on www.nseindia.com, which often
answers a script with HTTP 403. Then, with the user's OK:

1. Open the API link in the user's browser (Claude in Chrome, or the built-in
   browser): `https://www.nseindia.com/api/corporates-pit?index=equities&symbol=RELIANCE&from_date=24-08-2026&to_date=22-11-2026`
   (a browser that has visited nseindia.com gets the JSON).
2. Save the page text as `trader/nse/pit-RELIANCE.json`.
3. `insider.py pit --symbols RELIANCE --offline trader/nse`.

## Reading the deals

- **One trade, two lists.** A block trade that is also over 0.5 % of the
  company appears in both bulk.csv and block.csv: shown once, as
  `block+bulk`.
- **Round trips are set apart.** A client that bought and sold about the same
  number of shares (within 10 %) the same day is shown once, with the net,
  under "Round trips". These are usually market makers and high-frequency
  desks; on a busy day they are most of the list and say nothing about the
  stock. `--all` lists every row as NSE does.
- **One-sided deals come first**, biggest first: a client that only bought or
  only sold.

## Reading a disclosure

- **Promoter buying in the market** (a market purchase by a promoter or the
  promoter group) is flagged. It is the closest thing to a signal here, and it
  is still not a tip: promoters buy for many reasons, and disclose after.
- **Not a market bet**: pledges and their release, ESOP / ESOS allotments,
  gifts, inter-se transfers among promoters, transmission, bonus and rights
  shares. They are shown, marked, and left out of the net buy / sell line.
- A **pledge** by a promoter is a risk flag of its own: if the price falls,
  lenders can sell the pledged shares.
- **Days to disclose.** The rules allow 2 trading days to the company and 2
  more to the exchange, so much more than a week from the trade is unusual.
  Say so plainly, without accusing anyone.

## Steps

1. Ask which stocks, or use `--watchlist`.
2. Run `pit` (insider trades) and, for today's big trades, `deals`.
3. Read back, newest first: who, category, buy or sell, shares, value in lakh
   or crore, the date range, days to disclose. Then the net line per stock.
4. For a standing watch, run `new --watchlist` from a scheduled task: it shows
   each filing once.
5. Say every time that these are public filings read quickly, not inside
   information and not a reason to trade on their own.

## Example (the test fixtures, made-up people and funds)

```
DEMOCO     BUY  Demo Promoter Holdings Private Limited, Promoter Group (Market Purchase): buy 50,000 shares at about Rs 1512.40, Rs 7.56 cr, traded 2026-11-10 to 2026-11-11, holding 41.20% -> 41.21%, disclosed 2 days later  <- promoter buying in the market
DEMOCO     SELL A Demo Director, Director (Market Sale): sell 2,000 shares at about Rs 1505.00, Rs 30.1 lakh, traded 2026-11-05, disclosed 2 days later
DEMOCO: insiders bought Rs 7.56 cr and sold Rs 30.1 lakh in the market (net +Rs 7.26 cr).
```

## What it never does

It never places or sizes an order, never says anyone traded on inside
information, never guesses why someone traded, and never presents a filing
as a recommendation.

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
