#!/usr/bin/env python3
"""
Shell completion script generator for cs-proxy.

Supports bash and zsh. Generated scripts are pure text with no runtime
dependencies — users source them in their shell rc file.
"""

BASH_COMPLETION = """#!/bin/bash
# cs-proxy bash completion
_cs_proxy_completion() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local opts="start stop restart status list create set http proxychains env burp keygen config logs split ssh run name teardown down delete rm token aliases completion pac help"
    COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
}
complete -F _cs_proxy_completion cs-proxy
"""

ZSH_COMPLETION = """#compdef cs-proxy
local -a subcmds
subcmds=(
    'start:Start the SOCKS5 proxy tunnel'
    'stop:Stop the proxy tunnel'
    'restart:Restart the proxy tunnel'
    'status:Show proxy and Codespace status'
    'list:List available Codespaces'
    'create:Create a new Codespace'
    'set:Set the default Codespace'
    'http:Start HTTP proxy'
    'proxychains:Generate proxychains configuration'
    'env:Show environment variable exports'
    'burp:Show Burp Suite configuration'
    'keygen:Generate SSH key'
    'config:Edit configuration'
    'logs:Show proxy logs'
    'split:Set up split tunneling'
    'ssh:Open SSH session in Codespace'
    'run:Run a command in Codespace'
    'name:Print current Codespace name'
    'teardown:Stop proxy and Codespace'
    'down:Alias for teardown'
    'delete:Delete Codespace'
    'rm:Alias for delete'
    'token:Set GitHub token'
    'aliases:Write shell aliases'
    'completion:Generate shell completion script'
    'pac:Generate Proxy Auto-Config'
    'help:Show help'
)
_describe 'command' subcmds
"""


def generate_completion(shell: str) -> str:
    """
    Generate a shell completion script.

    Args:
        shell: 'bash' or 'zsh'

    Returns:
        Completion script as a string.
    """
    shell = shell.lower().strip()
    if shell == "bash":
        return BASH_COMPLETION
    if shell in ("zsh",):
        return ZSH_COMPLETION
    return f"# Unsupported shell: {shell}. Supported: bash, zsh\n"
