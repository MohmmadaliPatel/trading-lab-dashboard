#!/usr/bin/env bash
# Secret scan shared by update.sh and live_push.sh. Usage: ./scan.sh FILE_OR_DIR...
# Exit 0 = clean, 2 = hit (nothing may be published), 3 = scanner missing.
set -uo pipefail
cd "$(dirname "$0")"
PUB=()
for f in "$@"; do [ -e "$f" ] && PUB+=("$f"); done
[ "${#PUB[@]}" -gt 0 ] || { echo "scan: nothing to scan"; exit 0; }
command -v rg >/dev/null || { echo "ABORT: ripgrep (rg) is required for the secret scan" >&2; exit 3; }
fail=0
TMP=$(mktemp); ERR=$(mktemp); trap 'rm -f "$TMP" "$ERR"' EXIT
scan() {  # $1 = description, rest = rg args
  local desc="$1"; shift
  local rc=0
  rg -n --no-heading "$@" "${PUB[@]}" >"$TMP" 2>"$ERR" || rc=$?
  if [ "$rc" -ge 2 ]; then echo "SCAN ERROR ($desc): $(head -2 "$ERR")"; fail=1; fi
  if [ -s "$TMP" ]; then
    echo "SECRET SCAN HIT ($desc):"; head -5 "$TMP" | cut -c1-200; fail=1
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
