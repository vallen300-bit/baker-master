#!/bin/bash
# Baker build script — pip install + Tailscale binary

# Standard pip install
pip install -r requirements.txt

# Install Tailscale (static Linux binary)
if [ -n "$TAILSCALE_AUTHKEY" ]; then
    echo "Installing Tailscale..."
    curl -fsSL https://pkgs.tailscale.com/stable/tailscale_1.80.3_amd64.tgz -o /tmp/tailscale.tgz
    tar xzf /tmp/tailscale.tgz -C /tmp/
    cp /tmp/tailscale_1.80.3_amd64/tailscale /usr/local/bin/tailscale
    cp /tmp/tailscale_1.80.3_amd64/tailscaled /usr/local/bin/tailscaled
    mkdir -p /var/lib/tailscale /var/run/tailscale
    rm -rf /tmp/tailscale.tgz /tmp/tailscale_1.80.3_amd64
    echo "Tailscale installed: $(tailscale version)"
else
    echo "TAILSCALE_AUTHKEY not set — skipping Tailscale install"
fi
