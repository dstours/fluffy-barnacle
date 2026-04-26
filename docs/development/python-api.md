# Python API

All cs-proxy functionality can be imported and used as a Python library.

## Package Exports

```python
import csproxy

# Core classes
csproxy.GitHubManager        # GitHub CLI integration
csproxy.SSHTunnel            # SSH SOCKS5 tunnel
csproxy.HTTPProxyManager     # HTTP proxy (tinyproxy)
csproxy.CodespaceSelector    # Codespace selection/creation
csproxy.ProxychainsConfig    # Proxychains config generation

# Tool wrappers
csproxy.check_proxy          # Verify proxy is running
csproxy.ipcheck              # Compare direct vs proxied IP
csproxy.pcurl                # curl with SOCKS5
csproxy.pwget                # wget via proxychains
csproxy.pnmap                # nmap TCP connect scan
csproxy.pnuclei              # nuclei with proxy
csproxy.pffuf                # ffuf with proxy
csproxy.phttpx               # httpx with proxy
csproxy.psqlmap              # sqlmap with proxy
csproxy.pcs                  # generic proxychains wrapper
csproxy.psub                 # subdomain enumeration
csproxy.pportscan            # quick port scan

# Utilities
csproxy.Config               # Configuration management
csproxy.setup_logger         # Initialize logging
csproxy.get_logger           # Get logger instance
csproxy.check_dependencies   # Verify external tools
csproxy.CSProxyError         # Base exception
```

## Examples

### Start a Proxy Tunnel

```python
from csproxy import SSHTunnel, Config, GitHubManager, CodespaceSelector

config = Config()
gh = GitHubManager()

# Select or create a codespace
selector = CodespaceSelector(gh, config)
cs_name = selector.select()

# Start the SOCKS5 tunnel
tunnel = SSHTunnel(config, cs_name)
tunnel.start()

print(f"Proxy running on 127.0.0.1:{config.socks_port}")
print(f"Exit IP: {tunnel.get_exit_ip()}")

# Stop when done
tunnel.stop()
```

### Run Tools Through the Proxy

```python
from csproxy import check_proxy, ipcheck, pcurl, pnmap

if check_proxy():
    # Show IP comparison
    ipcheck()

    # curl through proxy (default 30s timeout)
    pcurl(['https://ifconfig.me'])

    # nmap scan — incompatible flags (-sS, -sU, -O) are auto-removed
    pnmap(['-p', '80,443', 'target.com'])

    # Override timeout for a slow scan
    pnmap(['-sV', '-p-', 'target.com'], timeout=900)
```

### Serve Files

```python
from csproxy.serve import serve_file, serve_redirect
from csproxy import GitHubManager

gh = GitHubManager()

# Serve a local file
serve_file('/path/to/payload.bin', port=9999, gh=gh)

# Start a redirect server
serve_redirect('http://169.254.169.254/', port=8888, gh=gh)
```

### Configuration

```python
from csproxy import Config

config = Config()

# Read settings
print(config.socks_port)       # 1080
print(config.codespace_name)   # ""

# Modify and save
config.set('socks_port', 9050)
config.save()

# Use custom config directory
config = Config(config_dir=Path('/tmp/cs-proxy-test'))
```

### Logging

```python
from csproxy import setup_logger, get_logger

# Initialize with verbose output
setup_logger(verbose=True)

# Get logger anywhere
logger = get_logger()
logger.info("Starting scan")
logger.debug("Detailed debug info")
```

### Dependency Checking

```python
from csproxy import check_dependencies

# Returns True if all required tools are available
if check_dependencies():
    print("All dependencies satisfied")
```

### Unified Proxy Environment

For tools with native proxy support, build an environment dict with SOCKS5 variables:

```python
from csproxy.tools import _proxy_env

env = _proxy_env('127.0.0.1', 1080)
# env contains: ALL_PROXY, HTTP_PROXY, HTTPS_PROXY, SOCKS_PROXY
```
