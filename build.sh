#!/bin/bash
# Baker build script — pip install + Tailscale binary

# Standard pip install
pip install -r requirements.txt

# Install Tailscale (static Linux binary) into repo directory
if [ -n "$TAILSCALE_AUTHKEY" ]; then
    echo "=== Installing Tailscale ==="
    echo "Architecture: $(uname -m)"
    curl -fsSL https://pkgs.tailscale.com/stable/tailscale_1.80.3_amd64.tgz -o /tmp/tailscale.tgz || { echo "ERROR: curl failed"; exit 0; }
    ls -la /tmp/tailscale.tgz
    tar xzf /tmp/tailscale.tgz -C /tmp/ || { echo "ERROR: tar failed"; exit 0; }
    ls -la /tmp/tailscale_1.80.3_amd64/
    # Install to repo directory (Render persists this to runtime)
    cp /tmp/tailscale_1.80.3_amd64/tailscale ./tailscale
    cp /tmp/tailscale_1.80.3_amd64/tailscaled ./tailscaled
    chmod +x ./tailscale ./tailscaled
    rm -rf /tmp/tailscale.tgz /tmp/tailscale_1.80.3_amd64
    echo "Tailscale installed: $(./tailscale version)"
    ls -la ./tailscale ./tailscaled
else
    echo "TAILSCALE_AUTHKEY not set — skipping Tailscale install"
fi
