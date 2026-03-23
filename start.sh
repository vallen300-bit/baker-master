#!/bin/bash
# Baker start script — starts Tailscale (if configured) then uvicorn

# Start Tailscale if auth key is set and binary exists
if [ -n "$TAILSCALE_AUTHKEY" ] && [ -f "./tailscaled" ]; then
    echo "=== Starting Tailscale (userspace mode) ==="
    ls -la ./tailscale ./tailscaled
    mkdir -p /tmp/tailscale
    ./tailscaled --tun=userspace-networking --statedir=/tmp/tailscale --socket=/tmp/tailscale/tailscaled.sock 2>&1 &
    TSPID=$!
    sleep 3
    if kill -0 $TSPID 2>/dev/null; then
        echo "tailscaled running (PID $TSPID)"
        ./tailscale --socket=/tmp/tailscale/tailscaled.sock up --authkey="$TAILSCALE_AUTHKEY" --hostname=baker-render 2>&1
        TS_IP=$(./tailscale --socket=/tmp/tailscale/tailscaled.sock ip -4 2>/dev/null || echo "failed")
        echo "Tailscale IP: $TS_IP"
        ./tailscale --socket=/tmp/tailscale/tailscaled.sock status 2>/dev/null || true
    else
        echo "WARNING: tailscaled failed to start — continuing without Tailscale"
    fi
elif [ -n "$TAILSCALE_AUTHKEY" ]; then
    echo "WARNING: TAILSCALE_AUTHKEY set but ./tailscaled not found — build step may have failed"
    ls -la ./tailscale* 2>/dev/null || echo "No tailscale binaries in repo dir"
else
    echo "TAILSCALE_AUTHKEY not set — skipping Tailscale"
fi

# Start Baker
exec uvicorn outputs.dashboard:app --host 0.0.0.0 --port $PORT
