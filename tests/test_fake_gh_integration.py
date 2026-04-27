#!/usr/bin/env python3
"""
Integration-style CLI tests that exercise subprocess boundaries with a fake gh.
"""

import os
import textwrap


def _install_fake_gh(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import sys

            args = sys.argv[1:]

            if args[:2] == ["auth", "status"]:
                sys.exit(0)

            if args[:2] == ["codespace", "list"]:
                if "--json" in args:
                    print(json.dumps([
                        {
                            "name": "fake-eu",
                            "state": "Available",
                            "repository": "owner/repo",
                            "createdAt": "2026-01-01T00:00:00Z",
                        }
                    ]))
                else:
                    print("fake-eu")
                sys.exit(0)

            print(f"unexpected gh args: {args}", file=sys.stderr)
            sys.exit(2)
            """
        )
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ.get('PATH', '')}")
    return gh


def test_cs_proxy_list_uses_fake_gh(tmp_path, monkeypatch, capsys):
    from csproxy.cli import main_proxy

    _install_fake_gh(tmp_path, monkeypatch)

    result = main_proxy(["list"])

    captured = capsys.readouterr()
    assert result == 0
    assert "fake-eu" in captured.out
    assert "owner/repo" in captured.out
