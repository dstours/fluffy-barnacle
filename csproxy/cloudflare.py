#!/usr/bin/env python3
"""
Cloudflare Worker management for cs-serve custom domain proxying.

Deploys and tears down Cloudflare Workers that reverse-proxy traffic
from a custom domain to a Codespace's app.github.dev URL.
"""

import json
import urllib.request
import urllib.error
from pathlib import Path

from .utils import get_logger

# Cloudflare API base URL
CF_API_BASE = "https://api.cloudflare.com/client/v4"

# Worker script template — {CODESPACE_URL} is replaced at deploy time
WORKER_SCRIPT_TEMPLATE = """\
export default {
  async fetch(request) {
    const url = new URL(request.url);
    url.hostname = "{CODESPACE_URL}";
    const newRequest = new Request(url.toString(), {
      method: request.method,
      headers: new Headers(request.headers),
      body: request.body,
      redirect: "follow"
    });
    newRequest.headers.set("Host", "{CODESPACE_URL}");
    return fetch(newRequest);
  },
};
"""


def generate_worker_script(codespace_url: str) -> str:
    """
    Generate a Cloudflare Worker script for the given Codespace URL.

    Args:
        codespace_url: The Codespace hostname (e.g., 'name-9999.app.github.dev')

    Returns:
        The complete Worker JavaScript source code.
    """
    return WORKER_SCRIPT_TEMPLATE.replace("{CODESPACE_URL}", codespace_url)


class CloudflareWorker:
    """Manages Cloudflare Worker deployment and teardown via REST API."""

    def __init__(self, api_token: str, account_id: str):
        """
        Args:
            api_token: Cloudflare API token with Workers permissions
            account_id: Cloudflare account ID
        """
        self.api_token = api_token
        self.account_id = account_id
        self.logger = get_logger()
        self._deployed_name = None

    def deploy(self, worker_name: str, codespace_url: str) -> str:
        """
        Deploy a Worker script that proxies to the Codespace URL.

        Args:
            worker_name: Name for the worker (e.g., 'cs-serve-9999')
            codespace_url: Target Codespace hostname

        Returns:
            The worker's default URL (worker_name.account-subdomain.workers.dev)
        """
        script = generate_worker_script(codespace_url)

        self.logger.info(f"Deploying Cloudflare Worker: {worker_name}")
        self.logger.info(f"  Target: {codespace_url}")

        self._api_request(
            "PUT",
            f"/accounts/{self.account_id}/workers/scripts/{worker_name}",
            data=script.encode("utf-8"),
            content_type="application/javascript",
        )

        self._deployed_name = worker_name
        self.logger.info(f"Worker deployed: {worker_name}")
        return worker_name

    def add_custom_domain(self, worker_name: str, domain: str) -> None:
        """
        Bind a custom domain to the deployed worker.

        The domain must be on a zone in the same Cloudflare account.

        Args:
            worker_name: Name of the deployed worker
            domain: Custom domain to bind (e.g., 'dev.example.com')
        """
        self.logger.info(f"Binding custom domain: {domain} -> {worker_name}")

        payload = {
            "hostname": domain,
            "service": worker_name,
            "environment": "production",
        }

        self._api_request(
            "PUT",
            f"/accounts/{self.account_id}/workers/domains",
            data=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
        )

        self.logger.info(f"Custom domain bound: {domain}")

    def teardown(self, worker_name: str = None) -> None:
        """
        Delete a Worker script from Cloudflare.

        Args:
            worker_name: Name of the worker to delete (defaults to last deployed)
        """
        name = worker_name or self._deployed_name
        if not name:
            return

        self.logger.info(f"Tearing down Cloudflare Worker: {name}")

        try:
            self._api_request(
                "DELETE",
                f"/accounts/{self.account_id}/workers/scripts/{name}",
            )
            self.logger.info(f"Worker deleted: {name}")
        except Exception as e:
            self.logger.warning(f"Failed to delete worker {name}: {e}")

        self._deployed_name = None

    def _api_request(self, method: str, endpoint: str,
                     data: bytes = None, content_type: str = None) -> dict:
        """
        Make an authenticated request to the Cloudflare API.

        Args:
            method: HTTP method (GET, PUT, POST, DELETE)
            endpoint: API path (e.g., '/accounts/{id}/workers/scripts/{name}')
            data: Request body bytes
            content_type: Content-Type header value

        Returns:
            Parsed JSON response (or empty dict for DELETE)

        Raises:
            urllib.error.HTTPError: On API errors
        """
        url = f"{CF_API_BASE}{endpoint}"
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.api_token}")

        if content_type:
            req.add_header("Content-Type", content_type)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                if body:
                    return json.loads(body)
                return {}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            self.logger.error(f"Cloudflare API error ({e.code}): {error_body}")
            raise


def setup_worker(codespace_url: str, domain: str, config) -> CloudflareWorker:
    """
    Deploy a Cloudflare Worker if credentials are available, otherwise
    generate the script and save it locally.

    Args:
        codespace_url: Target Codespace hostname (e.g., 'name-9999.app.github.dev')
        domain: Custom domain to bind
        config: Config object with Cloudflare credentials

    Returns:
        CloudflareWorker instance if deployed, None if script was generated only
    """
    logger = get_logger()
    api_token = config.get('cloudflare_api_token', '')
    account_id = config.get('cloudflare_account_id', '')

    port = codespace_url.split("-")[-1].split(".")[0]
    worker_name = f"cs-serve-{port}"

    if api_token and account_id:
        # Auto-deploy mode
        cf = CloudflareWorker(api_token, account_id)
        cf.deploy(worker_name, codespace_url)
        cf.add_custom_domain(worker_name, domain)
        return cf
    else:
        # Generate-only mode
        script = generate_worker_script(codespace_url)

        # Save to file
        script_path = Path("worker.js")
        script_path.write_text(script)

        logger.info(f"Worker script saved to: {script_path.absolute()}")
        print(f"\n{'=' * 60}")
        print("Cloudflare Worker Script (manual deployment)")
        print(f"{'=' * 60}\n")
        print("No Cloudflare credentials found. Set these environment variables")
        print("for automatic deployment:\n")
        print("  export CLOUDFLARE_API_TOKEN='your-api-token'")
        print("  export CLOUDFLARE_ACCOUNT_ID='your-account-id'\n")
        print(f"Worker script saved to: {script_path.absolute()}\n")
        print("Manual setup:")
        print("  1. Go to Cloudflare Dashboard > Workers & Pages > Create")
        print(f"  2. Name it '{worker_name}' and deploy")
        print("  3. Edit code, paste contents of worker.js, save and deploy")
        print(f"  4. Add custom domain: {domain}\n")
        print(f"{'=' * 60}\n")

        return None


def teardown_worker(port: int, config) -> None:
    """
    Tear down a Cloudflare Worker for the given port if credentials are available.

    Args:
        port: Port number (used to derive worker name cs-serve-{port})
        config: Config object with Cloudflare credentials
    """
    api_token = config.get('cloudflare_api_token', '')
    account_id = config.get('cloudflare_account_id', '')

    if not api_token or not account_id:
        return

    worker_name = f"cs-serve-{port}"
    cf = CloudflareWorker(api_token, account_id)
    cf.teardown(worker_name)
