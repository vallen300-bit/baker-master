#!/bin/bash
# Baker start script — starts Tailscale (if configured) then uvicorn

# Start Tailscale if auth key is set and binary exists
if [ -n "$TAILSCALE_AUTHKEY" ] && [ -f "./tailscaled" ]; then
    echo "=== Starting Tailscale (userspace mode) ==="
    ls -la ./tailscale ./tailscaled
    mkdir -p /tmp/tailscale
    ./tailscaled --tun=userspace-networking --statedir=/tmp/tailscale --socket=/tmp/tailscale/tailscaled.sock 2>&1 &
    TSPID=$!

    # Wait for tailscaled to be ready (up to 15 seconds)
    for i in 1 2 3 4 5; do
        sleep 3
        if [ -S /tmp/tailscale/tailscaled.sock ]; then
            echo "tailscaled socket ready after ${i}x3s"
            break
        fi
        echo "Waiting for tailscaled socket... (attempt $i)"
    done

    if kill -0 $TSPID 2>/dev/null; then
        echo "tailscaled running (PID $TSPID)"
        # Authenticate with retry
        for attempt in 1 2 3; do
            echo "tailscale up attempt $attempt..."
            ./tailscale --socket=/tmp/tailscale/tailscaled.sock up \
                --authkey="$TAILSCALE_AUTHKEY" \
                --hostname=baker-render 2>&1
            TS_RC=$?
            if [ $TS_RC -eq 0 ]; then
                echo "tailscale up succeeded"
                break
            fi
            echo "tailscale up failed (rc=$TS_RC), retrying in 3s..."
            sleep 3
        done
        TS_IP=$(./tailscale --socket=/tmp/tailscale/tailscaled.sock ip -4 2>/dev/null || echo "failed")
        echo "Tailscale IP: $TS_IP"
        ./tailscale --socket=/tmp/tailscale/tailscaled.sock status 2>/dev/null || true
    else
        echo "WARNING: tailscaled failed to start — continuing without Tailscale"
        echo "tailscaled stderr (if any):"
        wait $TSPID 2>/dev/null
    fi
elif [ -n "$TAILSCALE_AUTHKEY" ]; then
    echo "WARNING: TAILSCALE_AUTHKEY set but ./tailscaled not found — build step may have failed"
    ls -la ./tailscale* 2>/dev/null || echo "No tailscale binaries in repo dir"
else
    echo "TAILSCALE_AUTHKEY not set — skipping Tailscale"
fi

# Start Baker
exec uvicorn outputs.dashboard:app --host 0.0.0.0 --port $PORT
