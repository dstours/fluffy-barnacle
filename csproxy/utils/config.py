#!/usr/bin/env python3
"""
Configuration management for cs-proxy toolkit.

Provides YAML-based configuration with defaults and environment variable
overrides, replacing shell variable sourcing from Bash config files.
"""

import os
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from .errors import ConfigError
from .logging import get_logger


class Config:
    """
    Configuration manager for cs-proxy.

    Handles loading from YAML files, environment variables, and provides
    default values. Supports both reading and writing configuration.
    """

    # Default configuration values
    DEFAULTS = {
        # Proxy settings
        'socks_port': 1080,
        'http_proxy_port': 8080,
        'num_proxies': 1,

        # Codespace settings
        'codespace_name': '',

        # Connection settings
        'reconnect_delay': 5,
        'max_reconnect_delay': 300,

        # Advanced settings
        'dns_proxy': False,
        'verbose': False,

        # Cloudflare Worker settings
        'cloudflare_api_token': '',
        'cloudflare_account_id': '',

        # Codespace creation settings
        'locations': [],

        # Tracked managed codespaces (all names, not just the active tunnel)
        'codespace_names': [],
    }

    def __init__(self, config_dir: Optional[Path] = None, config_file: Optional[Path] = None):
        """
        Initialize configuration manager.

        Args:
            config_dir: Configuration directory (default: ~/.config/cs-proxy)
            config_file: Configuration file path (default: config_dir/config.yaml)
        """
        self.logger = get_logger()

        # Set configuration directory
        self.config_dir = config_dir or Path.home() / '.config' / 'cs-proxy'

        # Set configuration file
        if config_file:
            self.config_file = Path(config_file)
        else:
            self.config_file = self.config_dir / 'config.yaml'

        # Initialize with defaults
        self._config = self.DEFAULTS.copy()

        # Load from file if exists
        if self.config_file.exists():
            self.load()
        else:
            self.logger.debug(f"Config file not found: {self.config_file}")

        # Apply environment variable overrides
        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides to configuration."""
        env_mappings = {
            'SOCKS_PORT': ('socks_port', int),
            'HTTP_PROXY_PORT': ('http_proxy_port', int),
            'CODESPACE_NAME': ('codespace_name', str),
            'RECONNECT_DELAY': ('reconnect_delay', int),
            'MAX_RECONNECT_DELAY': ('max_reconnect_delay', int),
            'DNS_PROXY': ('dns_proxy', lambda x: x.lower() in ('true', '1', 'yes')),
            'VERBOSE': ('verbose', lambda x: x.lower() in ('true', '1', 'yes')),
            'NUM_PROXIES': ('num_proxies', int),
            'CLOUDFLARE_API_TOKEN': ('cloudflare_api_token', str),
            'CLOUDFLARE_ACCOUNT_ID': ('cloudflare_account_id', str),
            'LOCATIONS': ('locations', lambda x: [v.strip() for v in x.split(',') if v.strip()]),
        }

        for env_var, (config_key, converter) in env_mappings.items():
            value = os.environ.get(env_var)
            if value is not None:
                try:
                    self._config[config_key] = converter(value)
                    self.logger.debug(f"Overriding {config_key} from environment: {value}")
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Invalid value for {env_var}: {value} ({e})")

    def load(self) -> None:
        """
        Load configuration from YAML file.

        Raises:
            ConfigError: If configuration file is invalid or cannot be read
        """
        if not YAML_AVAILABLE:
            self.logger.warning("PyYAML not installed, using defaults only")
            return

        try:
            with open(self.config_file, 'r') as f:
                loaded = yaml.safe_load(f) or {}

            # Validate loaded config
            if not isinstance(loaded, dict):
                raise ConfigError(
                    f"Invalid config format (expected dict, got {type(loaded).__name__})",
                    config_file=str(self.config_file)
                )

            # Update config with loaded values
            for key, value in loaded.items():
                if key in self.DEFAULTS:
                    self._config[key] = value
                else:
                    self.logger.warning(f"Unknown config key: {key}")

            self.logger.debug(f"Loaded configuration from {self.config_file}")

        except FileNotFoundError:
            self.logger.debug(f"Config file not found: {self.config_file}")
        except yaml.YAMLError as e:
            raise ConfigError(
                f"Invalid YAML syntax: {e}",
                config_file=str(self.config_file)
            )
        except (OSError, PermissionError) as e:
            raise ConfigError(
                f"Cannot read config file: {e}",
                config_file=str(self.config_file)
            )

    def save(self) -> None:
        """
        Save current configuration to YAML file.

        Raises:
            ConfigError: If configuration cannot be saved
        """
        if not YAML_AVAILABLE:
            raise ConfigError("PyYAML not installed, cannot save config")

        try:
            # Ensure config directory exists
            self.config_dir.mkdir(parents=True, exist_ok=True)

            # Write configuration
            with open(self.config_file, 'w') as f:
                yaml.dump(self._config, f, default_flow_style=False, sort_keys=False)

            # Set secure permissions
            self.config_file.chmod(0o600)

            self.logger.info(f"Configuration saved to {self.config_file}")

        except (OSError, PermissionError) as e:
            raise ConfigError(
                f"Cannot write config file: {e}",
                config_file=str(self.config_file)
            )

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default

        Example:
            >>> config = Config()
            >>> port = config.get('socks_port')
            >>> print(port)
            1080
        """
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Set configuration value.

        Args:
            key: Configuration key
            value: Configuration value

        Example:
            >>> config = Config()
            >>> config.set('socks_port', 9050)
            >>> config.save()
        """
        self._config[key] = value
        self.logger.debug(f"Set {key} = {value}")

    def to_dict(self) -> dict:
        """
        Get configuration as dictionary.

        Returns:
            Configuration dictionary
        """
        return self._config.copy()

    def ensure_dirs(self) -> None:
        """
        Ensure all required directories exist.

        Creates:
            - Config directory (~/.config/cs-proxy)
        """
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.chmod(0o700)
        self.logger.debug(f"Ensured config directory: {self.config_dir}")

    @property
    def socks_port(self) -> int:
        """Get SOCKS5 proxy port."""
        return self._config['socks_port']

    @property
    def http_proxy_port(self) -> int:
        """Get HTTP proxy port."""
        return self._config['http_proxy_port']

    @property
    def codespace_name(self) -> str:
        """Get Codespace name."""
        return self._config['codespace_name']

    @property
    def reconnect_delay(self) -> int:
        """Get reconnect delay in seconds."""
        return self._config['reconnect_delay']

    @property
    def max_reconnect_delay(self) -> int:
        """Get maximum reconnect delay in seconds."""
        return self._config['max_reconnect_delay']

    @property
    def dns_proxy(self) -> bool:
        """Get DNS proxy setting."""
        return self._config['dns_proxy']

    @property
    def num_proxies(self) -> int:
        """Get number of proxy tunnels for round-robin."""
        return self._config.get('num_proxies', 1)

    @property
    def verbose(self) -> bool:
        """Get verbose logging setting."""
        return self._config['verbose']

    @property
    def locations(self) -> list:
        """Get preferred Codespace creation locations."""
        return self._config.get('locations', [])

    @property
    def location(self) -> str:
        """Get first preferred location, or empty string if none set."""
        locs = self.locations
        return locs[0] if locs else ''

    @property
    def codespace_names(self) -> list:
        """Get all managed Codespace names."""
        return self._config.get('codespace_names', [])

def create_example_config(config_file: Path) -> None:
    """
    Create an example configuration file with comments.

    Args:
        config_file: Path to create example config file

    Example:
        >>> from pathlib import Path
        >>> create_example_config(Path('config.example.yaml'))
    """
    example = """# cs-proxy configuration
# Copy to ~/.config/cs-proxy/config.yaml

# =============================================================================
# Proxy Settings
# =============================================================================

# SOCKS5 proxy port (default: 1080)
socks_port: 1080

# HTTP proxy port (default: 8080)
http_proxy_port: 8080

# =============================================================================
# Codespace Settings
# =============================================================================

# Default Codespace name (leave empty to select interactively)
codespace_name: ""

# =============================================================================
# Connection Settings
# =============================================================================

# Initial reconnection delay in seconds
reconnect_delay: 5

# Maximum reconnection delay (caps exponential backoff)
max_reconnect_delay: 300

# =============================================================================
# Advanced Settings
# =============================================================================

# Route DNS through proxy
dns_proxy: false

# Enable verbose logging
verbose: false
"""

    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(example)
    get_logger().info(f"Created example config: {config_file}")
