#!/usr/bin/env python3
"""
GitHub CLI and Codespace management functions.

Provides functions for GitHub authentication and Codespace operations,
replacing the functionality from lib/github.sh.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from .accounts import GitHubAccount
from .runner import CommandRunner
from .utils import GitHubAuthError, get_logger


class GitHubManager:
    """Manages GitHub CLI operations and authentication."""

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        *,
        account: Optional[GitHubAccount] = None,
        runner: Optional[CommandRunner] = None,
    ):
        """
        Initialize GitHub manager.

        Args:
            config_dir: Configuration directory (default: ~/.config/cs-proxy)
        """
        self.logger = get_logger()
        config_dir_override = os.environ.get('CS_PROXY_CONFIG_DIR')
        if config_dir is not None:
            self.config_dir = Path(config_dir)
        elif config_dir_override:
            self.config_dir = Path(config_dir_override).expanduser()
        else:
            self.config_dir = Path.home() / '.config' / 'cs-proxy'
        self.token_file = self.config_dir / 'gh_token'
        self._token = None
        self.account = account
        self.runner = runner or CommandRunner()

    def load_token(self) -> Optional[str]:
        """
        Load GitHub token from various sources.

        Priority:
            1. Environment variables (GH_TOKEN or GITHUB_TOKEN)
            2. Token file (~/.config/cs-proxy/gh_token)

        Returns:
            GitHub token if found, None otherwise
        """
        # Priority 1: Environment variables
        if self.account:
            token = self.account.token
            if token:
                self.logger.debug(
                    f"Using token from ${self.account.token_env} for account {self.account.name}"
                )
                self._token = token
                return token

        token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if token:
            self.logger.debug("Using GH_TOKEN from environment")
            self._token = token
            return token

        # Priority 2: Token file
        if self.token_file.exists():
            try:
                token = self.token_file.read_text().strip()
                if token:
                    self.logger.debug(f"Using GH_TOKEN from {self.token_file}")
                    self._token = token
                    return token
            except (OSError, PermissionError) as e:
                self.logger.warning(f"Could not read token file {self.token_file}: {e}")

        return None

    def save_token(self, token: str) -> None:
        """
        Save GitHub token to file.

        Args:
            token: GitHub personal access token

        Raises:
            OSError: If token file cannot be written
        """
        try:
            # Ensure config directory exists
            self.config_dir.mkdir(parents=True, exist_ok=True)

            # Write token with secure permissions
            self.token_file.write_text(token)
            self.token_file.chmod(0o600)

            self.logger.info(f"Saved GitHub token to {self.token_file}")
            self._token = token

        except (OSError, PermissionError) as e:
            raise OSError(f"Could not save token to {self.token_file}: {e}")

    def check_auth(self) -> bool:
        """
        Verify GitHub CLI authentication.

        Attempts to load token and verify authentication status.

        Returns:
            True if authenticated, False otherwise

        Raises:
            GitHubAuthError: If authentication fails and cannot be recovered
        """
        # Try to load token first
        token = self.load_token()

        # Set token in environment for gh CLI
        env = None
        if token:
            env = {'GH_TOKEN': token}

        # Check if we have valid auth
        try:
            result = self.runner.gh(
                ['auth', 'status'],
                capture_output=True,
                text=True,
                timeout=10,
                env=env,
            )

            if result.returncode == 0:
                self.logger.debug("GitHub CLI authenticated")
                return True

        except subprocess.TimeoutExpired:
            self.logger.error("GitHub auth check timed out")
        except FileNotFoundError:
            raise GitHubAuthError("GitHub CLI (gh) not found. Install from: https://cli.github.com/")

        # Authentication failed
        if token:
            self.logger.warning("GH_TOKEN is set but authentication failed")
            self.logger.warning("Check that your token has 'codespace' scope")
            self.logger.info("Create a new token at: https://github.com/settings/tokens/new")
            self.logger.info("Required scopes: codespace, repo (for private repos)")
            raise GitHubAuthError("Invalid or expired GitHub token")

        # No token, need interactive login
        self.logger.warning("GitHub CLI not authenticated")
        self.logger.info("Run: gh auth login")
        self.logger.info("Or set GH_TOKEN environment variable")
        raise GitHubAuthError("GitHub authentication required")

    def run_gh_command(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        """
        Run a GitHub CLI command.

        Args:
            args: Command arguments (e.g., ['codespace', 'list'])
            check: Raise exception on non-zero exit code (default: True)

        Returns:
            CompletedProcess instance

        Raises:
            subprocess.CalledProcessError: If command fails and check=True
            FileNotFoundError: If gh command not found

        Example:
            >>> gh = GitHubManager()
            >>> result = gh.run_gh_command(['codespace', 'list', '--json', 'name'])
            >>> codespaces = json.loads(result.stdout)
        """
        cmd = ['gh'] + args

        self.logger.debug(f"Running: {' '.join(cmd)}")

        try:
            env = None
            token = self.load_token()
            if token:
                env = {'GH_TOKEN': token}
            result = self.runner.run(
                cmd,
                capture_output=True,
                text=True,
                check=check,
                timeout=30,
                env=env,
            )
            return result

        except FileNotFoundError:
            raise FileNotFoundError("GitHub CLI (gh) not found. Install from: https://cli.github.com/")
        except subprocess.TimeoutExpired as e:
            self.logger.error(f"Command timed out: {' '.join(cmd)}")
            raise

    def list_codespaces(self) -> list[dict]:
        """
        List all Codespaces for the authenticated user.

        Returns:
            List of Codespace dictionaries with fields: name, state, repository, etc.

        Raises:
            subprocess.CalledProcessError: If gh command fails

        Example:
            >>> gh = GitHubManager()
            >>> codespaces = gh.list_codespaces()
            >>> for cs in codespaces:
            ...     print(f"{cs['name']}: {cs['state']}")
        """
        result = self.run_gh_command(['codespace', 'list', '--json', 'name,state,repository,createdAt'])
        return json.loads(result.stdout)

    def get_codespace(self, name: str) -> Optional[dict]:
        """
        Get information about a specific Codespace.

        Args:
            name: Codespace name

        Returns:
            Codespace dictionary if found, None otherwise

        Example:
            >>> gh = GitHubManager()
            >>> cs = gh.get_codespace('my-codespace')
            >>> if cs:
            ...     print(cs['state'])
        """
        codespaces = self.list_codespaces()
        for cs in codespaces:
            if cs['name'] == name:
                return cs
        return None

    def create_codespace(self, repo: Optional[str] = None, machine: str = '2-core') -> dict:
        """
        Create a new Codespace.

        Args:
            repo: Repository to create Codespace from (default: auto-detect)
            machine: Machine type (default: '2-core')

        Returns:
            Created Codespace information dictionary

        Raises:
            subprocess.CalledProcessError: If creation fails
        """
        args = ['codespace', 'create', '--machine', machine, '--json', 'name,state']

        if repo:
            args.extend(['--repo', repo])

        self.logger.info(f"Creating new Codespace (machine: {machine})...")
        result = self.run_gh_command(args)
        codespace = json.loads(result.stdout)

        self.logger.info(f"Created Codespace: {codespace['name']}")
        return codespace

    def delete_codespace(self, name: str, force: bool = False) -> None:
        """
        Delete a Codespace.

        Args:
            name: Codespace name
            force: Skip confirmation (default: False)

        Raises:
            subprocess.CalledProcessError: If deletion fails
        """
        args = ['codespace', 'delete', '--codespace', name]

        if force:
            args.append('--force')

        self.logger.info(f"Deleting Codespace: {name}")
        self.run_gh_command(args)
        self.logger.info(f"Deleted Codespace: {name}")

    def start_codespace(self, name: str) -> None:
        """
        Start a stopped Codespace.

        Args:
            name: Codespace name

        Raises:
            subprocess.CalledProcessError: If start fails
        """
        self.logger.info(f"Starting Codespace: {name}")
        self.run_gh_command(['api', f'/user/codespaces/{name}/start', '-X', 'POST'])

    def stop_codespace(self, name: str) -> None:
        """
        Stop a running Codespace.

        Args:
            name: Codespace name

        Raises:
            subprocess.CalledProcessError: If stop fails
        """
        self.logger.info(f"Stopping Codespace: {name}")
        self.run_gh_command(['codespace', 'stop', '--codespace', name])

    def ssh_command(self, name: str, command: Optional[list[str]] = None) -> subprocess.CompletedProcess:
        """
        Execute command via SSH in Codespace.

        Args:
            name: Codespace name
            command: Command to execute (default: None for interactive shell)

        Returns:
            CompletedProcess instance

        Raises:
            subprocess.CalledProcessError: If SSH command fails

        Example:
            >>> gh = GitHubManager()
            >>> result = gh.ssh_command('my-codespace', ['whoami'])
            >>> print(result.stdout)
        """
        args = ['codespace', 'ssh', '--codespace', name]

        if command:
            args.append('--')
            args.extend(command)

        return self.run_gh_command(args)
