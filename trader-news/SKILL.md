---
name: trader-news
description: >-
  News Monitor for NSE stocks. Tracks breaking news on every stock you watch
  and flags what moves it: Google News (India edition) and Yahoo Finance
  headlines per symbol, and each company's NSE corporate announcements (the
  filings listed companies must make under SEBI's LODR rules: results, board
  meetings, deals, resignations, credit ratings, pledges), tagged earnings,
  analyst, legal (SEBI, ED, NCLT), deal, capital, people, risk, regulatory
  (USFDA, RBI) and macro (RBI policy, FII flows, Budget, crude, rupee), with
  how far each stock has moved today. Shows only what is new since the last
  check, in IST. Use when the user says "any news on RELIANCE", "what's moving
  my stocks", "check the news", "why is this stock up", "any announcements",
  "did they file anything", "results date", or after /trader-scanner, before
  /trader-entry.
argument-hint: "[--tickers SYM ...] [--hours 48]"
---

# trader-news

The News Monitor answers one question before a trade: is something going on
with this stock today? It reads the headlines and the company's own NSE
filings for every symbol you watch or hold, tags what kind of news each item
is, and shows only what you have not seen. Headlines are leads, not facts:
open the story or the filing before acting.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                                  # watchlist + plan + portfolio
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE TCS INFY
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE --all --hours 72
python3 "${CLAUDE_SKILL_DIR}/news.py" --no-nse                         # headlines only
python3 "${CLAUDE_SKILL_DIR}/news.py" --json
```

Other flags: `--no-gnews`, `--no-moves`, `--move-pct 3`, `--offline DIR`,
`--now 2026-11-13T05:00:00Z`, `--dry-run` (do not update the seen list).
Exit code 0 when something new showed, 1 when nothing did.

## What it reads and writes

| source | what |
| --- | --- |
| Google News RSS (India) | `news.google.com/rss/search?q="<company name>" NSE when:2d&hl=en-IN&gl=IN` |
| Yahoo Finance RSS | `feeds.finance.yahoo.com/rss/2.0/headline?s=<SYMBOL>.NS&region=IN` |
| NSE announcements | `www.nseindia.com/api/corporate-announcements?index=equities&symbol=<SYMBOL>` (NSE sets cookies on its home page first; the tool visits it once) |
| Yahoo chart | today's move against yesterday's close |
| BSE announcements | when NSE turns the script away: `api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?...&strScrip=<BSE code>`; codes come from BSE's scrip list, saved in `trader/bse_codes.json` (edit it when a BSE id differs from the NSE symbol) |
| `trader/universe.txt` | company names from trader-scanner, so Google News searches "Demo Company" and not just "DEMOCO" |
| `trader/state/news.json` | what you have seen (30 days) |

## The rules

- **Important filings** (marked `!`): financial results, outcomes of board
  meetings, acquisitions and mergers, resignations, credit ratings, pledges,
  orders and contracts, penalties, searches, clarifications on news.
- **Tags** come from the words in the title and summary. A tag is a hint, not
  a reading of the story.
- **Results days move stocks.** If the company reports today or tomorrow (a
  "board meeting to consider financial results" filing), say so: a day trade
  is out before the close, but results usually come after 3:30 PM or during
  the session and can gap the price.
- **The move.** A stock 3 % or more from yesterday's close is flagged MOVING.
- **NSE often turns scripts away** (HTTP 403, even on its home page). Then
  the filings come from **BSE** instead: listed companies file the same
  disclosures with both exchanges. A note says so.
- **Only headlines that name the stock.** Google News matches loosely (a
  search for "TCS" brings back other companies and price-quote pages), so a
  headline is kept only if its title names the symbol or the company
  (`Tata Consultancy`, `(TCS)`, `NSE: TCS`). A note counts what was left out;
  `--loose` shows everything.

## Steps

1. Run it on the symbol the user is looking at, or with no arguments for the
   whole watchlist.
2. Tell the user the move and the new items, newest first, in IST. Lead with
   any `!` filing.
3. Never say a headline will move the price, and never say "buy on the news".
4. Hand on to `/trader-entry` (or `/trader-analyst` for results).

## Example (the test fixtures)

```
DEMOCO     Rs 1,500.90 +0.26% vs yesterday's close Rs 1,497.00 at 14:45 IST
  2026-11-13 09:40 IST  DEMOCO  GNews/Demo Markets   Brokerage upgrades Demo Company to buy, raises target price
      tags: analyst
! 2026-11-12 18:32 IST  DEMOCO  NSE filing           Demo Company Limited: Financial Result Updates
      tags: earnings
```

## What it never does

It never places or sizes an order, never calls a headline true, and never
says what a stock will do next.

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
