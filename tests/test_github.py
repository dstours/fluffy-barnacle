"""Tests for GitHubManager codespace lifecycle helpers."""

from unittest.mock import MagicMock

import pytest

from csproxy.github import GitHubManager


def _gh(tmp_path):
    return GitHubManager(config_dir=tmp_path)


def _result(stdout="", stderr=""):
    return MagicMock(returncode=0, stdout=stdout, stderr=stderr)


def test_create_codespace_parses_name_and_never_passes_json(tmp_path):
    gh = _gh(tmp_path)
    gh.runner.run = MagicMock(return_value=_result(stdout="cautious-meme-abc123\n"))

    cs = gh.create_codespace(repo="owner/repo", machine="basicLinux32gb")

    assert cs == {"name": "cautious-meme-abc123"}
    cmd = gh.runner.run.call_args.args[0]
    # gh codespace create has no --json flag (only list/view do); never pass it.
    assert "--json" not in cmd
    assert cmd[:3] == ["gh", "codespace", "create"]
    assert "--repo" in cmd and "owner/repo" in cmd
    assert "--machine" in cmd and "basicLinux32gb" in cmd


def test_create_codespace_reads_name_from_stdout_only(tmp_path):
    gh = _gh(tmp_path)
    # gh prints billing/status banners to stderr; only stdout carries the name.
    gh.runner.run = MagicMock(
        return_value=_result(
            stdout="\nfriendly-name-xyz\n",
            stderr="✓ Codespaces usage for this repository is paid for by acme\n",
        )
    )

    cs = gh.create_codespace(repo="owner/repo")

    assert cs["name"] == "friendly-name-xyz"
    # No machine given -> default to a concrete machine (gh would otherwise
    # prompt interactively and fail with "no terminal" in a worker/CI).
    cmd = gh.runner.run.call_args.args[0]
    assert "--machine" in cmd and "basicLinux32gb" in cmd


def test_create_codespace_omits_machine_when_blank(tmp_path):
    gh = _gh(tmp_path)
    gh.runner.run = MagicMock(return_value=_result(stdout="tty-created-cs\n"))

    gh.create_codespace(repo="owner/repo", machine="")

    # Explicit empty machine opts out of the flag (caller has a TTY).
    assert "--machine" not in gh.runner.run.call_args.args[0]


def test_create_codespace_defaults_to_blank_repo_when_none(tmp_path):
    # With no repo, `gh codespace create` would auto-detect from cwd and fail
    # headlessly. Default to GitHub's blank template instead of guessing.
    gh = _gh(tmp_path)
    gh.runner.run = MagicMock(return_value=_result(stdout="blank-cs\n"))

    gh.create_codespace()

    cmd = gh.runner.run.call_args.args[0]
    assert "--repo" in cmd
    assert "github/codespaces-blank" in cmd


def test_create_codespace_raises_when_no_name(tmp_path):
    gh = _gh(tmp_path)
    gh.runner.run = MagicMock(return_value=_result(stdout="\n   \n"))

    with pytest.raises(RuntimeError):
        gh.create_codespace(repo="owner/repo")
