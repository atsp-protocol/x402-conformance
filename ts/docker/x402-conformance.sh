#!/bin/sh
# Entry point of the x402-conformance image. One image, every entry point:
#   (no arguments)        the MCP server on stdio (what the MCP registry runs)
#   x402conf ...          the Python CLI: live, resource, offline, report
#   x402conf-svm ...      the Node CLI: probe (R0-R10), resource (P1-P7)
#   x402-conformance-mcp  the MCP server on stdio
#   ci                    a CI run configured from the environment (GitLab, Jenkins, CircleCI, Buildkite ...):
#       X402_RESOURCE_URL  your paid route on loopback, probed R0-R10 through the facilitator double
#       X402_START         command that starts your server; it gets X402_FACILITATOR_URL
#       X402_RESOURCES     space-separated paid URLs already answering (staging, say), whose 402 answer is
#                          checked (P1-P7), one unpaid GET each; checked before X402_START runs
#       X402_NETWORK       auto (default), solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1 or eip155:84532
#       X402_PORT          loopback port for the double (default 4402)
#       X402_RESULTS_DIR   where results, junit.xml and x402-conformance.sarif go (default x402-conformance)
#       X402_SHARE         "true" writes anonymised corpus cases for failures and prints the links; nothing is sent
#   help                  this text
set -eu
case "${1:-}" in
  "") exec x402-conformance-mcp ;;
  help|--help|-h) sed -n '2,/^set -eu/p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'; exit 0 ;;
  ci) ;;
  *) exec "$@" ;;
esac

dir="${X402_RESULTS_DIR:-x402-conformance}"
mkdir -p "$dir"
share=""
[ "${X402_SHARE:-false}" = "true" ] && share="--share"
ran=0
rc=0
if [ -n "${X402_RESOURCES:-}" ]; then
  ran=1
  # shellcheck disable=SC2086
  (cd "$dir" && x402conf resource $X402_RESOURCES --fail-on-error $share > resource-402.json) || rc=1
fi
if [ -n "${X402_RESOURCE_URL:-}" ]; then
  ran=1
  set -- probe --resource "$X402_RESOURCE_URL" --port "${X402_PORT:-4402}" --network "${X402_NETWORK:-auto}" \
    --out "$dir/resource-server.json"
  [ -n "${X402_START:-}" ] && set -- "$@" --start "$X402_START"
  [ -n "$share" ] && set -- "$@" --share
  x402conf-svm "$@" > /dev/null || rc=1
fi
if [ "$ran" = 0 ]; then
  echo "x402-conformance ci: nothing to check; set X402_RESOURCE_URL (and X402_START) or X402_RESOURCES" >&2
  exit 2
fi
x402conf report --dir "$dir" --junit "$dir/junit.xml" --sarif "$dir/x402-conformance.sarif" --fail-on-error || rc=1
exit "$rc"
