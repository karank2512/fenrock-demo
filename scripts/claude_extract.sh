#!/usr/bin/env bash
# Preset extractor command for the Claude Code CLI, signed in by its owner with their own plan.
# Adapted from the po-intake preset (same safety properties, complaint schema).
# Usage: FENROCK_LLM_CMD="$PWD/scripts/claude_extract.sh" python3 -m complaint_triage.run --fields-mode llm ...
#
#  - Provider, key and model override variables are removed so the call uses the existing plan login only.
#    Do NOT add --bare: it skips the plan login and expects an API key.
#  - --restricted (for harnesses that must not run commands or read user/project settings) plus --tools ""
#    (no built-in tools) plus --strict-mcp-config with no MCP file, --disable-slash-commands and
#    --no-session-persistence.
#  - Runs in an empty temp dir. A schema forces one JSON record. Nothing in a document can reach files,
#    commands or the network.
#  - Needs a Claude Code version that supports --restricted. If any flag is rejected the script fails
#    loudly. It never retries without it.
set -euo pipefail
# Binary: default to the CLI on PATH; set FENROCK_CLAUDE_BIN to an absolute path when PATH
# is not populated (e.g. a transient launchd context). This changes no auth, only discovery.
CLAUDE_BIN="${FENROCK_CLAUDE_BIN:-claude}"
PROMPT="$(cat)"
WORK="$(mktemp -d)"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT
cd "$WORK"
SCHEMA='{"type":"object","properties":{"customer_name":{"type":"string"},"account_reference":{"type":"string"},"product":{"type":"string"},"amount":{"type":["number","null"]},"date":{"type":"string"},"customer_ask":{"type":"string"},"summary":{"type":"string"}},"required":["customer_name","account_reference","product","amount","date","customer_ask","summary"]}'
# Auth: the plan login reaches the CLI from its own logged-in config or from CLAUDE_CODE_OAUTH_TOKEN set by
# its owner for this one call. The token is passed through untouched and never printed, logged or created here.
# Scrub every env var that can redirect auth, provider, endpoint or model. Values are never printed.
SCRUB=()
while IFS='=' read -r name _; do
  case "$name" in
    ANTHROPIC_*|CLAUDE_CODE_USE_*|CLAUDE_CODE_API_KEY_HELPER*|CLAUDE_CONFIG_DIR_OVERRIDE|AWS_BEARER_TOKEN_BEDROCK|VERTEX_*|CLOUD_ML_REGION) SCRUB+=(-u "$name");;
  esac
done < <(env)
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && ! "$CLAUDE_BIN" auth status >/dev/null 2>&1; then
  echo "claude_extract.sh: no Claude login available (not logged in, CLAUDE_CODE_OAUTH_TOKEN not set). Refusing to run." >&2; exit 3
fi
env ${SCRUB[@]+"${SCRUB[@]}"} "$CLAUDE_BIN" -p "$PROMPT" \
  --restricted --tools "" --strict-mcp-config --disable-slash-commands \
  --output-format json --json-schema "$SCHEMA" \
  --max-turns 3 --no-session-persistence \
  ${FENROCK_CLAUDE_MODEL:+--model "$FENROCK_CLAUDE_MODEL"}
