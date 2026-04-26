# Installation

## Requirements

- **Python 3.8+** (3.10+ recommended)
- **Linux or macOS** (WSL works on Windows)

### Required External Tools

| Tool | Purpose |
|------|---------|
| [`gh`](https://cli.github.com/) | GitHub CLI -- manages Codespace lifecycle and SSH tunnels |
| `ssh` | OpenSSH client for tunneling |
| `curl` | HTTP requests and proxy verification |

### Optional External Tools

| Tool | Used By | Purpose |
|------|---------|---------|
| `proxychains4` | `cs-proxy proxychains` | Generate proxychains config |
| `tinyproxy` | `cs-proxy http` | HTTP proxy upstream of SOCKS5 |
| `wg`, `wg-quick` | `cs-wg` | WireGuard interface management |
| `socat` | `cs-wg` | UDP-over-TCP relay for WireGuard |
| `ip` | `cs-wg` | Route and interface management |
| `tcpdump` | `cs-wg monitor` | Traffic monitoring |

## Install cs-proxy

### From Source (Recommended)

```bash
git clone https://github.com/dstours/fluffy-barnacle.git
cd fluffy-barnacle
pip install -e .
```

### With Development Dependencies

```bash
pip install -e ".[dev]"
```

This adds pytest, black, mypy, and flake8.

### Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

## Install External Dependencies

=== "Debian / Ubuntu"

    ```bash
    # Required
    sudo apt update
    sudo apt install -y curl openssh-client

    # GitHub CLI
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) \
      signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
      https://cli.github.com/packages stable main" \
      | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    sudo apt update && sudo apt install -y gh

    # Optional
    sudo apt install -y wireguard-tools socat iproute2 proxychains4 tinyproxy tcpdump
    ```

=== "macOS"

    ```bash
    brew install gh openssh curl

    # Optional
    brew install wireguard-tools socat proxychains-ng tinyproxy tcpdump
    ```

=== "Arch Linux"

    ```bash
    sudo pacman -S github-cli openssh curl

    # Optional
    sudo pacman -S wireguard-tools socat iproute2 proxychains-ng tinyproxy tcpdump
    ```

## Authenticate with GitHub

```bash
gh auth login
```

Select **GitHub.com**, **SSH** protocol, and authenticate via browser.

## Verify Installation

```bash
# Check CLI commands are available
cs-proxy --help
cs-serve --help
cs-wg --help
cs-tools --help

# Run diagnostics
cs-proxy check

# Run the test suite
python -m pytest tests/ -v
```

## Troubleshooting

### `command not found: cs-proxy`

Ensure pip's bin directory is in your `PATH`:

```bash
export PATH="$PATH:$HOME/.local/bin"
```

Add this to your `~/.bashrc` or `~/.zshrc` to make it permanent.

### `ModuleNotFoundError: No module named 'yaml'`

```bash
pip install pyyaml
```

### `ModuleNotFoundError: No module named 'colorama'`

```bash
pip install colorama
```

### Permission denied during install

Use a virtual environment or the `--user` flag:

```bash
pip install --user -e .
```

## Uninstall

```bash
pip uninstall cs-proxy
rm -rf ~/.config/cs-proxy    # remove configuration (optional)
```
