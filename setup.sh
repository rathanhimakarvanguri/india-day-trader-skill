#!/usr/bin/env bash
# One-time setup for the India Day Trader skill pack (macOS or Linux).
#   bash setup.sh            # check Python, run the tests, install the skills, make trader/config.json
#   bash setup.sh --no-data  # the same, without downloading the Nifty 500 list
# Safe to run again: it never overwrites your trader/config.json.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
SKILLS="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"

say() { printf '\n== %s\n' "$*"; }

say "1/5 Python"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install it (macOS: xcode-select --install, or python.org) and run this again."
  exit 1
fi
python3 - <<'PY'
import sys
if sys.version_info < (3, 8):
    sys.exit("Python %d.%d is too old: this pack needs 3.8 or newer." % sys.version_info[:2])
print("Python %d.%d.%d: OK" % sys.version_info[:3])
PY

say "2/5 Tests (offline, synthetic data)"
python3 -m unittest discover -s tests 2>&1 | tail -3

say "3/5 Install the 11 skills into $SKILLS"
mkdir -p "$SKILLS"
for d in trader-*; do
  rm -rf "${SKILLS:?}/$d"
  cp -R "$d" "$SKILLS/$d"
  echo "  /$d"
done

say "4/5 Your rules: trader/config.json"
mkdir -p trader
if [ -f trader/config.json ]; then
  echo "  trader/config.json already exists: left as it is."
else
  cp trader-budget/config.example.json trader/config.json
  echo "  Wrote trader/config.json from the example: budget Rs 1,00,000, max loss Rs 500 a trade,"
  echo "  Rs 1,500 a day, 3 trades a day, flat by 15:10, paper true. Edit it to your own numbers."
fi

say "5/5 Market data check"
if [ "${1:-}" = "--no-data" ]; then
  echo "  skipped (--no-data)"
else
  python3 trader-scanner/scan.py universe || echo "  NSE did not answer: run 'python3 trader-scanner/scan.py universe' later."
  python3 trader-alerts/alerts.py clock || true
fi

cat <<EOF

Done. In Claude Code, open this folder ($HERE) and try:
  /trader-alerts clock          is NSE open?
  /trader-scanner               build the watchlist
  /trader-news RELIANCE         headlines and filings
Paper trading is on ("paper": true). Nothing is ever sent to Zerodha without your yes.
EOF
