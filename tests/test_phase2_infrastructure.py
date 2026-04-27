#!/usr/bin/env python3
"""Shared infrastructure tests for command execution and account config."""

import subprocess
from unittest.mock import patch

import pytest


def test_command_runner_dry_run_returns_success_without_subprocess():
    from csproxy.runner import CommandRunner

    runner = CommandRunner(dry_run=True)

    with patch("subprocess.run") as mock_run:
        result = runner.run(["gh", "auth", "status"])

    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0
    mock_run.assert_not_called()


def test_command_runner_merges_env(monkeypatch):
    from csproxy.runner import CommandRunner

    monkeypatch.setenv("EXISTING", "1")
    runner = CommandRunner(base_env={"BASE": "2"})

    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as mock_run:
        runner.run(["echo", "ok"], env={"CALL": "3"})

    env = mock_run.call_args.kwargs["env"]
    assert env["EXISTING"] == "1"
    assert env["BASE"] == "2"
    assert env["CALL"] == "3"


def test_github_account_loads_from_config(monkeypatch, tmp_path):
    from csproxy.accounts import GitHubAccount
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    config.set("accounts", {"eu": {"token_env": "GH_TOKEN_EU", "gh_host": "github.com"}})
    monkeypatch.setenv("GH_TOKEN_EU", "secret")

    account = GitHubAccount.from_config(config, "eu")

    assert account.name == "eu"
    assert account.token_env == "GH_TOKEN_EU"
    assert account.token == "secret"


def test_github_account_rejects_missing_token_env(tmp_path):
    from csproxy.accounts import GitHubAccount
    from csproxy.utils.config import Config
    from csproxy.utils.errors import ConfigError

    config = Config(config_dir=tmp_path)
    config.set("accounts", {"bad": {}})

    with pytest.raises(ConfigError, match="missing token_env"):
        GitHubAccount.from_config(config, "bad")


def test_github_manager_uses_account_token(monkeypatch, tmp_path):
    from csproxy.accounts import GitHubAccount
    from csproxy.github import GitHubManager
    from csproxy.runner import CommandRunner

    monkeypatch.setenv("GH_TOKEN_EU", "secret")
    runner = CommandRunner()
    gh = GitHubManager(
        config_dir=tmp_path,
        account=GitHubAccount("eu", token_env="GH_TOKEN_EU"),
        runner=runner,
    )

    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as mock_run:
        assert gh.check_auth() is True

    assert mock_run.call_args.kwargs["env"]["GH_TOKEN"] == "secret"
