# Configuration

cs-proxy uses a YAML configuration file with environment variable overrides and profile support.

## Config File

**Location:** `~/.config/cs-proxy/config.yaml`

```yaml
# Proxy settings
socks_port: 1080
http_proxy_port: 8080
num_proxies: 1              # 1-2 on free tier; each gets its own tunnel on consecutive ports

# Codespace settings
codespace_name: ""          # blank = interactive selection
locations: []               # e.g. [WestEurope, EastUs] — one region per codespace
                            # valid: EastUs, WestUs2, WestEurope, SouthEastAsia

# Connection settings
reconnect_delay: 5          # initial reconnect delay (seconds)
max_reconnect_delay: 300    # max delay with exponential backoff + jitter

# Advanced
dns_proxy: false
verbose: false

# Profiles — switch between presets without editing files
profile: ""                 # active profile name (must match a key below)
profiles:
  redteam:
    num_proxies: 2
    locations: [WestEurope, EastUs]
  stealth:
    dns_proxy: true
    verbose: true
```

### Validation

The config is validated on load and when setting values:

- `socks_port` and `http_proxy_port` must be between `1024` and `65535`
- `num_proxies` must be between `1` and `5`
- `reconnect_delay` must be `>= 1`
- `max_reconnect_delay` must be `>= reconnect_delay`

Invalid values raise an error immediately so bad configs are caught at startup.

### Create a Config File

```bash
mkdir -p ~/.config/cs-proxy
chmod 700 ~/.config/cs-proxy
```

You can generate an example config programmatically:

```python
from csproxy.utils import create_example_config
from pathlib import Path

create_example_config(Path.home() / '.config/cs-proxy/config.yaml')
```

## Profiles

Profiles let you switch between preset configurations from the command line:

```yaml
profile: "redteam"
profiles:
  redteam:
    num_proxies: 2
    locations: [WestEurope, EastUs]
  stealth:
    dns_proxy: true
    verbose: true
```

When `profile` is set to a key that exists in `profiles`, those values override the top-level defaults. Profile values are merged — keys not specified in the profile keep their default values.

## Environment Variables

All settings can be overridden via environment variables:

| Variable | Config Key | Default | Description |
|----------|-----------|---------|-------------|
| `SOCKS_PORT` | `socks_port` | `1080` | SOCKS5 proxy listen port |
| `HTTP_PROXY_PORT` | `http_proxy_port` | `8080` | HTTP proxy listen port |
| `NUM_PROXIES` | `num_proxies` | `1` | Number of codespaces/tunnels (1-2 on free tier) |
| `CODESPACE_NAME` | `codespace_name` | `""` | Target Codespace name |
| `LOCATIONS` | `locations` | `[]` | Comma-separated regions, e.g. `WestEurope,EastUs` |
| `RECONNECT_DELAY` | `reconnect_delay` | `5` | Initial reconnect delay (s) |
| `MAX_RECONNECT_DELAY` | `max_reconnect_delay` | `300` | Max reconnect delay (s) |
| `DNS_PROXY` | `dns_proxy` | `false` | Route DNS through proxy (`true`/`1`/`yes`) |
| `VERBOSE` | `verbose` | `false` | Enable debug logging (`true`/`1`/`yes`) |

### Additional Environment Variables

| Variable | Used By | Description |
|----------|---------|-------------|
| `GH_TOKEN` | `cs-proxy`, `cs-serve`, `cs-wg` | GitHub Personal Access Token |
| `CS_PROXY_CONFIG_DIR` | All tools | Override config directory |
| `WG_INTERFACE` | `cs-wg` | WireGuard interface name (default: `cswg0`) |
| `WG_PORT` | `cs-wg` | WireGuard listen port (default: `51820`) |
| `WG_LOCAL_IP` | `cs-wg` | Local tunnel IP (default: `10.99.99.2/24`) |
| `WG_REMOTE_IP` | `cs-wg` | Remote tunnel IP (default: `10.99.99.1/24`) |
| `WG_NETWORK` | `cs-wg` | Tunnel network (default: `10.99.99.0/24`) |

## Precedence

Settings are resolved in this order (highest wins):

1. Command-line arguments (`-p`, `-c`, etc.)
2. Environment variables
3. Active profile values (if `profile:` is set)
4. Config file (`~/.config/cs-proxy/config.yaml`)
5. Built-in defaults

## GitHub Authentication

cs-proxy uses the GitHub CLI for authentication. Set up with:

```bash
gh auth login
```

Alternatively, set a personal access token:

```bash
export GH_TOKEN="ghp_your_token_here"
```

Or save it to a file:

```bash
echo "ghp_your_token_here" > ~/.config/cs-proxy/gh_token
chmod 600 ~/.config/cs-proxy/gh_token
```

The token needs the `codespace` scope.

## Deprecated Keys

The following keys are deprecated and will be ignored with a warning:

- `chain` — no longer used; remove from your config file
