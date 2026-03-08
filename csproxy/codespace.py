#!/usr/bin/env python3
"""
Codespace selection and lifecycle management.

Provides interactive Codespace selection, creation, and state management.
Extracted from proxy.py for modularity.
"""

import time

from .github import GitHubManager
from .utils import Config, get_logger


class CodespaceSelector:
    """
    Interactive Codespace selection and lifecycle management.

    Equivalent to select_codespace(), create_codespace(), start_codespace()
    in cs-proxy.sh.
    """

    BLANK_REPO = "github/codespaces-blank"
    DEFAULT_MACHINE = "standardLinux32gb"
    READY_TIMEOUT_SECS = 180  # 60 attempts x 3s each

    LOCATIONS = [
        ('EastUs',        'US East'),
        ('WestUs2',       'US West'),
        ('WestEurope',    'Europe West'),
        ('SouthEastAsia', 'Southeast Asia'),
    ]

    def __init__(self, gh: GitHubManager, config: Config):
        self.gh = gh
        self.config = config
        self.logger = get_logger()

    def select(self) -> str:
        """Select or create a Codespace."""
        if self.config.codespace_name:
            self.logger.debug(f"Using configured Codespace: {self.config.codespace_name}")
            return self.config.codespace_name

        codespaces = self.gh.list_codespaces()

        if len(codespaces) == 0:
            self.logger.info("No Codespaces found. Creating one...")
            return self._create_interactively()
        elif len(codespaces) == 1:
            name = codespaces[0]['name']
            self.logger.info(f"Auto-selected Codespace: {name}")
            return name
        else:
            return self._prompt_selection(codespaces)

    def _create_interactively(self) -> str:
        """Prompt user for repo and create a new Codespace."""
        print(f"\nEnter repository (owner/repo, or press Enter for {self.BLANK_REPO}):")
        repo = input("> ").strip() or self.BLANK_REPO

        location = self.config.location
        if not location:
            print("\nSelect region (or press Enter for no preference):")
            for i, (value, label) in enumerate(self.LOCATIONS, 1):
                print(f"  {i}) {value:<16} ({label})")
            choice = input("> ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(self.LOCATIONS):
                    location = self.LOCATIONS[idx][0]

        return self._create_and_wait(repo, location=location)

    def _get_machine_types(self, repo: str) -> list:
        """Query available machine types for a repository."""
        result = self.gh.run_gh_command(
            ['api', f'/repos/{repo}/codespaces/machines',
             '--jq', '[.machines[].name] | join(" ")'],
            check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split()
        return [self.DEFAULT_MACHINE, 'standardLinux32gb', 'basicLinux32gb']

    def _create_and_wait(self, repo: str, location: str = '') -> str:
        """Create a Codespace and wait until it's available."""
        location = location or self.config.location
        loc_display = f" in {location}" if location else ""
        self.logger.info(f"Creating Codespace from {repo}{loc_display} (this may take a minute)...")

        machine_types = self._get_machine_types(repo)
        self.logger.debug(f"Available machine types: {machine_types}")

        result = None
        for machine in machine_types:
            args = ['codespace', 'create', '-R', repo, '-m', machine]
            if location:
                args += ['-l', location]
            result = self.gh.run_gh_command(args, check=False)
            if result.returncode == 0:
                break
            self.logger.debug(f"Machine type {machine!r} failed, trying next...")

        if result is None or result.returncode != 0:
            raise RuntimeError(
                f"Codespace creation failed. "
                f"Try manually: gh codespace create -R {repo}"
            )

        name = result.stdout.strip()

        if not name:
            time.sleep(2)
            codespaces = self.gh.list_codespaces()
            if codespaces:
                codespaces_sorted = sorted(codespaces, key=lambda x: x.get('createdAt', ''), reverse=True)
                name = codespaces_sorted[0]['name']

        if not name:
            raise RuntimeError("Failed to get Codespace name. Check: gh codespace list")

        self.logger.info(f"Created Codespace: {name}")
        self._wait_until_available(name)
        return name

    def _wait_until_available(self, name: str) -> None:
        """Wait for a Codespace to reach 'Available' state."""
        self.logger.info("Waiting for Codespace to be available...")

        start = time.time()
        while time.time() - start < self.READY_TIMEOUT_SECS:
            result = self.gh.run_gh_command(
                ['codespace', 'list', '--json', 'name,state',
                 '-q', f'.[] | select(.name=="{name}") | .state'],
                check=False
            )

            state = result.stdout.strip() or 'Unknown'

            if state == 'Available':
                self.logger.info("Codespace is ready!")
                return
            elif state == 'Shutdown':
                self.logger.info("Starting Codespace...")
                self.gh.run_gh_command(['codespace', 'start', '--codespace', name], check=False)
            else:
                self.logger.debug(f"Codespace state: {state}")

            time.sleep(3)

        raise TimeoutError(f"Codespace '{name}' did not become available within {self.READY_TIMEOUT_SECS}s")

    def _prompt_selection(self, codespaces: list) -> str:
        """Prompt user to select from multiple Codespaces."""
        self.logger.info("Available Codespaces:")
        print()
        for i, cs in enumerate(codespaces, 1):
            name = cs.get('name', 'unknown')
            state = cs.get('state', 'unknown')
            repo = cs.get('repository', 'unknown')
            print(f"  {i}) {name:<40} {state:<15} {repo}")
        print()

        selection = input("Enter number, name, or press Enter for most recent: ").strip()

        if not selection:
            sorted_cs = sorted(codespaces, key=lambda x: x.get('createdAt', ''), reverse=True)
            name = sorted_cs[0]['name']
            self.logger.info(f"Using most recent: {name}")
            return name
        elif selection.isdigit():
            idx = int(selection) - 1
            if 0 <= idx < len(codespaces):
                return codespaces[idx]['name']
            raise ValueError(f"Invalid selection: {selection}")
        else:
            return selection

    def ensure_running(self, name: str) -> None:
        """Ensure a Codespace is in 'Available' state, starting it if needed."""
        result = self.gh.run_gh_command(
            ['codespace', 'list', '--json', 'name,state',
             '-q', f'.[] | select(.name=="{name}") | .state'],
            check=False
        )

        state = result.stdout.strip() or 'NotFound'

        if state == 'Available':
            self.logger.debug("Codespace already running")
            return
        elif state in ('Shutdown', 'Starting'):
            self.logger.info("Starting Codespace...")
            self.gh.run_gh_command(['codespace', 'start', '--codespace', name])
            time.sleep(10)
        elif state == 'NotFound':
            raise RuntimeError(f"Codespace '{name}' not found")
        else:
            self.logger.warning(f"Codespace in state: {state}")
