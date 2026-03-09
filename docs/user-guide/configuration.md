# Configuration

cs-proxy uses a YAML configuration file with environment variable overrides.

## Config File

**Location:** `~/.config/cs-proxy/config.yaml`

```yaml
# Proxy settings
socks_port: 1080
http_proxy_port: 8080
num_proxies: 1              # 1-2; each codespace gets its own tunnel on consecutive ports

# Codespace settings
codespace_name: ""          # blank = interactive selection
locations: []               # e.g. [WestEurope, EastUs] — one region per codespace
                            # valid: EastUs, WestUs2, WestEurope, SouthEastAsia

# Connection settings
reconnect_delay: 5          # initial reconnect delay (seconds)
max_reconnect_delay: 300    # max delay with exponential backoff

# Advanced
dns_proxy: false
verbose: false
```

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

## Environment Variables

All settings can be overridden via environment variables:

| Variable | Config Key | Default | Description |
|----------|-----------|---------|-------------|
| `SOCKS_PORT` | `socks_port` | `1080` | SOCKS5 proxy listen port |
| `HTTP_PROXY_PORT` | `http_proxy_port` | `8080` | HTTP proxy listen port |
| `NUM_PROXIES` | `num_proxies` | `1` | Number of codespaces/tunnels (max 2) |
| `CODESPACE_NAME` | `codespace_name` | `""` | Target Codespace name |
| `LOCATIONS` | `locations` | `[]` | Comma-separated regions, e.g. `WestEurope,EastUs` |
| `RECONNECT_DELAY` | `reconnect_delay` | `5` | Initial reconnect delay (s) |
| `MAX_RECONNECT_DELAY` | `max_reconnect_delay` | `300` | Max reconnect delay (s) |
| `DNS_PROXY` | `dns_proxy` | `false` | Route DNS through proxy |
| `VERBOSE` | `verbose` | `false` | Enable debug logging |

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
3. Config file (`~/.config/cs-proxy/config.yaml`)
4. Built-in defaults

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
