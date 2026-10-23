#!/bin/sh
# tools/quickstart.sh <framework>: from a clean checkout to a first conformance result for one framework quickstart.
#
#   sh tools/quickstart.sh express|hono|next|fastapi|flask|go
#
# It builds the probe if ts/dist is missing, installs the quickstart's pinned dependencies under examples/<framework>/,
# starts the quickstart on a free port behind the facilitator double, runs R0-R10 against its paid route and writes
# examples/<framework>/quickstart-result.json. It exits 0 only when the probe ran, every check passed and the whole
# run took under 300 s; it prints the elapsed seconds either way. Nothing leaves loopback.
set -eu
fw=${1:-}
case "$fw" in
  express|hono|next|fastapi|flask|go) ;;
  *) echo "usage: sh tools/quickstart.sh express|hono|next|fastapi|flask|go" >&2; exit 2 ;;
esac
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
t0=$(date +%s)
say() { echo "quickstart $fw: $*"; }
if [ ! -f ts/dist/src/cli.js ]; then
  say "building the probe (ts/dist is missing)"
  (cd ts && npm ci --no-audit --no-fund --silent && npx tsc -p .)
fi
dir=examples/$fw
route=paid
port=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
case "$fw" in
  express|hono)
    say "npm ci in $dir"
    (cd "$dir" && npm ci --no-audit --no-fund --silent)
    start="PORT=$port node $dir/server.mjs" ;;
  next)
    say "npm ci in $dir"
    (cd "$dir" && npm ci --no-audit --no-fund --silent)
    route=api/paid
    start="cd $dir && npx next dev -p $port -H 127.0.0.1" ;;
  fastapi|flask)
    say "venv and pip install in $dir"
    python3 -m venv "$dir/.venv"
    "$dir/.venv/bin/pip" install -q --disable-pip-version-check -r "$dir/requirements.txt"
    start="PORT=$port $dir/.venv/bin/python $dir/server.py" ;;
  go)
    say "go build in $dir"
    (cd "$dir" && go build -o quickstart-server .)
    start="PORT=$port $dir/quickstart-server" ;;
esac
say "installed in $(( $(date +%s) - t0 )) s; probing http://127.0.0.1:$port/$route"
out=$dir/quickstart-result.json
log=$dir/quickstart-probe.log
rc=0
node ts/dist/src/cli.js probe --resource "http://127.0.0.1:$port/$route" --port 0 --start "$start" --out "$out" >"$log" 2>&1 || rc=$?
elapsed=$(( $(date +%s) - t0 ))
[ "$rc" = 0 ] || { say "the probe exited $rc; its last lines:"; tail -n 8 "$log"; }
# The result must exist, every check must have passed, and the run must have fit the budget.
python3 - "$out" "$rc" "$elapsed" "$fw" <<'EOF'
import json, sys
out, rc, elapsed, fw = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
try:
    d = json.load(open(out))
except Exception as e:  # noqa: BLE001  no result file is a failed quickstart
    print(f"quickstart {fw}: no result ({e}); probe exit {rc}; {elapsed} s")
    sys.exit(1)
results = d.get("results") or []
failed = [r.get("check", "?").split(" ")[0] for r in results if not r.get("pass")]
ran = len(results) >= 11
ok = rc == 0 and ran and not failed and elapsed < 300
print(f"quickstart {fw}: {'pass' if ok else 'FAIL'}: {len(results)} checks, failed {failed or 'none'}, probe exit {rc}, {elapsed} s"
      + ("" if elapsed < 300 else " (over the 300 s budget)") + ("" if ran else " (the probe did not run R0-R10)"))
sys.exit(0 if ok else 1)
EOF
