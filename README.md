<p align="center">
  <img src="docs/assets/logo.png" alt="fluffy-barnacle" width="280">
</p>

<h1 align="center">Fluffy-Barnacle</h1>

<p align="center">
  <b>Disposable, ephemeral network infrastructure powered by GitHub Codespaces.</b><br>
  Deploy SOCKS5 proxies, HTTPS file hosting, and WireGuard tunnels in seconds, for free.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt="Python 3.8+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="Apache 2.0 License"></a>
  <a href="https://github.com/psf/black"><img src="https://img.shields.io/badge/code%20style-black-000000.svg" alt="Code style: black"></a>
</p>

---
> [!WARNING]
> This software is provided strictly for **educational, research, and authorized security testing purposes.** 
>
> **GitHub's Terms of Service** and **Acceptable Use Policies** explicitly prohibit certain uses of Codespaces, including:
> 
> - Using Codespaces to disrupt services, gain unauthorized access to networks/devices, or support attack infrastructure (see [GitHub Terms for Additional Products and Features - Codespaces section](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features#codespaces)).
> - Placing disproportionate burden on GitHub's servers (e.g., excessive bandwidth, proxy/CDN-like usage).
> - Any activity violating applicable laws, third-party rights, or GitHub's Acceptable Use Policies (e.g., unauthorized scanning, proxying for malicious purposes).
> 
> Misuse may result in suspension/termination of your GitHub account, Codespaces access restrictions, or other enforcement actions by GitHub.
> The author is not liable for any harm or damage resulting from its unauthorized use.

## Documentation

Full documentation at **[https://dstours.github.io/fluffy-barnacle/](https://dstours.github.io/fluffy-barnacle/)**

## What is Fluffy-Barnacle?

**Fluffy-Barnacle** is an operator-focused toolkit that turns GitHub Codespaces into free, ephemeral network infrastructure. It provides a suite of CLI tools for rapid deployment and teardown.

| Tool | Description |
|------|-------------|
| **cs-proxy** | SOCKS5 and HTTP proxy via SSH tunnel with auto-reconnect and Burp Suite integration |
| **cs-serve** | Instant public HTTPS file hosting, redirect servers, custom HTTP responses, and data capture via `*.app.github.dev` |
| **cs-wg** | Full WireGuard VPN tunnel with route management and traffic monitoring |
| **cs-tools** | Drop-in wrappers for nmap, ffuf, httpx, nuclei, sqlmap with automatic SOCKS5 proxy arguments |

Codespace IPs rotate on each creation, giving you fresh egress IPs on demand. Each tool works from the CLI or as a Python library.

## Quick Start

```bash
pip install -e .
gh auth login
cs-proxy start
cs-tools ipcheck          # verify you're proxied
```

See the [Quick Start Guide](https://dstours.github.io/fluffy-barnacle/quickstart/) for detailed setup.

## Feature Highlights

### SOCKS5 Proxy with Auto-Reconnect

```bash
cs-proxy start                                # single proxy, auto-select codespace
cs-proxy -n 2 start -l WestEurope -l EastUs  # two proxies, different regions (ports 1080 + 1081)
cs-proxy status             # codespace state + per-tunnel exit IP
cs-proxy ssh                # interactive shell (menu if multiple codespaces tracked)
cs-proxy env                # export statements for tools that read env vars
cs-proxy burp               # upstream proxy config for Burp Suite
```

### Public File Hosting

```bash
cs-serve file payload.bin                               # serve a file
cs-serve redirect http://169.254.169.254/metadata/      # SSRF redirect
cs-serve custom 9999 '{"pwned":true}' application/json  # custom response
cs-serve capture                                        # capture POST data
cs-serve -d dev.example.com file payload.bin            # custom domain via Cloudflare
```

### WireGuard VPN

```bash
cs-wg up
cs-wg route add 192.168.10.0/24    # route a specific subnet
cs-wg route all                     # route everything
cs-wg monitor http                  # tcpdump with labeled output
cs-wg down
```

### Proxied Tool Wrappers

```bash
cs-tools ipcheck
cs-tools pnmap -p 80,443,8080 target.com
cs-tools pffuf -u https://target.com/FUZZ -w list.txt
cs-tools phttpx -l domains.txt -title -status-code
cs-tools pcs gobuster dir -u https://target.com -w list.txt
```

## Installation

**Requirements:** Python 3.8+, [GitHub CLI](https://cli.github.com/) (`gh`), `ssh`, `curl`

```bash
git clone https://github.com/dstours/fluffy-barnacle.git
cd fluffy-barnacle
pip install -e .
```

Optional dependencies for specific features:

- `wg`, `wg-quick`, `socat`, `ip` -- for `cs-wg`
- `proxychains4`, `tinyproxy` -- for `cs-proxy proxychains` / `cs-proxy http`
- `tcpdump` -- for `cs-wg monitor`

See the [Installation Guide](https://dstours.github.io/fluffy-barnacle/user-guide/installation/) for platform-specific instructions.

## Python API

```python
from csproxy import SSHTunnel, Config, GitHubManager, CodespaceSelector

config = Config()
gh = GitHubManager()
cs_name = CodespaceSelector(gh, config).select()

tunnel = SSHTunnel(config, cs_name)
tunnel.start()

from csproxy import check_proxy, ipcheck, pnmap
if check_proxy():
    ipcheck()
    pnmap(['-p', '80,443', 'target.com'])
```

## Configuration

Config file: `~/.config/cs-proxy/config.yaml`

```yaml
socks_port: 1080
http_proxy_port: 8080
num_proxies: 1              # 1-2; starts a tunnel through each on consecutive ports
codespace_name: ""
locations: []               # e.g. [WestEurope, EastUs] — one region per codespace
reconnect_delay: 5
max_reconnect_delay: 300
verbose: false
```

See the [Configuration Reference](https://dstours.github.io/fluffy-barnacle/user-guide/configuration/) for all options and environment variables.

## License

[Apache-2.0](LICENSE)
