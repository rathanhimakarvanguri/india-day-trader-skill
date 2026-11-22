---
name: trader-analyst
description: >-
  Results Analyst for NSE-listed companies. Reads quarterly results as filed
  with NSE (the XBRL every listed company files under SEBI's LODR Regulation
  33) and sums up what changed: revenue from operations, operating profit and
  margin, profit before tax, net profit (owners' share) and margin, EPS, QoQ
  and YoY growth, the last four quarters, in Rs crore, with Indian fiscal
  quarters (Q2 FY27 = July to September 2026). Consolidated by default,
  standalone on request. Flags profit that leans on other income and profit
  that grew while revenue fell. Use when the user says "how were the
  results", "Q2 results of TCS", "what changed in the last quarter", "is
  revenue growing", "EPS", "profit growth", "read the results", "earnings
  analysis", or before trading a stock around its results day.
argument-hint: "[SYMBOL ...] [--quarters 6] [--standalone]"
---

# trader-analyst

The Results Analyst reads the numbers a company filed and lays them out side
by side, so the user can see what changed without opening a PDF. It reads
numbers only. It never says whether a stock is a buy.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/results.py" RELIANCE
python3 "${CLAUDE_SKILL_DIR}/results.py" TCS INFY --quarters 8
python3 "${CLAUDE_SKILL_DIR}/results.py" HDFCBANK --standalone
python3 "${CLAUDE_SKILL_DIR}/results.py" RELIANCE TCS --metrics trader/metrics.json
python3 "${CLAUDE_SKILL_DIR}/results.py" --xbrl saved-results.xml      # one saved XBRL file
python3 "${CLAUDE_SKILL_DIR}/results.py" RELIANCE --json
```

## What it reads and writes

| source | what |
| --- | --- |
| NSE results list | `www.nseindia.com/api/corporates-financial-results?index=equities&symbol=<SYM>&period=Quarterly`: each filing's period, consolidated or standalone, audited or not, filing date and XBRL link |
| each XBRL file | `nsearchives.nseindia.com/corporate/xbrl/...`: the filed numbers, by Ind AS concept name |
| `trader/metrics.json` | with `--metrics`: one row per symbol (TTM revenue and profit in crore, EPS, growth, margins) |

NSE's site often turns scripts away (HTTP 403, even on its home page). With
`--source auto` (the default) the tool then reads **Yahoo Finance's quarterly
financials** instead (`query2.finance.yahoo.com/ws/fundamentals-timeseries`,
`SYMBOL.NS`): consolidated revenue, operating income, profit before tax, net
profit to shareholders and EPS for the last 5 to 8 quarters, and says so in a
note. Yahoo's operating income is its own line item, not the NSE formula
below. `--source nse` insists on the filings; `--source yahoo` skips NSE.

For the filed XBRL itself when NSE blocks the script: open nseindia.com >
Corporate filings > Financial results in a browser (Claude in Chrome can do
it and save the JSON), save the list as `results-<SYMBOL>.json` and the XBRL
files, and run with `--offline DIR`, or read one file with `--xbrl`.

## The rules

- **One filing per quarter end.** Consolidated by default; standalone with
  `--standalone`. A revision filed later wins.
- **Only the quarter's own figures.** A results XBRL also holds year-to-date
  numbers and segment numbers; the tool keeps only the company-total facts
  whose period is about three months ending on that quarter end.
- **Concepts:** RevenueFromOperations, OtherIncome, FinanceCosts,
  DepreciationDepletionAndAmortisationExpense, ProfitBeforeTax,
  ProfitLossForPeriod (or the owners' share,
  ProfitOrLossAttributableToOwnersOfParent), basic and diluted EPS.
- **Operating profit** = profit before tax + finance costs - other income (an
  EBIT-style figure). Banks and NBFCs file a different schedule: revenue may
  be interest earned and operating profit may be blank. Say so.
- **Fiscal quarters.** India's fiscal year runs April to March: the quarter
  ending 30 Sep 2026 is Q2 FY27.
- Figures print in Rs crore (1 crore = 1,00,00,000 = 10 million). EPS in rupees.

## Steps

1. Run it on the symbol the user asks about.
2. Read back the latest quarter's line under "What changed", then the trend
   (revenue and profit YoY over the quarters shown), then any warning lines.
3. If results are due soon (trader-news shows the board-meeting notice), say
   that a day trade on results day carries gap risk.
4. Never turn the numbers into a buy or sell call.

## Example (the test fixtures)

DEMOCO, a made-up company with eight synthetic quarterly filings:

```
quarter  ended         revenue  rev yoy  op profit  op mgn net profit  net yoy net mgn      EPS  EPS yoy
Q2 FY27  2026-09-30     24,597   +12.6%      2,706   11.0%      2,164   +11.2%    8.8%    21.64   +11.1%
Q1 FY27  2026-06-30     23,881   +12.6%      2,627   11.0%      2,107   +11.1%    8.8%    21.07   +11.1%
...
What changed:
  - Q2 FY27 (quarter ended 2026-09-30): revenue Rs 24,597 cr (+12.6% YoY, +3.0% QoQ), net profit Rs 2,164 cr (+11.2% YoY), EPS Rs 21.64 (+11.1% YoY).
  - Other income is 30% of profit before tax: a big part of the profit is not from the business itself ...
```

## What it never does

It never places or sizes an order, never estimates future results, never
values a company, and never calls a stock cheap or expensive.

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
