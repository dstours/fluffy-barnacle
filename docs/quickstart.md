# Quick Start

Get cs-proxy running in under a minute.

## Prerequisites

- Python 3.10+
- [GitHub CLI](https://cli.github.com/) (`gh`) installed and authenticated
- `ssh` and `curl` available

## Install

```bash
git clone https://github.com/dstours/fluffy-barnacle.git
cd fluffy-barnacle
pip install -e .
```

## Authenticate

```bash
gh auth login
```

## Verify Your Setup

```bash
cs-proxy check
```

This diagnoses your environment: `gh` auth, SSH keys, port availability, config, and state file health.

## Start a Proxy

```bash
cs-proxy start
```

This will:

1. Select an existing Codespace (or create one interactively)
2. Start an SSH tunnel with SOCKS5 forwarding on `127.0.0.1:1080`
3. Run in the background with automatic reconnection and circuit-breaker protection

## Verify

```bash
cs-tools ipcheck
```

This compares your direct IP with the proxied IP to confirm traffic is routing through the Codespace.

## Use It

### Route tools through the proxy

```bash
cs-tools pcurl https://ifconfig.me
cs-tools pnmap -p 80,443 target.com
cs-tools pffuf -u https://target.com/FUZZ -w wordlist.txt
```

Preview a command before running it:

```bash
cs-tools --dry-run pnmap -p 80,443 target.com
```

Pin to a specific tunnel port:

```bash
cs-tools --port 1081 pcurl https://target.com
```

### Monitor tunnel health

```bash
cs-proxy status              # one-shot status
cs-proxy status --watch      # auto-refresh every 2 seconds
```

### Serve files publicly

```bash
cs-serve file payload.bin
# Gives you a public https://*.app.github.dev URL
```

### Set up a VPN tunnel

```bash
sudo cs-wg up
sudo cs-wg route add 10.0.0.0/8
```

## Two Proxies, Different Exit IPs

```bash
cs-proxy -n 2 start -l WestEurope -l EastUs
# Tunnel 1: socks5://127.0.0.1:1080  (WestEurope)
# Tunnel 2: socks5://127.0.0.1:1081  (EastUs)

curl --socks5-hostname 127.0.0.1:1080 https://ifconfig.me
curl --socks5-hostname 127.0.0.1:1081 https://ifconfig.me
cs-proxy status     # health + exit IP per tunnel
cs-proxy ssh        # numbered menu to pick which codespace to shell into
```

## Dry-Run Mode

Preview actions without making changes:

```bash
cs-proxy --dry-run start     # show what would start
cs-proxy --dry-run stop      # show what would stop
cs-tools --dry-run pnmap -p 80 target.com   # preview the nmap command
```

## Stop

```bash
cs-proxy stop          # stop all proxy tunnels
cs-proxy teardown      # stop tunnels + shut down codespaces (storage preserved)
cs-proxy down          # stop tunnels + permanently delete codespaces
cs-proxy delete        # interactively delete specific codespace(s)
```

## Next Steps

- [Installation Guide](user-guide/installation.md) -- platform-specific setup and troubleshooting
- [Configuration](user-guide/configuration.md) -- customize ports, codespace, profiles, and behavior
- [Command Reference](user-guide/command-reference/index.md) -- full list of commands
- [Use Cases](use-cases/index.md) -- real-world scenarios and workflows
