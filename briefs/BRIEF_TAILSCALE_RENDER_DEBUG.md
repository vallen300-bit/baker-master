# BRIEF: Tailscale on Render — Debug & Complete

**Priority:** HIGH — unlocks Baker browser agent (BROWSER-AGENT-1 Phase 2)
**Assigned to:** Code Brisen
**Created by:** AI Head (Session 33, 2026-03-23)

## Objective

Get Tailscale running on Baker's Render instance so it can reach Chrome DevTools on the Director's MacBook via private Tailscale network.

## Current State

**What's done:**
- `build.sh` — downloads Tailscale 1.80.3 amd64 binary during Render build
- `start.sh` — starts `tailscaled` in userspace mode before uvicorn
- `TAILSCALE_AUTHKEY` env var set on Render (reusable, ephemeral, expires Jun 21 2026)
- Render Build Command: `bash build.sh`
- Render Start Command: `bash start.sh`
- MacBook Tailscale is running (100.83.39.16)
- TCP proxy running on MacBook: 0.0.0.0:9223 → 127.0.0.1:9222 (Chrome debug port)

**What's NOT working:**
- `baker-render` never appears on `tailscale status`
- No "Tailscale" or "Starting Tailscale" output in Render logs
- Two deploys went live but no Tailscale logs at all — suggests either:
  1. Tailscale binary not being installed during build (curl/tar failing silently)
  2. `tailscaled` crashing on startup even with `--tun=userspace-networking`
  3. Permission issue on Render's container (can't write to /tmp, can't exec binary)

## Files

| File | Purpose |
|------|---------|
| `build.sh` | Build script — pip install + Tailscale binary download |
| `start.sh` | Start script — tailscaled + tailscale up + uvicorn |

## Debugging Steps

### Step 1: Use Render Shell to test interactively

Go to https://dashboard.render.com/web/srv-d6dgsbctgctc73f55730/shell and run:

```bash
# Check if tailscale binary was installed
which tailscale
which tailscaled
tailscale version
tailscaled --version

# If not found, the build step failed. Try manual install:
curl -fsSL https://pkgs.tailscale.com/stable/tailscale_1.80.3_amd64.tgz -o /tmp/tailscale.tgz
ls -la /tmp/tailscale.tgz
tar xzf /tmp/tailscale.tgz -C /tmp/
ls -la /tmp/tailscale_1.80.3_amd64/
/tmp/tailscale_1.80.3_amd64/tailscale version
```

### Step 2: Test tailscaled startup

```bash
# Try userspace networking
mkdir -p /tmp/tailscale
/usr/local/bin/tailscaled --tun=userspace-networking --statedir=/tmp/tailscale --socket=/tmp/tailscale/tailscaled.sock &
sleep 3
# Check if it's running
ps aux | grep tailscaled
# Try to authenticate
/usr/local/bin/tailscale --socket=/tmp/tailscale/tailscaled.sock up --authkey="$TAILSCALE_AUTHKEY" --hostname=baker-render
# Check IP
/usr/local/bin/tailscale --socket=/tmp/tailscale/tailscaled.sock ip -4
```

### Step 3: If binary path is wrong

The build step installs to `/usr/local/bin/` but Render might not have write access there during build. Check:

```bash
ls -la /usr/local/bin/tailscale*
# If not there, try the build step manually:
bash build.sh 2>&1
```

If `/usr/local/bin` is read-only, change `build.sh` to install to the repo directory instead:
```bash
cp /tmp/tailscale_1.80.3_amd64/tailscale ./tailscale
cp /tmp/tailscale_1.80.3_amd64/tailscaled ./tailscaled
```
And update `start.sh` to use `./tailscaled` and `./tailscale`.

### Step 4: If tailscaled crashes

Check stderr output:
```bash
./tailscaled --tun=userspace-networking --statedir=/tmp/tailscale --socket=/tmp/tailscale/tailscaled.sock 2>&1 | head -20
```

Common issues:
- Missing shared libraries (unlikely for static binary)
- Architecture mismatch (Render uses amd64, verify with `uname -m`)
- Port conflicts
- Memory limits

### Step 5: Once Tailscale works on Render

Verify connectivity:
```bash
# On Render shell:
tailscale --socket=/tmp/tailscale/tailscaled.sock ping 100.83.39.16

# Test Chrome access (MacBook must have TCP proxy running on 9223):
curl -s http://100.83.39.16:9223/json/version
```

If that returns Chrome version JSON, the bridge is complete.

## Tailscale Auth Key

Already on Render as `TAILSCALE_AUTHKEY` env var. Value:
```
tskey-auth-kPVzXqrm4X11CNTRL-wJPJZo2Sim3NDbb98hTAn3jUYTdqKUoq9
```
Reusable + Ephemeral. Expires Jun 21, 2026.

## MacBook Side Setup (already done)

1. Chrome runs with `--remote-debugging-port=9222` (localhost only — macOS ignores `--remote-debugging-address`)
2. Python TCP proxy: `0.0.0.0:9223 → 127.0.0.1:9222`
3. Tailscale connected as `macbook-pro-2` (100.83.39.16)

The TCP proxy is running as a background process. If it dies, restart with:
```bash
python3 -c "
import socket, threading
def forward(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data: break
            dst.sendall(data)
    except: pass
    finally: src.close(); dst.close()
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('0.0.0.0', 9223))
server.listen(5)
print('Proxy on 0.0.0.0:9223 → 127.0.0.1:9222')
while True:
    client, addr = server.accept()
    remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    remote.connect(('127.0.0.1', 9222))
    threading.Thread(target=forward, args=(client, remote), daemon=True).start()
    threading.Thread(target=forward, args=(remote, client), daemon=True).start()
" &
```

## Success Criteria

1. `tailscale status` on MacBook shows `baker-render` node
2. From Render Shell: `curl http://100.83.39.16:9223/json/version` returns Chrome info
3. Baker can be started with Tailscale without crashing (start.sh works end-to-end)
4. No impact on Baker's normal operation (Tailscale failure must not block uvicorn startup)

## Fallback

If Render can't run Tailscale at all (permission/environment limitations), the fallback is **Tailscale Funnel** from the MacBook side — exposes Chrome debug port via public HTTPS URL. Works but has security tradeoff (public exposure). AI Head will implement this if Code Brisen reports Render-side is not viable.

## Safety

- **Do NOT modify dashboard.py or any Baker business logic** — this is infrastructure only
- Only files to modify: `build.sh`, `start.sh`
- If Baker crashes on deploy, revert start command to `uvicorn outputs.dashboard:app --host 0.0.0.0 --port $PORT`
- Tailscale failure in start.sh must be non-blocking (the `if kill -0` check handles this)
