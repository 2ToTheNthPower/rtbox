"""Distro definitions and metadata."""

from dataclasses import dataclass


@dataclass
class Distro:
    """Represents a Debian distribution."""

    name: str  # e.g., "bookworm"
    version: str  # e.g., "12"
    glibc_version: str  # e.g., "2.36"
    codename: str  # e.g., "bookworm"


# Debian distributions with their glibc versions
# These are the distros available from images.linuxcontainers.org
# Note: glibc versions are from the actual LXC images, which may differ
# slightly from the official Debian package versions
DISTROS: dict[str, Distro] = {
    "bullseye": Distro(
        name="bullseye",
        version="11",
        glibc_version="2.30",
        codename="bullseye",
    ),
    "bookworm": Distro(
        name="bookworm",
        version="12",
        glibc_version="2.36",
        codename="bookworm",
    ),
    "trixie": Distro(
        name="trixie",
        version="13",
        glibc_version="2.41",
        codename="trixie",
    ),
    "forky": Distro(
        name="forky",
        version="14",
        glibc_version="2.41",
        codename="forky",
    ),
}


def get_distro(name: str) -> Distro | None:
    """Get a distro by name or version number."""
    # Try direct lookup
    if name in DISTROS:
        return DISTROS[name]

    # Try by version number
    for distro in DISTROS.values():
        if distro.version == name:
            return distro

    return None


def list_distros() -> list[Distro]:
    """List all available distros."""
    return list(DISTROS.values())
