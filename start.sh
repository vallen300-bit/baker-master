#!/bin/bash
# Baker start script — starts Tailscale (if configured) then uvicorn

# Start Tailscale if auth key is set
if [ -n "$TAILSCALE_AUTHKEY" ]; then
    echo "Starting Tailscale..."
    tailscaled --state=/var/lib/tailscale/tailscaled.state --socket=/var/run/tailscale/tailscaled.sock &
    sleep 2
    tailscale up --authkey="$TAILSCALE_AUTHKEY" --hostname=baker-render
    echo "Tailscale started: $(tailscale ip -4 2>/dev/null || echo 'connecting...')"
else
    echo "TAILSCALE_AUTHKEY not set — skipping Tailscale"
fi

# Start Baker
exec uvicorn outputs.dashboard:app --host 0.0.0.0 --port $PORT
