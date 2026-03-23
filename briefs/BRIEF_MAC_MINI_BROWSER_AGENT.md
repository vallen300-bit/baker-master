# BRIEF: Mac Mini Browser Agent Setup

**Date**: 2026-03-23 (updated)
**Priority**: High
**Estimated time**: 20 minutes

## Architecture (Tailscale Funnel)

```
Baker (Render) → HTTPS → Tailscale Funnel → Mac Mini:9223 → chrome-proxy.py → Chrome:9222
```

No special software needed on Render. Baker makes standard HTTPS requests to the Funnel URL.

## Prerequisites

- Mac Mini is on and connected to internet
- You know the Mac Mini's admin password
- Tailscale account: vallen300@ (already has macbook-pro-2 registered)

## Step 1 — Install Tailscale

Open Terminal on the Mac Mini:

```bash
brew install --cask tailscale
```

Enter admin password when prompted. Then:

```bash
open -a Tailscale
```

Sign in with the **same vallen300@ account** used on the MacBook. Verify:

```bash
/Applications/Tailscale.app/Contents/MacOS/Tailscale status
```

You should see both devices listed.

## Step 2 — Set up Chrome debug profile

```bash
mkdir -p ~/.chrome-debug-profile
```

Create the launch script:

```bash
cat > ~/.chrome-debug-profile/launch-chrome-debug.sh << 'EOF'
#!/bin/bash
if curl -s http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
    echo "Chrome debug already running on port 9222"
    exit 0
fi
pkill -f "Google Chrome" 2>/dev/null
sleep 2
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --remote-allow-origins="*" \
    --user-data-dir="$HOME/.chrome-debug-profile" \
    >/dev/null 2>&1 &
sleep 4
if curl -s http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
    echo "Chrome debug started on port 9222"
else
    echo "ERROR: Chrome debug failed to start"
    exit 1
fi
EOF
chmod +x ~/.chrome-debug-profile/launch-chrome-debug.sh
```

Launch Chrome:

```bash
~/.chrome-debug-profile/launch-chrome-debug.sh
```

## Step 3 — Log into sites

Chrome opens with a fresh profile. Log into these 4 sites:

1. **Baker dashboard**: https://baker-master.onrender.com → API key: `bakerbhavanga`
2. **WhatsApp Web**: https://web.whatsapp.com → scan QR with phone
3. **Gmail**: https://mail.google.com → dvallen@brisengroup.com
4. **Dropbox**: https://www.dropbox.com → sign in

## Step 4 — Set up Chrome proxy

Chrome only listens on localhost. This proxy rewrites the Host header so requests from Tailscale Funnel work.

```bash
cat > ~/.chrome-debug-profile/chrome-proxy.py << 'PYEOF'
"""HTTP reverse proxy for Chrome DevTools Protocol.
Rewrites Host header so Chrome accepts Funnel requests.
Handles WebSocket upgrade for CDP commands.
"""
import http.server
import urllib.request
import socketserver
import socket
import threading

CHROME_HOST = "127.0.0.1"
CHROME_PORT = 9222
PROXY_PORT = 9223

class ChromeProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self._proxy_websocket()
            return
        self._proxy_http("GET")

    def do_PUT(self):
        self._proxy_http("PUT")

    def do_POST(self):
        self._proxy_http("POST")

    def _proxy_http(self, method):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None
            req = urllib.request.Request(
                f"http://{CHROME_HOST}:{CHROME_PORT}{self.path}",
                data=body, method=method,
                headers={"Host": f"{CHROME_HOST}:{CHROME_PORT}"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"Proxy error: {e}".encode())

    def _proxy_websocket(self):
        try:
            remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote.connect((CHROME_HOST, CHROME_PORT))
            request_line = f"{self.command} {self.path} {self.request_version}\r\n"
            headers = f"Host: {CHROME_HOST}:{CHROME_PORT}\r\n"
            for key, value in self.headers.items():
                if key.lower() != "host":
                    headers += f"{key}: {value}\r\n"
            headers += "\r\n"
            remote.sendall((request_line + headers).encode())
            client_sock = self.connection
            def forward(src, dst):
                try:
                    while True:
                        data = src.recv(65536)
                        if not data: break
                        dst.sendall(data)
                except: pass
                finally:
                    try: src.close()
                    except: pass
                    try: dst.close()
                    except: pass
            t1 = threading.Thread(target=forward, args=(client_sock, remote), daemon=True)
            t2 = threading.Thread(target=forward, args=(remote, client_sock), daemon=True)
            t1.start()
            t2.start()
            t1.join()
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"WebSocket proxy error: {e}".encode())

    def log_message(self, format, *args):
        pass

class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    server = ReusableTCPServer(("0.0.0.0", PROXY_PORT), ChromeProxyHandler)
    print(f"Chrome proxy on 0.0.0.0:{PROXY_PORT} -> {CHROME_HOST}:{CHROME_PORT}")
    server.serve_forever()
PYEOF
```

