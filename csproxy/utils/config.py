#!/usr/bin/env python3
"""
Configuration management for cs-proxy toolkit.

Provides YAML-based configuration with defaults, validation, profiles,
and environment variable overrides.
"""

import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, List, Optional

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from .errors import ConfigError
from .logging import get_logger


@dataclass
class _ConfigData:
    """Typed configuration schema with validation."""

    socks_port: int = 1080
    http_proxy_port: int = 8080
    num_proxies: int = 1
    codespace_name: str = ""
    reconnect_delay: int = 5
    max_reconnect_delay: int = 300
    dns_proxy: bool = False
    verbose: bool = False
    cloudflare_api_token: str = ""
    cloudflare_account_id: str = ""
    locations: List[str] = field(default_factory=list)
    codespace_names: List[str] = field(default_factory=list)
    profile: str = ""
    profiles: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "_ConfigData":
        """Build from a raw dict, merging active profile if set."""
        profile_name = raw.get("profile", "")
        profiles = raw.get("profiles", {})
        if profile_name and profile_name in profiles:
            merged = {**raw, **profiles[profile_name]}
        else:
            merged = raw
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in merged.items() if k in known}
        return cls(**clean)

    def __post_init__(self) -> None:
        if not 1024 <= self.socks_port <= 65535:
            raise ValueError(f"socks_port must be 1024-65535, got {self.socks_port}")
        if not 1024 <= self.http_proxy_port <= 65535:
            raise ValueError(
                f"http_proxy_port must be 1024-65535, got {self.http_proxy_port}"
            )
        if not 1 <= self.num_proxies <= 5:
            raise ValueError(f"num_proxies must be 1-5, got {self.num_proxies}")
        if self.reconnect_delay < 1:
            raise ValueError(f"reconnect_delay must be >= 1, got {self.reconnect_delay}")
        if self.max_reconnect_delay < self.reconnect_delay:
            raise ValueError("max_reconnect_delay must be >= reconnect_delay")

    def set_field(self, key: str, value: Any) -> None:
        """Set a field with full schema re-validation."""
        if not hasattr(self, key):
            raise KeyError(f"Unknown config key: {key}")
        temp = asdict(self)
        temp[key] = value
        validated = _ConfigData(**temp)
        for f in fields(self):
            setattr(self, f.name, getattr(validated, f.name))


