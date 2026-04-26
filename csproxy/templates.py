#!/usr/bin/env python3
"""
Embedded text templates for remote server scripts, configuration files, and help text.

These templates are used across proxy, wireguard, and serve modules.
Separated to keep source modules focused on logic.
"""

# =============================================================================
# Serve module templates - Python HTTP server scripts uploaded to Codespace
# =============================================================================

_START_HELPER = """\
import time, subprocess, os

def start_server(handler, port, retries=5):
    from http.server import HTTPServer
    HTTPServer.allow_reuse_address = True
    for attempt in range(retries):
        try:
            server = HTTPServer(('', port), handler)
            server.serve_forever()
        except OSError as e:
            if attempt < retries - 1:
                print(f'Port {{port}} busy, killing and retrying ({{attempt+1}}/{{retries}})...', flush=True)
                subprocess.run(['fuser', '-k', '-9', f'{{port}}/tcp'],
                               capture_output=True)
                subprocess.run(['sh', '-c',
                                f'lsof -ti:{{port}} | xargs kill -9 2>/dev/null'],
                               capture_output=True)
                time.sleep(2)
            else:
                raise
"""

FILE_SERVER_SCRIPT = _START_HELPER + """\
from http.server import SimpleHTTPRequestHandler

class NoListingHandler(SimpleHTTPRequestHandler):
    def list_directory(self, path):
        self.send_error(403, "Directory listing disabled")
        return None

    def log_message(self, format, *args):
        print(f"[REQUEST] {{args[0]}}", flush=True)

os.chdir("/tmp/serve")
print(f"Serving on port {PORT}...", flush=True)
start_server(NoListingHandler, {PORT})
"""

REDIRECT_SERVER_SCRIPT = _START_HELPER + """\
from http.server import BaseHTTPRequestHandler

TARGET_URL = {TARGET_URL!r}
REDIRECT_CODE = {REDIRECT_CODE}

class RedirectHandler(BaseHTTPRequestHandler):
    def _redirect(self):
        if TARGET_URL.startswith(('http://', 'https://')) and self.path not in ('/', ''):
            redirect_url = TARGET_URL.rstrip('/') + self.path
        else:
            redirect_url = TARGET_URL

        print(f'[REDIRECT {{REDIRECT_CODE}}] {{self.path}} -> {{redirect_url}}', flush=True)
        print(f'  Client: {{self.client_address[0]}}', flush=True)
        print(f'  User-Agent: {{self.headers.get("User-Agent", "N/A")}}', flush=True)

        self.send_response(REDIRECT_CODE)
        self.send_header('Location', redirect_url)
        self.send_header('Content-Length', '0')
        self.end_headers()

    do_GET = do_POST = do_HEAD = _redirect

    def log_message(self, format, *args):
        pass

print(f'Redirect server on port {PORT}', flush=True)
print(f'Redirecting to: {{TARGET_URL}}', flush=True)
print(f'Redirect type: {{REDIRECT_CODE}}', flush=True)
print('=' * 50, flush=True)
start_server(RedirectHandler, {PORT})
"""

CUSTOM_SERVER_SCRIPT = _START_HELPER + """\
from http.server import BaseHTTPRequestHandler

RESPONSE_BODY = {RESPONSE_BODY!r}
CONTENT_TYPE = {CONTENT_TYPE!r}
STATUS_CODE = {STATUS_CODE}

class CustomHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        print(f'[REQUEST] {{self.command}} {{self.path}}', flush=True)
        print(f'  Client: {{self.client_address[0]}}', flush=True)
        for header, value in self.headers.items():
            print(f'  {{header}}: {{value}}', flush=True)
        print(flush=True)

        body = RESPONSE_BODY.encode('utf-8')
        self.send_response(STATUS_CODE)
        self.send_header('Content-Type', CONTENT_TYPE)
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        print(f'[REQUEST] {{self.command}} {{self.path}}', flush=True)
        print(f'  Client: {{self.client_address[0]}}', flush=True)
        print(f'  Body: {{post_data.decode("utf-8", errors="replace")}}', flush=True)
        print(flush=True)
        self.do_GET()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    def log_message(self, format, *args):
        pass

print(f'Custom server on port {PORT}', flush=True)
print(f'Status: {{STATUS_CODE}}, Content-Type: {{CONTENT_TYPE}}', flush=True)
print('=' * 50, flush=True)
start_server(CustomHandler, {PORT})
"""

