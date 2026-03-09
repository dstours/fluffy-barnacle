# Proxy Rotation

Rotate your egress IP by cycling GitHub Codespaces. Each Codespace gets a fresh IP from GitHub's Azure infrastructure.

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

## Tips

- Codespace creation takes 30-60 seconds. Factor this into your rotation timing.
- GitHub's free tier includes 120 core-hours/month. A 2-core Codespace gives you 60 hours.
- The free tier allows a maximum of 2 codespaces. Use `-n 2` to pre-create both.
- Codespaces that sit idle are automatically stopped after 30 minutes, saving billing.
- Use `cs-proxy teardown` (not just `stop`) to fully delete and free resources.
