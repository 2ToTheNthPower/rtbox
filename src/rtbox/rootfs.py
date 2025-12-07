"""Rootfs management - download and extract Debian rootfs from LXC images."""

import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TransferSpeedColumn,
)

from rtbox.config import get_distro_rootfs, ensure_dirs
from rtbox.distros import Distro, get_distro, list_distros


console = Console()

# LXC image server base URL
LXC_IMAGE_SERVER = "https://images.linuxcontainers.org"


class RootfsError(Exception):
    """Error during rootfs operations."""

    pass


def _get_arch() -> str:
    """Get the current machine architecture in LXC format."""
    machine = platform.machine().lower()
    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "armhf",
        "ppc64le": "ppc64el",
        "s390x": "s390x",
    }
    return arch_map.get(machine, machine)


def _get_lxc_distro_name(distro_name: str) -> str:
    """Map our distro names to LXC distro names."""
    # LXC uses the same names for Debian codenames
    return distro_name


def _get_latest_image_path(distro_name: str, arch: str) -> str:
    """
    Get the path to the latest rootfs.tar.xz for a distro.

    Returns the full URL to the rootfs.tar.xz file.
    """
    lxc_name = _get_lxc_distro_name(distro_name)
    base_url = f"{LXC_IMAGE_SERVER}/images/debian/{lxc_name}/{arch}/default/"

    # Fetch the directory listing to find the latest build
    try:
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            response = client.get(base_url)
            response.raise_for_status()
    except httpx.HTTPError as e:
        raise RootfsError(
            f"Failed to fetch image list for {distro_name}: {e}"
        ) from e

    # Parse directory listing to find date directories
    # Format: 20251206_05:24/ (colon may be URL-encoded as %3A)
    content = response.text
    # Find all directory entries that look like dates
    # The colon may be either literal or URL-encoded
    date_pattern = r'href="(\d{8}_\d{2}(?::|%3A)\d{2})/"'
    matches = re.findall(date_pattern, content)
    # Normalize - replace %3A with :
    matches = [m.replace("%3A", ":") for m in matches]

    if not matches:
        raise RootfsError(
            f"No images found for {distro_name} on {arch}. "
            f"Check if the distro is available at {base_url}"
        )

    # Sort and get the latest, URL-encode the colon
    latest = sorted(matches)[-1]
    latest_encoded = latest.replace(":", "%3A")
    return f"{base_url}{latest_encoded}/rootfs.tar.xz"


def is_rootfs_installed(distro_name: str) -> bool:
    """Check if a rootfs is installed."""
    rootfs_path = get_distro_rootfs(distro_name)
    # Check for key directories that should exist in a rootfs
    return (rootfs_path / "lib").exists() or (rootfs_path / "lib64").exists()


def get_installed_rootfs() -> list[str]:
    """Get list of installed rootfs names."""
    return [d.name for d in list_distros() if is_rootfs_installed(d.name)]


def pull_rootfs(distro: Distro, force: bool = False) -> Path:
    """
    Pull a rootfs from the LXC image server.

    Downloads the rootfs.tar.xz from images.linuxcontainers.org and extracts it.
    No Docker or container runtime required.
    """
    ensure_dirs()
    rootfs_path = get_distro_rootfs(distro.name)

    if rootfs_path.exists() and not force:
        if is_rootfs_installed(distro.name):
            console.print(
                f"[yellow]Rootfs for {distro.name} already exists. Use --force to re-download.[/yellow]"
            )
            return rootfs_path
        # Directory exists but incomplete, remove it
        shutil.rmtree(rootfs_path)

    if force and rootfs_path.exists():
        shutil.rmtree(rootfs_path)

    rootfs_path.mkdir(parents=True, exist_ok=True)

    _pull_from_lxc(distro, rootfs_path)

    return rootfs_path


def _pull_from_lxc(distro: Distro, rootfs_path: Path) -> None:
    """Pull rootfs from LXC image server."""
    arch = _get_arch()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    ) as progress:
        # Find the latest image URL
        task = progress.add_task(
            f"Finding latest {distro.name} image for {arch}...", total=None
        )

        try:
            url = _get_latest_image_path(distro.name, arch)
        except RootfsError:
            raise

        progress.update(task, description=f"Downloading {distro.name} rootfs...")

        # Download the tarball
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".tar.xz", delete=False
            ) as tmp:
                tmp_path = tmp.name

            # Stream download with progress
            with httpx.Client(follow_redirects=True, timeout=300.0) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("content-length", 0))
                    progress.update(task, total=total)

                    with open(tmp_path, "wb") as f:
                        for chunk in response.iter_bytes(chunk_size=8192):
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))

            # Extract the tarball
            progress.update(
                task, description="Extracting rootfs...", total=None, completed=0
            )

            result = subprocess.run(
                ["tar", "-xJf", tmp_path, "-C", str(rootfs_path)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RootfsError(f"Failed to extract rootfs: {result.stderr}")

            progress.update(
                task, description=f"[green]Installed {distro.name}[/green]"
            )

        except httpx.HTTPError as e:
            raise RootfsError(f"Failed to download rootfs: {e}") from e
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)


def remove_rootfs(distro_name: str) -> bool:
    """Remove an installed rootfs."""
    rootfs_path = get_distro_rootfs(distro_name)
    if rootfs_path.exists():
        shutil.rmtree(rootfs_path)
        return True
    return False


def get_rootfs_info(distro_name: str) -> dict | None:
    """Get information about an installed rootfs."""
    rootfs_path = get_distro_rootfs(distro_name)
    if not is_rootfs_installed(distro_name):
        return None

    distro = get_distro(distro_name)
    if not distro:
        return None

    # Calculate size
    total_size = sum(f.stat().st_size for f in rootfs_path.rglob("*") if f.is_file())

    # Find the actual glibc version
    glibc_version = _detect_glibc_version(rootfs_path)

    return {
        "name": distro.name,
        "version": distro.version,
        "glibc_version": glibc_version or distro.glibc_version,
        "path": str(rootfs_path),
        "size_mb": total_size / (1024 * 1024),
    }


def _detect_glibc_version(rootfs_path: Path) -> str | None:
    """Detect the actual glibc version in a rootfs."""
    # Look for libc.so.6 and try to extract version
    lib_paths = [
        rootfs_path / "lib" / "x86_64-linux-gnu",
        rootfs_path / "lib64",
        rootfs_path / "lib",
        rootfs_path / "lib" / "aarch64-linux-gnu",
    ]

    for lib_path in lib_paths:
        libc = lib_path / "libc.so.6"
        if libc.exists():
            # Try to run the libc to get version (it prints version when executed)
            # This won't work on macOS, so we'll fall back to readelf or strings
            try:
                result = subprocess.run(
                    ["strings", str(libc)],
                    capture_output=True,
                    text=True,
                )
                for line in result.stdout.split("\n"):
                    if "GNU C Library" in line and "release version" in line:
                        # Extract version like "2.36"
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if part == "version":
                                return parts[i + 1].rstrip(",.")
                    elif line.startswith("glibc "):
                        return line.split()[1]
            except Exception:
                pass

    return None
