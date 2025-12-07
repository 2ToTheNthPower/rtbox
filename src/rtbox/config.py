"""Configuration and paths for rtbox."""

import os
from pathlib import Path


def get_rtbox_home() -> Path:
    """Get the rtbox home directory."""
    home = os.environ.get("RTBOX_HOME")
    if home:
        return Path(home)
    return Path.home() / ".rtbox"


def get_rootfs_dir() -> Path:
    """Get the directory where rootfs images are stored."""
    return get_rtbox_home() / "rootfs"


def get_distro_rootfs(distro_name: str) -> Path:
    """Get the rootfs path for a specific distro."""
    return get_rootfs_dir() / distro_name


def ensure_dirs() -> None:
    """Ensure all required directories exist."""
    get_rootfs_dir().mkdir(parents=True, exist_ok=True)
