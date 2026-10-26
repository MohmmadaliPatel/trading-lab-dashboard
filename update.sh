#!/usr/bin/env bash
# Rebuild the dashboard data from the bots' shared files, scan for secrets, commit+push if changed.
# Usage: /workspace/trading-lab-dashboard/update.sh            (build + scan + commit + push)
#        /workspace/trading-lab-dashboard/update.sh --no-push  (build + scan only)
set -euo pipefail
cd "$(dirname "$0")"
export TZ=Asia/Kolkata

python3 build_site.py

# ---- secret scan over everything that would be published (abort on any hit) ----
PUB=()
for f in index.html app.js style.css data README.md; do [ -e "$f" ] && PUB+=("$f"); done
command -v rg >/dev/null || { echo "ABORT: ripgrep (rg) is required for the secret scan" >&2; exit 3; }
fail=0
scan() {  # $1 = description, rest = rg args
  local desc="$1"; shift
  local rc=0
  rg -n --no-heading "$@" "${PUB[@]}" >/tmp/tld_scan.txt 2>/tmp/tld_scan.err || rc=$?
  if [ "$rc" -ge 2 ]; then echo "SCAN ERROR ($desc): $(head -2 /tmp/tld_scan.err)"; fail=1; fi
  if [ -s /tmp/tld_scan.txt ]; then
    echo "SECRET SCAN HIT ($desc):"; head -5 /tmp/tld_scan.txt | cut -c1-200; fail=1
  fi
}
scan "JWT-like"        -e 'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}'
scan "GitHub/API token" -e '(gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})'
# GROWW is also an NSE ticker symbol; only the exact quoted value "GROWW" is allowed.
scan "GROWW"           -P -e '(?<!")GROWW|GROWW(?!")'
scan "TOTP"            -e 'TOTP'
scan "secret"          -i -e 'secret'
scan "token"           -i -e 'token'
scan "gmail"           -i -e '@gmail'
scan "email address"   -e '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.(com|in|org|net|io|co)\b'
scan "phone number"    -P -e '(?<![\d/._A-Za-z])(\+91[\s-]?)?[6-9]\d{9}(?![\d])'
scan "private info"    -i -e '(api[_-]?key|password|passwd|\.env\b|account[_ ]?id|client[_ ]?id)'
[ -s private_terms.txt ] && scan "private term" -i -F -f private_terms.txt
if [ "$fail" = 1 ]; then
  echo "ABORT: secret scan failed. Nothing committed or pushed." >&2
  exit 2
fi
echo "secret scan: clean"

[ "${1:-}" = "--no-push" ] && { echo "build ok (--no-push)"; exit 0; }

# Ignore a rebuild whose only change is the "last updated" timestamp in data/meta.json
if git diff --quiet HEAD -- . ':(exclude)data/meta.json' 2>/dev/null && [ -z "$(git ls-files --others --exclude-standard)" ] \
   && ! git diff -U0 HEAD -- data/meta.json | grep -E '^[+-] ' | grep -vqE '"updated_(ist|iso)"'; then
  git checkout -q -- data/meta.json 2>/dev/null || true
  echo "no changes (only timestamp); nothing to push"
  exit 0
fi

git add -A index.html app.js style.css data README.md build_site.py update.sh .gitignore .nojekyll vercel.json .vercelignore
if git diff --cached --quiet; then
  echo "no changes; nothing to push"
  exit 0
fi
git commit -q -m "Update dashboard data $(date '+%Y-%m-%d %H:%M IST')"
git push -q origin main
echo "pushed: $(git log -1 --format=%s)"
