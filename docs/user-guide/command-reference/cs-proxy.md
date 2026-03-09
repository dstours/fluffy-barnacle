# cs-proxy

SOCKS5 and HTTP proxy management via SSH tunnel to a GitHub Codespace.

## Usage

```
cs-proxy <command> [options]
```

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
```

Starts an SSH tunnel with SOCKS5 dynamic port forwarding on `127.0.0.1:<port>`. The tunnel runs in the background with automatic reconnection using exponential backoff.

When `-n 2` is used, a second codespace is created (or reused) and a second independent tunnel is started on the next port (`socks_port + 1`). Each tunnel has a different exit IP. Use `-l` once per codespace to pin each to a region: `EastUs`, `WestUs2`, `WestEurope`, `SouthEastAsia`.

#### `stop`

Stop the proxy tunnel and HTTP proxy.

```bash
cs-proxy stop
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
```

When multiple codespaces are tracked, shows each tunnel's port, health, and exit IP side by side.

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

#### `proxychains`

Generate a proxychains4 configuration file.

```bash
cs-proxy proxychains
```

#### `set`

Set a configuration value.

```bash
cs-proxy set socks_port 9050
cs-proxy set codespace_name my-codespace
```

#### `config`

Manage configuration files.

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

#### `teardown` / `down`

Stop the proxy tunnel(s) and shut down all managed Codespaces (compute stops, storage is preserved — no billing).

```bash
cs-proxy teardown     # stops all tunnels and all tracked codespaces
cs-proxy down         # alias
```

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
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-p`, `--port` | SOCKS5 proxy port | `1080` |
| `-n`, `--num-proxies` | Number of codespaces/tunnels (max 2); each gets its own port | `1` |
| `-c`, `--codespace` | Codespace name | auto-select |
| `-l`, `--location` | Region for new Codespace: `EastUs`, `WestUs2`, `WestEurope`, `SouthEastAsia`. Repeat for multiple: `-l WestEurope -l EastUs` | none |
| `-v`, `--verbose` | Verbose output | off |
