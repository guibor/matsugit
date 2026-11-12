"""Read legacy installation state without moving or deleting user data."""
import os
from pathlib import Path


def legacy_config():
    """Work distributions can disable old settings without deleting old data."""
    return os.environ.get('MATSUGIT_LEGACY_CONFIG', '1') != '0'


def env(name, default=None):
    """New environment names win; existing launchers keep working."""
    fallback = os.environ.get(name.replace('MATSUGIT_', 'FOLIOFORGE_'), default) if legacy_config() else default
    return os.environ.get(name, fallback)


def existing(new, old):
    """Prefer the new path unless only the legacy location exists."""
    new, old = Path(new).expanduser(), Path(old).expanduser()
    return old if not new.exists() and old.exists() else new


def global_config():
    explicit = env('MATSUGIT_CONFIG')
    if explicit:
        return [Path(explicit).expanduser()]
    old = [Path('~/.config/folioforge/config.json').expanduser()] if legacy_config() else []
    return [*old, Path('~/.config/matsugit/config.json').expanduser()]


def project_configs(root):
    return [*([root / 'folioforge.json'] if legacy_config() else []), root / 'matsugit.json']