Start the proxy:

```bash
python3 ~/.chrome-debug-profile/chrome-proxy.py &
```

Verify:

```bash
curl -s http://127.0.0.1:9223/json/version | head -1
```

## Step 5 — Start Tailscale Funnel

```bash
/Applications/Tailscale.app/Contents/MacOS/Tailscale funnel 9223
```

Note the URL it prints (e.g., `https://mac-mini.tail4c0b32.ts.net/`).

**Test from any other machine:**

```bash
curl -s https://YOUR-MAC-MINI-HOSTNAME.tail4c0b32.ts.net/json/version
```

Should return Chrome version JSON.

## Step 6 — Set Render env var

On Render dashboard → baker-master → Environment:

```
CHROME_CDP_URL = https://YOUR-MAC-MINI-HOSTNAME.tail4c0b32.ts.net
```

Baker's `browser_client.py` reads this to reach Chrome.

## Step 7 — Auto-start on boot

### Chrome (LaunchAgent):

```bash
cat > ~/Library/LaunchAgents/com.baker.chrome-debug.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.baker.chrome-debug</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Applications/Google Chrome.app/Contents/MacOS/Google Chrome</string>
        <string>--remote-debugging-port=9222</string>
        <string>--remote-allow-origins=*</string>
        <string>--user-data-dir=/Users/dimitry/.chrome-debug-profile</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.baker.chrome-debug.plist
```

### Chrome Proxy (LaunchAgent):

```bash
cat > ~/Library/LaunchAgents/com.baker.chrome-proxy.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.baker.chrome-proxy</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/dimitry/.chrome-debug-profile/chrome-proxy.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.baker.chrome-proxy.plist
```

### Tailscale Funnel (LaunchAgent):

```bash
cat > ~/Library/LaunchAgents/com.baker.tailscale-funnel.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.baker.tailscale-funnel</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Applications/Tailscale.app/Contents/MacOS/Tailscale</string>
        <string>funnel</string>
        <string>9223</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.baker.tailscale-funnel.plist
```

## Step 8 — Verify end-to-end

Ask Baker (via dashboard or WhatsApp): "Check my latest emails" or browse a site.

Baker on Render → HTTPS → Tailscale Funnel → Mac Mini → Chrome → authenticated site → result

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Chrome not listening | `~/.chrome-debug-profile/launch-chrome-debug.sh` |
| Proxy not running | `python3 ~/.chrome-debug-profile/chrome-proxy.py &` |
| Funnel not running | `/Applications/Tailscale.app/Contents/MacOS/Tailscale funnel 9223` |
| Tailscale disconnected | `open -a Tailscale`, check menu bar |
| "Host header" error | Chrome proxy not running — requests bypass proxy |
| WhatsApp logged out | Open Chrome on Mac Mini, re-scan QR code |

## Opening prompt for Claude Code tomorrow:

```
Session 34, Mac Mini setup. Tailscale is installed and connected. Chrome debug running on 9222, chrome-proxy.py on 9223, Tailscale Funnel active. My Funnel URL is [PASTE URL HERE]. Set CHROME_CDP_URL on Render and test Baker browsing end-to-end.
```
