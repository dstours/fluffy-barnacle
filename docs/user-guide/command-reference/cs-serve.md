# cs-serve

Instant public HTTPS file hosting, redirect servers, and custom HTTP responses using GitHub Codespaces.

All servers are exposed via `*.app.github.dev` URLs with automatic HTTPS -- no DNS setup required.

## Usage

```
cs-serve <command> [options]
```

## Commands

### `file`

Serve a single file.

```bash
cs-serve file payload.bin
cs-serve file exploit.html 8888
```

The file is uploaded to the Codespace and served via Python's HTTP server. The public URL is printed once the port forward is active.

**Arguments:**

| Argument | Description | Default |
|----------|-------------|---------|
| `filepath` | Local file to serve | required |
| `port` | Port to serve on | `9999` |

### `dir`

Serve a directory with file listing.

```bash
cs-serve dir ./www
cs-serve dir /path/to/payloads 8888
```

!!! note
    Directory listing is disabled by default for security. Files are served by direct path only.

### `redirect`

Start a redirect server.

```bash
cs-serve redirect http://169.254.169.254/metadata/
cs-serve redirect "javascript:alert(document.domain)" 8888 301
```

Useful for SSRF testing, XSS payload delivery, and URL manipulation.

**Arguments:**

| Argument | Description | Default |
|----------|-------------|---------|
| `url` | Target URL to redirect to | required |
| `port` | Port to serve on | `9999` |
| `code` | HTTP redirect status code | `302` |

### `custom`

Serve a custom HTTP response with arbitrary body, content type, and status code.

```bash
cs-serve custom 9999 '{"pwned":true}' application/json
cs-serve custom 9999 '<html>test</html>' text/html 200
```

**Arguments:**

| Argument | Description | Default |
|----------|-------------|---------|
| `port` | Port to serve on | required |
| `body` | Response body | required |
| `content_type` | Content-Type header | `text/plain` |
| `status` | HTTP status code | `200` |

### `capture`

Start a catch-all capture server that logs and saves incoming POST data. Base64-encoded payloads are auto-detected and decoded.

```bash
cs-serve capture
cs-serve capture 8080
```

When data is received, the server logs the request details (method, path, client IP, headers) and a content preview in real time. If the body is valid base64, it is automatically decoded and the decoded content is shown.

On `Ctrl+C`, all captured files are downloaded from the Codespace to your current working directory.

**Arguments:**

| Argument | Description | Default |
|----------|-------------|---------|
| `port` | Port to listen on | `9999` |

**Saved files:**

| File | Contents |
|------|----------|
| `capture_001.bin` | Raw POST body |
| `capture_001.decoded` | Base64-decoded content (only if base64 detected) |

**Example output:**

```
[CAPTURE #001] 2026-02-20 14:30:00
  Method:  POST /callback
  Client:  203.0.113.42
  Length:  16 bytes
  Content-Type: application/octet-stream
  Saved:   /tmp/serve/captures/capture_001.bin
  Base64:  Detected and decoded (12 bytes) -> capture_001.decoded
  Preview: Hello World!
```

### `stop`

Stop a server running on a specific port.

```bash
cs-serve stop 9999
```

### `clean` / `cleanup`

Kill all running servers and port forwards on the Codespace.

```bash
cs-serve clean
```

### `list`

List files on the Codespace.

```bash
cs-serve list
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-c`, `--codespace` | Codespace name | auto-select |
| `-d`, `--domain` | Custom domain via Cloudflare Worker | none |
| `-v`, `--verbose` | Verbose output | off |

## Custom Domain via Cloudflare Worker

Use the `-d` flag to proxy traffic through a Cloudflare Worker on your own domain, making served content accessible via a clean URL instead of the `*.app.github.dev` URL.

```bash
cs-serve -d dev.example.com file payload.bin
cs-serve -d dev.example.com capture
cs-serve -d dev.example.com redirect http://internal:8080/
```

### Auto-deploy mode

Set `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` environment variables. The worker is deployed automatically and torn down on `Ctrl+C`.

```bash
export CLOUDFLARE_API_TOKEN="your-api-token"
export CLOUDFLARE_ACCOUNT_ID="your-account-id"
cs-serve -d dev.example.com file payload.bin
# → Worker deployed, both URLs shown
# → Ctrl+C tears down worker automatically
```

### Manual mode

Without credentials, cs-serve generates a `worker.js` file and prints setup instructions for the Cloudflare dashboard.

## How It Works

1. A Python HTTP server script is generated locally with the desired behavior
2. The script is uploaded to the Codespace via `gh codespace ssh`
3. The server is started in the background on the Codespace
4. The port is forwarded and made public via `gh codespace ports`
5. A public `https://*.app.github.dev` URL is generated
6. Request logs are tailed in real time
