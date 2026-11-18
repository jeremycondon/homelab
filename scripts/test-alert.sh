#!/usr/bin/env bash
# Send a test push to the ntfy topic used by Grafana alerts, with the same priority and tags as the real ones
# (services/grafana/provisioning/alerting/contact-points.yml). Goes straight to ntfy, so it doesn't exercise Grafana.
#   scripts/test-alert.sh <critical|warning> [message]
set -euo pipefail

usage() { echo "usage: $0 <critical|warning> [message]" >&2; exit 2; }

[[ $# -ge 1 ]] || usage
severity=$1
shift
message=${*:-This is a test alert.}

case "$severity" in
  critical) title="Critical: Test alert"; priority=5; tags=rotating_light ;;
  warning)  title="Warning: Test alert";  priority=3; tags=warning ;;
  *) usage ;;
esac

env_file="$(dirname "$0")/../secrets/grafana.env"
[[ -r $env_file ]] || { echo "can't read $env_file (run: make decrypt-secrets)" >&2; exit 1; }

url=$(sed -n 's/^NTFY_URL=//p' "$env_file" | tr -d "\"'")
[[ -n $url ]] || { echo "NTFY_URL is not set in $env_file" >&2; exit 1; }

curl -fsS -o /dev/null --max-time 15 \
  -H "Title: $title" \
  -H "Priority: $priority" \
  -H "Tags: $tags" \
  --data-binary "$message" \
  "$url"

echo "sent $severity: $message"
