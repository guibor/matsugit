"""Read legacy installation state without moving or deleting user data."""
import os
from pathlib import Path


def env(name, default=None):
    """New environment names win; existing launchers keep working."""
    return os.environ.get(name, os.environ.get(name.replace('MATSUGIT_', 'FOLIOFORGE_'), default))


def existing(new, old):
    """Prefer the new path unless only the legacy location exists."""
    new, old = Path(new).expanduser(), Path(old).expanduser()
    return old if not new.exists() and old.exists() else new


def global_config():
    explicit = env('MATSUGIT_CONFIG')
    if explicit:
        return [Path(explicit).expanduser()]
    return [Path('~/.config/folioforge/config.json').expanduser(),
            Path('~/.config/matsugit/config.json').expanduser()]
