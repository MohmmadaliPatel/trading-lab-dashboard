#!/usr/bin/env bash
# Publish ONLY the paper-lab JSON to the `live-data` branch (read by the page from raw.githubusercontent.com).
# Vercel does not deploy this branch (vercel.json), so lab updates cost no Vercel builds.
# Usage: /workspace/trading-lab-dashboard/live_push.sh            build lab.json, scan, push if changed
#        /workspace/trading-lab-dashboard/live_push.sh --no-push  build + scan only
# History: by default each change is one normal (fast-forward) commit on live-data.
#          LIVE_SQUASH=1 instead replaces the branch with a single commit (force-with-lease on live-data only).
set -euo pipefail
cd "$(dirname "$0")"
export TZ=Asia/Kolkata
BR=live-data
REMOTE=$(git remote get-url origin)
LIVE=.live
mkdir -p "$LIVE"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/data"
python3 build_lab.py "$TMP/data/lab.json"
./scan.sh "$TMP/data/lab.json" || exit $?
[ "${1:-}" = "--no-push" ] && { echo "lab build ok (--no-push)"; exit 0; }

# isolated checkout of the live-data branch (never touches the main working tree)
if [ ! -d "$LIVE/.git" ]; then git -C "$LIVE" init -q && git -C "$LIVE" remote add origin "$REMOTE"; fi
git -C "$LIVE" config user.name "$(git config user.name)"; git -C "$LIVE" config user.email "$(git config user.email)"
if git -C "$LIVE" fetch -q origin "$BR" 2>/dev/null; then
  git -C "$LIVE" checkout -q -B "$BR" FETCH_HEAD
  HAVE=1
else
  git -C "$LIVE" checkout -q --orphan "$BR" 2>/dev/null || true
  git -C "$LIVE" rm -rqf . 2>/dev/null || true
  HAVE=0
fi

# skip if only the as-of timestamp changed
if [ -f "$LIVE/data/lab.json" ] && python3 - "$LIVE/data/lab.json" "$TMP/data/lab.json" <<'PY'
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
for d in (a, b):
    d.pop("as_of_ist", None); d.pop("as_of_iso", None)
sys.exit(0 if a == b else 1)
PY
then echo "lab unchanged; nothing to push"; exit 0; fi

mkdir -p "$LIVE/data"; cp "$TMP/data/lab.json" "$LIVE/data/lab.json"
printf '# live-data\n\nAuto-generated paper-lab data for the Trading Lab dashboard (exploratory paper trading, not validation). Not deployed by Vercel. Written by live_push.sh.\n' > "$LIVE/README.md"
printf '{\n  "git": { "deploymentEnabled": false }\n}\n' > "$LIVE/vercel.json"   # belt and braces: this branch never deploys
git -C "$LIVE" add -A data/lab.json README.md vercel.json
MSG="Live lab data $(date '+%Y-%m-%d %H:%M IST')"
if [ "${LIVE_SQUASH:-0}" = 1 ] && [ "$HAVE" = 1 ]; then
  OLD=$(git -C "$LIVE" rev-parse HEAD)
  git -C "$LIVE" checkout -q --orphan tmp-squash && git -C "$LIVE" commit -q -m "$MSG"
  git -C "$LIVE" branch -q -M "$BR"
  git -C "$LIVE" push -q --force-with-lease="$BR:$OLD" origin "$BR"
else
  git -C "$LIVE" commit -q -m "$MSG"
  git -C "$LIVE" push -q origin "$BR"
fi
echo "pushed: $MSG"
