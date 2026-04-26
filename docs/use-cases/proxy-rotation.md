# Proxy Rotation

Rotate your egress IP by cycling GitHub Codespaces. Each Codespace gets a fresh IP from GitHub's Azure infrastructure.

## Smart Tunnel Rotation

When you have multiple tunnels running, `cs-tools` automatically picks a healthy tunnel from `state.json`. If one tunnel goes down, traffic is routed through another without manual intervention.

```bash
cs-proxy -n 2 start -l WestEurope -l EastUs

# cs-tools will automatically distribute traffic across healthy tunnels
cs-tools pnmap -p 80,443 target.com
cs-tools pffuf -u https://target.com/FUZZ -w wordlist.txt

# Pin a specific tool to one tunnel explicitly
cs-tools --port 1081 pcurl https://target.com
```

The rotation is random across healthy tunnels. If no healthy tunnels exist, tools fall back to the configured `socks_port`.

## Two Simultaneous Proxies

Run two independent tunnels at once, each with a different exit IP:

```bash
cs-proxy -n 2 start -l WestEurope -l EastUs
```

This creates two codespaces in different regions and starts a tunnel through each:

- `socks5://127.0.0.1:1080` → WestEurope codespace
- `socks5://127.0.0.1:1081` → EastUs codespace

```bash
curl --socks5-hostname 127.0.0.1:1080 https://ifconfig.me   # EU exit IP
curl --socks5-hostname 127.0.0.1:1081 https://ifconfig.me   # US exit IP
cs-proxy status   # shows health and exit IP for each tunnel
```

Route specific tools to one or the other by setting the SOCKS5 proxy endpoint explicitly, or configure Burp Suite / proxychains to use whichever suits the target.

## Manual Rotation

For full IP rotation (new IP each cycle), tear down and recreate:

```bash
# Start with first IP
cs-proxy start
cs-tools ipcheck          # note the exit IP

# Rotate: tear down and recreate
cs-proxy teardown          # deletes the Codespace
cs-proxy start             # creates a new one with a fresh IP
cs-tools ipcheck          # new exit IP
```

## Scripted Rotation

```python
from csproxy import SSHTunnel, Config, GitHubManager, CodespaceSelector
import time

config = Config()
gh = GitHubManager()

for i in range(5):
    # Create a new codespace
    selector = CodespaceSelector(gh, config)
    cs_name = selector.select()

    # Start tunnel
    tunnel = SSHTunnel(config, cs_name)
    tunnel.start()
    time.sleep(3)

    # Do your work here
    print(f"Rotation {i+1}: proxied through {cs_name}")

    # Tear down
    tunnel.stop()
    gh.run_gh_command(['codespace', 'delete', '--codespace', cs_name, '-f'])
    time.sleep(5)
```

## Circuit Breaker

Tunnels have built-in circuit-breaker protection. If a tunnel fails 3 consecutive health checks (e.g. the Codespace was deleted or the SSH relay is down), it is automatically marked as `dead` and stops retrying. This prevents infinite reconnection loops.

Reset a dead tunnel with:

```bash
cs-proxy restart
```

## Tips

- Codespace creation takes 30-60 seconds. Factor this into your rotation timing.
- GitHub's free tier includes 120 core-hours/month. A 2-core Codespace gives you 60 hours.
- The free tier allows multiple codespaces. Use `-n 2` to pre-create both.
- Codespaces that sit idle are automatically stopped after 30 minutes, saving billing.
- Use `cs-proxy teardown` (not just `stop`) to fully delete and free resources.
