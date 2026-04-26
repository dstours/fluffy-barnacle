# cs-proxy

SOCKS5 and HTTP proxy management via SSH tunnel to a GitHub Codespace.

## Usage

```
cs-proxy [options] <command> [args]
```

## Global Options

| Flag | Description | Default |
|------|-------------|---------|
| `-p`, `--port` | SOCKS5 proxy port | `1080` |
| `-n`, `--num-proxies` | Number of codespaces/tunnels (1-2 on free tier); each gets its own port | `1` |
| `-c`, `--codespace` | Codespace name | auto-select |
| `-l`, `--location` | Region for new Codespace: `EastUs`, `WestUs2`, `WestEurope`, `SouthEastAsia`. Repeat for multiple: `-l WestEurope -l EastUs` | none |
| `-v`, `--verbose` | Verbose output | off |
| `--dry-run` | Show what would happen without making changes | off |

## Commands

### Tunnel Management

#### `start`

Start a SOCKS5 proxy tunnel to a Codespace.

```bash
cs-proxy start                                # auto-select or create one codespace
cs-proxy start -c my-codespace-name          # use a specific codespace
cs-proxy start -p 9050                       # use a non-default port
cs-proxy -n 2 start                          # two codespaces, two tunnels (1080 + 1081)
cs-proxy -n 2 start -l WestEurope -l EastUs  # pin each to a specific region
cs-proxy --dry-run start                     # preview what would happen
```

Starts an SSH tunnel with SOCKS5 dynamic port forwarding on `127.0.0.1:<port>`. The tunnel runs in the background with automatic reconnection using exponential backoff and jitter.

When `-n 2` is used, a second codespace is created (or reused) and a second independent tunnel is started on the next port (`socks_port + 1`). Each tunnel has a different exit IP. Use `-l` once per codespace to pin each to a region: `EastUs`, `WestUs2`, `WestEurope`, `SouthEastAsia`.

**Circuit breaker:** If a tunnel fails 3 consecutive health checks, it is automatically marked as `dead` and stops retrying. Use `cs-proxy restart` to reset it.

#### `stop`

Stop the proxy tunnel and HTTP proxy.

```bash
cs-proxy stop
cs-proxy --dry-run stop   # preview what would stop
```

#### `restart`

Restart the proxy tunnel.

```bash
cs-proxy restart
```

#### `status`

Show tunnel status, Codespace state, and exit IP.

```bash
cs-proxy status
cs-proxy status --watch   # auto-refresh every 2 seconds
```

When multiple codespaces are tracked, shows each tunnel's port, health, and exit IP side by side.

### Diagnostics

#### `check`

Run diagnostics and report configuration/dependency health.

```bash
cs-proxy check
```

Checks:

- `gh` CLI installed and authenticated
- `ssh`, `curl`, `proxychains4` installed
- Config directory and file present
- SSH key generated
- SOCKS5/HTTP ports available
- State file readable

Returns exit code `0` if all checks pass, `1` if any issues are found.

### HTTP Proxy

#### `http`

Start an HTTP proxy (tinyproxy) that connects upstream to the SOCKS5 tunnel.

```bash
cs-proxy http
```

This is useful for tools that support HTTP proxies but not SOCKS5. The HTTP proxy listens on port 8080 by default.

### Configuration

#### `env`

Print environment export statements for shell integration.

```bash
eval $(cs-proxy env)
```

Exports `http_proxy`, `https_proxy`, `ALL_PROXY`, and `SOCKS_PROXY`.

#### `burp`

Print Burp Suite upstream proxy configuration.

```bash
cs-proxy burp
```

#### `pac`

Generate a Proxy Auto-Config (PAC) file for browser routing.

```bash
cs-proxy pac > ~/.config/cs-proxy/proxy.pac
```

The PAC script routes local addresses directly and sends everything else through the SOCKS5 proxy. Point your browser to `file:///Users/you/.config/cs-proxy/proxy.pac`.

#### `proxychains`

Generate a proxychains4 configuration file.

```bash
cs-proxy proxychains
```

#### `completion`

Generate shell completion scripts.

```bash
cs-proxy completion bash   # bash completion
cs-proxy completion zsh    # zsh completion
```

#### `set`

Set a configuration value.

```bash
cs-proxy set socks_port 9050
cs-proxy set codespace_name my-codespace
```

#### `config`

Open the configuration file in your `$EDITOR`.

```bash
cs-proxy config
```

### Codespace Management

#### `list`

List available Codespaces.

```bash
cs-proxy list
```

#### `create`

Create a new Codespace interactively.

```bash
cs-proxy create
```

#### `teardown`

Stop the proxy tunnel(s) and shut down all managed Codespaces (compute stops, storage is preserved — no billing).

```bash
cs-proxy teardown     # stops all tunnels and all tracked codespaces
```

#### `down`

Stop the proxy tunnel(s), shut down, and **permanently delete** all managed Codespaces.

```bash
cs-proxy down         # stops tunnels, then prompts to confirm deletion
```

This is the "nuclear option" for cleaning up after a session. It stops tunnels, stops codespaces, then asks for confirmation before permanently deleting them.

#### `name`

Get or set the current Codespace name.

```bash
cs-proxy name                    # show current
cs-proxy name my-codespace       # set
```

### Utilities

#### `ssh`

Open an SSH session to a Codespace.

```bash
cs-proxy ssh          # auto-selects; shows numbered menu if multiple codespaces tracked
cs-proxy ssh 2        # connect to the second tracked codespace by index
cs-proxy ssh my-cs    # connect to a specific codespace by name
```

#### `run`

Run a command through the proxy.

```bash
cs-proxy run curl https://ifconfig.me
```

#### `keygen`

Generate an SSH keypair for Codespace authentication.

```bash
cs-proxy keygen
```

#### `split`

Set up split tunneling routes.

```bash
cs-proxy split
```

#### `logs`

Show tunnel logs.

```bash
cs-proxy logs
cs-proxy logs 100     # last 100 lines
```
