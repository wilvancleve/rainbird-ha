#!/usr/bin/env bash
# Launch mitmproxy to capture the Rain Bird 2.0 app and extract the OAuth keys.
#
#   ./tools/run_proxy.sh            # writes captures/rainbird-iq4-<stamp>.jsonl
#
# Then on the phone: Wi-Fi > (network) > Configure Proxy > Manual, Server =
# this machine's LAN IP, Port = 8080. First time, install + trust the mitmproxy
# CA via http://mitm.it. Open the Rain Bird 2.0 app and sign in; the client
# id/secret + refresh token are extracted live and saved to captures/.
#
# Requires mitmproxy: `pipx install mitmproxy` or `brew install mitmproxy`.
set -euo pipefail
cd "$(dirname "$0")/.."

MITMDUMP="$(command -v mitmdump || true)"
if [ -z "$MITMDUMP" ]; then
  echo "mitmdump not found. Install with: pipx install mitmproxy (or brew install mitmproxy)" >&2
  exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p captures
export RAINBIRD_CAPTURE_FILE="captures/rainbird-iq4-${STAMP}.jsonl"
export RAINBIRD_KEYS_FILE="captures/rainbird-keys-${STAMP}.json"

# Best-effort: show this host's LAN IP so you know what to point the phone at.
IP="$( (ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}') || true)"
echo "Proxy listening on 0.0.0.0:8080   (point the phone's Wi-Fi proxy here: ${IP:-<this host's LAN IP>}:8080)"
echo "Capture : $RAINBIRD_CAPTURE_FILE"
echo "Keys    : $RAINBIRD_KEYS_FILE   (client_id/secret + refresh_token appear here after you sign in)"
echo

exec "$MITMDUMP" -s tools/rainbird_mitm.py --listen-port 8080 --set stream_large_bodies=10m
