#!/usr/bin/env bash
# Switch and operate the live (gap-iq) and demo replay (gap-iq-demo) Fly apps.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIVE_APP="gap-iq"
DEMO_APP="gap-iq-demo"
DEMO_HOST="gap-iq-demo.navratils.org"
LIVE_URL="https://${LIVE_APP}.fly.dev"
DEMO_URL="https://${DEMO_HOST}"

usage() {
  cat <<EOF
Usage: $(basename "$0") <command> [options]

Commands:
  status [--app APP]     Show LIVE vs REPLAY from /api/meta (default: both apps)
  deploy-demo            Build and deploy the demo replay app (gap-iq-demo)
  setup-demo             Create demo app, request TLS cert, print DNS records
  reset [--app APP]      Restart machines — replay virtual clock starts over
  dns                    Show current certificate / DNS status for the demo host

Apps:
  live   → ${LIVE_APP} (${LIVE_URL})
  demo   → ${DEMO_APP} (${DEMO_URL})

Examples:
  $(basename "$0") setup-demo          # first-time demo app + custom domain
  $(basename "$0") deploy-demo         # ship code to gap-iq-demo
  $(basename "$0") reset               # restart demo replay from the gun
  $(basename "$0") status              # confirm both apps are in the right mode
EOF
}

require_fly() {
  if ! command -v fly >/dev/null 2>&1; then
    echo "fly CLI not found. Install: https://fly.io/docs/hands-on/install-flyctl/" >&2
    exit 1
  fi
}

app_url() {
  case "$1" in
    "$LIVE_APP" | live) echo "$LIVE_URL" ;;
    "$DEMO_APP" | demo) echo "$DEMO_URL" ;;
    *) echo "https://$1.fly.dev" ;;
  esac
}

normalize_app() {
  case "$1" in
    live) echo "$LIVE_APP" ;;
    demo) echo "$DEMO_APP" ;;
    *) echo "$1" ;;
  esac
}

fetch_meta() {
  local url="$1"
  curl -fsS "${url}/api/meta" 2>/dev/null
}

print_status() {
  local app="$1"
  local url
  url="$(app_url "$app")"
  echo "── ${app} (${url}) ──"
  if ! meta="$(fetch_meta "$url")"; then
    echo "  UNREACHABLE — is the app deployed?"
    echo
    return 1
  fi
  local mode provider label replay_line
  mode="$(echo "$meta" | python3 -c "import json,sys; print(json.load(sys.stdin).get('mode','?'))")"
  provider="$(echo "$meta" | python3 -c "import json,sys; print(json.load(sys.stdin)['event']['provider'])")"
  label="$(echo "$meta" | python3 -c "import json,sys; print(json.load(sys.stdin)['event']['label'])")"
  if [[ "$mode" == "replay" ]]; then
    replay_line="$(echo "$meta" | python3 -c "
import json, sys
body = json.load(sys.stdin)
r = body.get('replay') or {}
parts = [r.get('elapsed_text', '?'), f\"{r.get('speed', '?')}×\"]
if r.get('frozen'):
    parts.append('frozen')
rem = r.get('remaining_wall_seconds')
if rem is not None:
    parts.append(f'~{rem}s left')
print(' · '.join(parts))
")"
    echo "  MODE:   *** REPLAY ***  (provider=${provider})"
    echo "  EVENT:  ${label}"
    echo "  CLOCK:  ${replay_line}"
  else
    echo "  MODE:   LIVE  (provider=${provider})"
    echo "  EVENT:  ${label}"
  fi
  echo
}

cmd_status() {
  local app="${1:-}"
  if [[ -n "$app" ]]; then
    print_status "$(normalize_app "$app")"
    return
  fi
  print_status "$LIVE_APP" || true
  print_status "$DEMO_APP" || true
}

cmd_deploy_demo() {
  require_fly
  echo "Deploying demo replay app (${DEMO_APP})..."
  fly deploy -c "${ROOT}/fly.demo.toml" --app "$DEMO_APP" --ha=false
  fly scale count 1 -y --app "$DEMO_APP" >/dev/null
  echo
  cmd_status demo
}

cmd_setup_demo() {
  require_fly
  if ! fly apps list 2>/dev/null | awk '{print $1}' | grep -qx "$DEMO_APP"; then
    echo "Creating Fly app ${DEMO_APP}..."
    fly apps create "$DEMO_APP"
  else
    echo "Fly app ${DEMO_APP} already exists."
  fi

  echo
  echo "Requesting TLS certificate for ${DEMO_HOST}..."
  fly certs add "$DEMO_HOST" --app "$DEMO_APP" || fly certs show "$DEMO_HOST" --app "$DEMO_APP"

  echo
  echo "DNS setup for ${DEMO_HOST}:"
  echo "  Run 'fly certs setup ${DEMO_HOST} --app ${DEMO_APP}' if records are not shown above."
  echo "  Typical records (fly will print the exact values for your app):"
  echo "    A     gap-iq-demo  →  <Fly IPv4 from certs setup>"
  echo "    AAAA  gap-iq-demo  →  <Fly IPv6 from certs setup>"
  echo
  echo "After DNS propagates, deploy the demo app:"
  echo "  ./scripts/fly-mode.sh deploy-demo"
}

cmd_dns() {
  require_fly
  fly certs show "$DEMO_HOST" --app "$DEMO_APP"
}

cmd_reset() {
  require_fly
  local app
  app="$(normalize_app "${1:-demo}")"
  echo "Restarting ${app} — replay virtual clock will start from offset 0..."

  local machine_ids
  machine_ids="$(
    fly machines list -a "$app" -j | python3 -c "
import json, sys
ids = [m['id'] for m in json.load(sys.stdin) if m.get('state') == 'started']
print(' '.join(ids))
"
  )"

  if [[ -z "$machine_ids" ]]; then
    echo "No running machines — starting one..." >&2
    machine_ids="$(fly machines list -a "$app" -q | head -1)"
    fly machine start "$machine_ids" -a "$app"
  fi

  # shellcheck disable=SC2086
  fly machine restart $machine_ids -a "$app" --force
  echo "Done. Check status:"
  cmd_status "$app"
}

main() {
  local cmd="${1:-}"
  shift || true

  case "$cmd" in
    status)
      local app=""
      if [[ "${1:-}" == "--app" ]]; then
        shift
        app="${1:-}"
      fi
      cmd_status "$app"
      ;;
    deploy-demo) cmd_deploy_demo ;;
    setup-demo) cmd_setup_demo ;;
    dns) cmd_dns ;;
    reset)
      local app="demo"
      if [[ "${1:-}" == "--app" ]]; then
        shift
        app="${1:-demo}"
      fi
      cmd_reset "$app"
      ;;
    -h | --help | help | "") usage ;;
    *)
      echo "Unknown command: ${cmd}" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
