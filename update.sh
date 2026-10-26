#!/usr/bin/env bash
# Rebuild the dashboard data from the bots' shared files, scan for secrets, commit+push if changed.
# Usage: /workspace/trading-lab-dashboard/update.sh            (build + scan + commit + push)
#        /workspace/trading-lab-dashboard/update.sh --no-push  (build + scan only)
set -euo pipefail
cd "$(dirname "$0")"
export TZ=Asia/Kolkata

python3 build_site.py

# ---- secret scan over everything that would be published (abort on any hit) ----
./scan.sh index.html app.js style.css data README.md vercel.json || exit $?

[ "${1:-}" = "--no-push" ] && { echo "build ok (--no-push)"; exit 0; }

# Ignore a rebuild whose only change is the "last updated" timestamp in data/meta.json
meta_same() {  # true if data/meta.json differs from HEAD only in its timestamp fields
  python3 - <<'PY'
import json, subprocess, sys
try:
    old = json.loads(subprocess.run(["git", "show", "HEAD:data/meta.json"], capture_output=True, text=True, check=True).stdout)
    new = json.load(open("data/meta.json"))
except Exception:
    sys.exit(1)
for d in (old, new):
    d.pop("updated_ist", None); d.pop("updated_iso", None)
sys.exit(0 if old == new else 1)
PY
}
if git diff --quiet HEAD -- . ':(exclude)data/meta.json' ':(exclude)data/lab.json' 2>/dev/null && [ -z "$(git ls-files --others --exclude-standard)" ] && meta_same; then
  git checkout -q -- data/meta.json data/lab.json 2>/dev/null || true
  echo "no changes (only timestamp); nothing to push"
  exit 0
fi

git add -A index.html app.js style.css data README.md build_site.py update.sh .gitignore .nojekyll vercel.json .vercelignore scan.sh build_lab.py live_push.sh
if git diff --cached --quiet; then
  echo "no changes; nothing to push"
  exit 0
fi
git commit -q -m "Update dashboard data $(date '+%Y-%m-%d %H:%M IST')"
git push -q origin main
echo "pushed: $(git log -1 --format=%s)"
