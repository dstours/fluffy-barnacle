#!/usr/bin/env python3
"""
Shared subprocess runner for cs-proxy.

Centralizes command execution so CLI features can share timeout handling,
environment injection, logging, and dry-run behavior.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from .utils.logging import get_logger


@dataclass
class CommandRunner:
    """Small wrapper around subprocess.run with cs-proxy defaults."""

    default_timeout: int = 30
    dry_run: bool = False
    base_env: Optional[Mapping[str, str]] = None
    redacted_values: Sequence[str] = field(default_factory=tuple)

    def _merged_env(self, env: Optional[Mapping[str, str]] = None) -> Optional[dict[str, str]]:
        if self.base_env is None and env is None:
            return None
        merged = dict(os.environ)
        if self.base_env:
            merged.update(self.base_env)
        if env:
            merged.update(env)
        return merged

    def _display_cmd(self, cmd: Sequence[str]) -> str:
        parts = []
        redacted = {v for v in self.redacted_values if v}
        for part in cmd:
            parts.append("***" if part in redacted else str(part))
        return " ".join(parts)

    def run(
        self,
        cmd: Sequence[str],
        *,
        check: bool = False,
        capture_output: bool = True,
        text: bool = True,
        timeout: Optional[int] = None,
        env: Optional[Mapping[str, str]] = None,
        input=None,
        **kwargs,
    ) -> subprocess.CompletedProcess:
        """Run a command with consistent defaults."""
        logger = get_logger()
        logger.debug(f"Running: {self._display_cmd(cmd)}")

        if self.dry_run:
            return subprocess.CompletedProcess(list(cmd), 0, stdout="", stderr="")

        return subprocess.run(
            list(cmd),
            check=check,
            capture_output=capture_output,
            text=text,
            timeout=self.default_timeout if timeout is None else timeout,
            env=self._merged_env(env),
            input=input,
            **kwargs,
        )

    def gh(self, args: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
        """Run a GitHub CLI command."""
        return self.run(["gh", *args], **kwargs)