class Config:
    """
    Configuration manager for cs-proxy.

    Backed by a dataclass schema for validation, with YAML persistence,
    environment variable overrides, and profile support.
    """

    DEPRECATED_KEYS = {"chain"}
    DEFAULTS = {
        "socks_port": 1080,
        "http_proxy_port": 8080,
        "num_proxies": 1,
        "codespace_name": "",
        "reconnect_delay": 5,
        "max_reconnect_delay": 300,
        "dns_proxy": False,
        "verbose": False,
        "cloudflare_api_token": "",
        "cloudflare_account_id": "",
        "locations": [],
        "codespace_names": [],
        "profile": "",
        "profiles": {},
    }

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        config_file: Optional[Path] = None,
    ):
        self.logger = get_logger()
        self.config_dir = config_dir or Path.home() / ".config" / "cs-proxy"
        if config_file:
            self.config_file = Path(config_file)
        else:
            self.config_file = self.config_dir / "config.yaml"

        self._data = _ConfigData()
        self._extra: dict = {}  # Unknown keys preserved across save/load

        if self.config_file.exists():
            self.load()
        else:
            self.logger.debug(f"Config file not found: {self.config_file}")

        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides to configuration."""
        env_mappings = {
            "SOCKS_PORT": ("socks_port", int),
            "HTTP_PROXY_PORT": ("http_proxy_port", int),
            "CODESPACE_NAME": ("codespace_name", str),
            "RECONNECT_DELAY": ("reconnect_delay", int),
            "MAX_RECONNECT_DELAY": ("max_reconnect_delay", int),
            "DNS_PROXY": ("dns_proxy", lambda x: x.lower() in ("true", "1", "yes")),
            "VERBOSE": ("verbose", lambda x: x.lower() in ("true", "1", "yes")),
            "NUM_PROXIES": ("num_proxies", int),
            "CLOUDFLARE_API_TOKEN": ("cloudflare_api_token", str),
            "CLOUDFLARE_ACCOUNT_ID": ("cloudflare_account_id", str),
            "LOCATIONS": ("locations", lambda x: [v.strip() for v in x.split(",") if v.strip()]),
        }

        for env_var, (config_key, converter) in env_mappings.items():
            value = os.environ.get(env_var)
            if value is not None:
                try:
                    setattr(self._data, config_key, converter(value))
                    self.logger.debug(f"Overriding {config_key} from environment: {value}")
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Invalid value for {env_var}: {value} ({e})")

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load configuration from YAML file."""
        if not YAML_AVAILABLE:
            self.logger.warning("PyYAML not installed, using defaults only")
            return

        try:
            with open(self.config_file, "r") as f:
                loaded = yaml.safe_load(f) or {}

            if not isinstance(loaded, dict):
                raise ConfigError(
                    f"Invalid config format (expected dict, got {type(loaded).__name__})",
                    config_file=str(self.config_file),
                )

            known = {f.name for f in fields(_ConfigData)}
            for key in loaded:
                if key in self.DEPRECATED_KEYS:
                    self.logger.warning(
                        f"Deprecated config key '{key}' will be ignored. "
                        f"Please remove it from {self.config_file}"
                    )
                elif key not in known:
                    self.logger.warning(f"Unknown config key: {key}")

            self._extra = {k: v for k, v in loaded.items() if k not in known}
            self._data = _ConfigData.from_dict(loaded)
            self.logger.debug(f"Loaded configuration from {self.config_file}")

        except FileNotFoundError:
            self.logger.debug(f"Config file not found: {self.config_file}")
        except yaml.YAMLError as e:
            raise ConfigError(
                f"Invalid YAML syntax: {e}", config_file=str(self.config_file)
            )
        except (OSError, PermissionError) as e:
            raise ConfigError(
                f"Cannot read config file: {e}", config_file=str(self.config_file)
            )
        except (ValueError, TypeError) as e:
            raise ConfigError(
                f"Invalid configuration value: {e}", config_file=str(self.config_file)
            )

    def save(self) -> None:
        """Save current configuration to YAML file."""
        if not YAML_AVAILABLE:
            raise ConfigError("PyYAML not installed, cannot save config")

        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            data_dict = asdict(self._data)
            data_dict.update(self._extra)
            with open(self.config_file, "w") as f:
                yaml.dump(data_dict, f, default_flow_style=False, sort_keys=False)
            self.config_file.chmod(0o600)
            self.logger.info(f"Configuration saved to {self.config_file}")
        except (OSError, PermissionError) as e:
            raise ConfigError(
                f"Cannot write config file: {e}", config_file=str(self.config_file)
            )

    # ------------------------------------------------------------------
    # Get / Set
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return getattr(self._data, key, default)

    def set(self, key: str, value: Any) -> None:
        """Set configuration value with validation."""
        try:
            self._data.set_field(key, value)
            self.logger.debug(f"Set {key} = {value}")
        except (KeyError, ValueError, TypeError) as e:
            self.logger.warning(f"Invalid config value for {key}: {e}")

    def to_dict(self) -> dict:
        """Get configuration as dictionary."""
        return asdict(self._data)

    def ensure_dirs(self) -> None:
        """Ensure all required directories exist."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.chmod(0o700)
        self.logger.debug(f"Ensured config directory: {self.config_dir}")

    # ------------------------------------------------------------------
    # Properties (backward-compatible API)
    # ------------------------------------------------------------------

    @property
    def socks_port(self) -> int:
        return self._data.socks_port

    @property
    def http_proxy_port(self) -> int:
        return self._data.http_proxy_port

    @property
    def codespace_name(self) -> str:
        return self._data.codespace_name

    @property
    def reconnect_delay(self) -> int:
        return self._data.reconnect_delay

    @property
    def max_reconnect_delay(self) -> int:
        return self._data.max_reconnect_delay

    @property
    def dns_proxy(self) -> bool:
        return self._data.dns_proxy

    @property
    def num_proxies(self) -> int:
        return self._data.num_proxies

    @property
    def verbose(self) -> bool:
        return self._data.verbose

    @property
    def locations(self) -> list:
        return self._data.locations

    @property
    def location(self) -> str:
        locs = self._data.locations
        return locs[0] if locs else ""

    @property
    def codespace_names(self) -> list:
        return self._data.codespace_names


def create_example_config(config_file: Path) -> None:
    """Create an example configuration file with comments and profiles."""
    example = """# cs-proxy configuration
# Copy to ~/.config/cs-proxy/config.yaml

# =============================================================================
# Proxy Settings
# =============================================================================

socks_port: 1080
http_proxy_port: 8080
num_proxies: 1

# =============================================================================
# Codespace Settings
# =============================================================================

codespace_name: ""
locations: []

# =============================================================================
# Connection Settings
# =============================================================================

reconnect_delay: 5
max_reconnect_delay: 300

# =============================================================================
# Advanced Settings
# =============================================================================

dns_proxy: false
verbose: false

# =============================================================================
# Profiles
# =============================================================================
#
# Profiles let you switch between preset configurations:
#   cs-proxy start --profile redteam
#
# profile: ""
# profiles:
#   redteam:
#     num_proxies: 2
#     locations: [WestEurope, EastUs]
#     socks_port: 1080
#   stealth:
#     dns_proxy: true
#     verbose: true
"""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(example)
    get_logger().info(f"Created example config: {config_file}")
