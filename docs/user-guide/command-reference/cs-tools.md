# cs-tools

Drop-in wrappers for common security tools that automatically apply SOCKS5 proxy arguments.

Each wrapper checks that cs-proxy is running before executing and exits with a warning if the proxy is down. When multiple tunnels are active, `cs-tools` automatically rotates across healthy tunnels.

## Usage

```
cs-tools <tool> [tool-specific args]
```

## Tools

### `ipcheck`

Compare your direct IP with the proxied IP.

```bash
cs-tools ipcheck
```

Output shows both IPs side by side so you can confirm traffic is being routed through the Codespace.

### `pcurl`

curl with SOCKS5 proxy.

```bash
cs-tools pcurl https://ifconfig.me
cs-tools pcurl -X POST -d '{"test":true}' https://target.com/api
```

Automatically adds `--socks5-hostname 127.0.0.1:<port>`. If multiple tunnels are healthy, a random healthy port is used.

### `pwget`

wget via proxychains.

```bash
cs-tools pwget https://target.com/file.zip
```

### `pnmap`

nmap TCP connect scan through the proxy.

```bash
cs-tools pnmap -p 80,443,8080 target.com
cs-tools pnmap -sV -p 1-1000 target.com
```

Uses proxychains with `-sT` (TCP connect) since SYN scans can't go through SOCKS.

### `pnuclei`

nuclei with proxy.

```bash
cs-tools pnuclei -u https://target.com
cs-tools pnuclei -l urls.txt -t cves/
```

### `pffuf`

ffuf with proxy.

```bash
cs-tools pffuf -u https://target.com/FUZZ -w wordlist.txt
cs-tools pffuf -u https://target.com/FUZZ -w wordlist.txt -mc 200,301
```

### `phttpx`

httpx with proxy.

```bash
cs-tools phttpx -l domains.txt -title -status-code -tech-detect
cs-tools phttpx -u https://target.com -follow-redirects
```

### `psqlmap`

sqlmap with proxy.

```bash
cs-tools psqlmap -u "https://target.com/page?id=1" --batch
```

### `pcs`

Generic proxychains wrapper for any command.

```bash
cs-tools pcs gobuster dir -u https://target.com -w wordlist.txt
cs-tools pcs whatweb https://target.com
cs-tools pcs ssh user@target.com
```

### `psub`

Subdomain enumeration (requires `subfinder`).

```bash
cs-tools psub target.com
```

### `pportscan`

Quick port scan against common ports.

```bash
cs-tools pportscan target.com
cs-tools pportscan 10.0.0.1
```

Default ports: `21,22,23,25,80,443,445,3306,3389,8080,8443`

## Smart Tunnel Rotation

When multiple tunnels are active, `cs-tools` wrappers read `state.json` and pick a random healthy tunnel port. This means:

```bash
cs-proxy -n 2 start -l WestEurope -l EastUs
# Each cs-tools call may use a different exit IP automatically
cs-tools pnmap -p 80,443 target.com
cs-tools phttpx -l hosts.txt
```

If no healthy tunnels exist, tools fall back to the default `socks_port`.

## Default Wordlists

cs-tools looks for SecLists at `~/wordlists/SecLists/` (override with `SECLISTS` env var):

| Variable | Default Path |
|----------|-------------|
| Common | `Discovery/Web-Content/common.txt` |
| Big | `Discovery/Web-Content/big.txt` |
| Dirs | `Discovery/Web-Content/directory-list-2.3-medium.txt` |
| Params | `Discovery/Web-Content/burp-parameter-names.txt` |
| Subdomains | `Discovery/DNS/subdomains-top1million-5000.txt` |
