#!/bin/bash
# Baker start script — starts Tailscale (if configured) then uvicorn

# Start Tailscale if auth key is set
if [ -n "$TAILSCALE_AUTHKEY" ]; then
    echo "Starting Tailscale (userspace mode)..."
    # Render containers are non-root — use userspace networking (no TUN)
    mkdir -p /tmp/tailscale
    tailscaled --tun=userspace-networking --statedir=/tmp/tailscale --socket=/tmp/tailscale/tailscaled.sock 2>&1 &
    TSPID=$!
    sleep 3
    if kill -0 $TSPID 2>/dev/null; then
        tailscale --socket=/tmp/tailscale/tailscaled.sock up --authkey="$TAILSCALE_AUTHKEY" --hostname=baker-render 2>&1
        echo "Tailscale IP: $(tailscale --socket=/tmp/tailscale/tailscaled.sock ip -4 2>/dev/null || echo 'failed')"
    else
        echo "WARNING: tailscaled failed to start — continuing without Tailscale"
    fi
else
    echo "TAILSCALE_AUTHKEY not set — skipping Tailscale"
fi

# Start Baker
exec uvicorn outputs.dashboard:app --host 0.0.0.0 --port $PORT