CAPTURE_SERVER_SCRIPT = _START_HELPER + """\
import base64, json
from http.server import BaseHTTPRequestHandler

CAPTURE_DIR = '/tmp/serve/captures'
os.makedirs(CAPTURE_DIR, exist_ok=True)

capture_count = 0

def is_base64(data):
    try:
        if len(data) < 4:
            return False
        cleaned = data.strip()
        decoded = base64.b64decode(cleaned, validate=True)
        if base64.b64encode(decoded).rstrip(b'=') == cleaned.rstrip(b'=').replace(b'\\n', b''):
            return True
    except Exception:
        pass
    return False

class CaptureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        print(f'[GET] {{self.path}} from {{self.client_address[0]}}', flush=True)
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Access-Control-Allow-Origin', '*')
        body = b'OK'
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        global capture_count
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b''

        capture_count += 1
        seq = f'{{capture_count:03d}}'
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')

        print(f'', flush=True)
        print(f'[CAPTURE #{{seq}}] {{timestamp}}', flush=True)
        print(f'  Method:  {{self.command}} {{self.path}}', flush=True)
        print(f'  Client:  {{self.client_address[0]}}', flush=True)
        print(f'  Length:  {{len(post_data)}} bytes', flush=True)
        for header, value in self.headers.items():
            print(f'  {{header}}: {{value}}', flush=True)

        raw_path = os.path.join(CAPTURE_DIR, f'capture_{{seq}}.bin')
        with open(raw_path, 'wb') as f:
            f.write(post_data)
        print(f'  Saved:   {{raw_path}}', flush=True)

        if post_data and is_base64(post_data):
            try:
                decoded = base64.b64decode(post_data.strip())
                decoded_path = os.path.join(CAPTURE_DIR, f'capture_{{seq}}.decoded')
                with open(decoded_path, 'wb') as f:
                    f.write(decoded)
                print(f'  Base64:  Detected and decoded ({{len(decoded)}} bytes) -> {{decoded_path}}', flush=True)
                try:
                    print(f'  Preview: {{decoded[:200].decode("utf-8", errors="replace")}}', flush=True)
                except Exception:
                    print(f'  Preview: (binary data, {{len(decoded)}} bytes)', flush=True)
            except Exception as e:
                print(f'  Base64:  Detection passed but decode failed: {{e}}', flush=True)
        else:
            try:
                print(f'  Preview: {{post_data[:200].decode("utf-8", errors="replace")}}', flush=True)
            except Exception:
                print(f'  Preview: (binary data, {{len(post_data)}} bytes)', flush=True)

        print(f'', flush=True)

        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Access-Control-Allow-Origin', '*')
        body = f'Captured #{{seq}}'.encode()
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    do_PUT = do_PATCH = do_POST

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    def log_message(self, format, *args):
        pass

print(f'Capture server on port {PORT}', flush=True)
print(f'Saving captures to: {{CAPTURE_DIR}}', flush=True)
print('=' * 50, flush=True)
start_server(CaptureHandler, {PORT})
"""


# =============================================================================
# WireGuard remote setup script template
# =============================================================================

WG_REMOTE_SETUP_SCRIPT = """\
#!/usr/bin/env bash
set -euo pipefail

echo "[*] Fixing apt sources if needed..."
sudo rm -f /etc/apt/sources.list.d/yarn.list 2>/dev/null || true

echo "[*] Installing WireGuard..."
sudo apt-get update -o Acquire::AllowInsecureRepositories=true 2>/dev/null || true
sudo apt-get install -y wireguard-tools iptables socat --no-install-recommends 2>/dev/null || {{
    echo "[!] apt install failed, trying with --fix-broken"
    sudo apt-get install -y --fix-broken wireguard-tools iptables socat --no-install-recommends
}}

echo "[*] Creating WireGuard config..."
sudo mkdir -p /etc/wireguard

sudo tee /etc/wireguard/wg0.conf > /dev/null << 'WGCONF'
[Interface]
PrivateKey = {remote_private_key}
Address = {wg_remote_ip}
ListenPort = {wg_port}
PostUp = iptables -I FORWARD 1 -i wg0 -o eth0 -j ACCEPT; iptables -I FORWARD 2 -i eth0 -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -A POSTROUTING -s {wg_network} -o eth0 -j MASQUERADE; sysctl -w net.ipv4.ip_forward=1
PostDown = iptables -D FORWARD -i wg0 -o eth0 -j ACCEPT; iptables -D FORWARD -i eth0 -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT; iptables -t nat -D POSTROUTING -s {wg_network} -o eth0 -j MASQUERADE || true

[Peer]
PublicKey = {local_public_key}
AllowedIPs = {local_ip_host}/32
WGCONF

sudo chmod 600 /etc/wireguard/wg0.conf

echo "[*] Stopping any existing WireGuard..."
sudo wg-quick down wg0 2>/dev/null || true

echo "[*] Starting WireGuard..."
sudo wg-quick up wg0

echo "[*] WireGuard status:"
sudo wg show

echo "[*] Starting TCP-to-UDP relay for tunnel..."
pkill -f 'socat.*TCP-LISTEN.*51821' 2>/dev/null || true
nohup socat TCP-LISTEN:51821,reuseaddr,fork UDP:127.0.0.1:51820 > /tmp/socat_relay.log 2>&1 &
sleep 1
if pgrep -f 'socat.*TCP-LISTEN.*51821' > /dev/null; then
    echo "[+] Socat relay started on port 51821"
else
    echo "[!] Warning: socat relay may not have started"
fi

echo ""
echo "[+] WireGuard is running on port {wg_port}"
echo "[+] Remote IP: {remote_ip_host}"
echo "[+] TCP relay port: 51821"
"""
