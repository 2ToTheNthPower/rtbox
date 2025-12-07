"""
Integration tests for rtbox.

These tests verify rtbox functionality. Some tests require Linux to fully work.
"""

import platform
import subprocess
import sys

from rtbox.config import get_distro_rootfs, get_rtbox_home
from rtbox.distros import get_distro, list_distros
from rtbox.rootfs import (
    _detect_glibc_version,
    get_rootfs_info,
    is_rootfs_installed,
    pull_rootfs,
    remove_rootfs,
)
from rtbox.runtime import find_ld_linux, get_lib_paths


def test_distros():
    """Test distro listing and lookup."""
    print("=== Test: Distro listing ===")
    distros = list_distros()
    assert len(distros) >= 4, f"Expected at least 4 distros, got {len(distros)}"
    print(f"  Found {len(distros)} distros")

    # Test lookup by name
    bookworm = get_distro("bookworm")
    assert bookworm is not None
    assert bookworm.glibc_version == "2.36"
    print(f"  bookworm lookup: OK (glibc {bookworm.glibc_version})")

    # Test lookup by version
    d12 = get_distro("12")
    assert d12 is not None
    assert d12.name == "bookworm"
    print("  version lookup: OK")

    print("  PASSED\n")


def test_pull_rootfs():
    """Test pulling a rootfs."""
    print("=== Test: Pull rootfs ===")
    distro = get_distro("bookworm")
    assert distro is not None

    # Pull (may already exist)
    rootfs_path = pull_rootfs(distro, force=False)
    assert rootfs_path.exists()
    print(f"  Rootfs path: {rootfs_path}")

    # Verify it's installed
    assert is_rootfs_installed("bookworm")
    print("  is_rootfs_installed: OK")

    print("  PASSED\n")


def test_rootfs_structure():
    """Test that the rootfs has the expected structure."""
    print("=== Test: Rootfs structure ===")

    if not is_rootfs_installed("bookworm"):
        print("  SKIPPED (bookworm not installed)\n")
        return

    rootfs = get_distro_rootfs("bookworm")

    # Check for essential directories
    essential_dirs = ["lib", "usr", "etc", "bin"]
    for d in essential_dirs:
        path = rootfs / d
        assert path.exists(), f"Missing directory: {d}"
    print("  Essential directories: OK")

    # Check for ld-linux
    ld = find_ld_linux(rootfs)
    assert ld is not None, "ld-linux not found"
    assert ld.exists(), f"ld-linux does not exist: {ld}"
    print(f"  ld-linux: {ld.name}")

    # Check for library paths
    lib_paths = get_lib_paths(rootfs)
    assert len(lib_paths) > 0, "No library paths found"
    print(f"  Library paths: {len(lib_paths)}")

    # Check for libc.so.6
    libc_found = False
    for lp in lib_paths:
        if (lp / "libc.so.6").exists():
            libc_found = True
            break
    assert libc_found, "libc.so.6 not found"
    print("  libc.so.6: OK")

    # Detect glibc version
    glibc_ver = _detect_glibc_version(rootfs)
    assert glibc_ver == "2.36", f"Expected glibc 2.36, got {glibc_ver}"
    print(f"  glibc version: {glibc_ver}")

    print("  PASSED\n")


def test_rootfs_info():
    """Test rootfs info command."""
    print("=== Test: Rootfs info ===")

    if not is_rootfs_installed("bookworm"):
        print("  SKIPPED (bookworm not installed)\n")
        return

    info = get_rootfs_info("bookworm")
    assert info is not None
    assert info["name"] == "bookworm"
    assert info["version"] == "12"
    assert info["glibc_version"] == "2.36"
    assert info["size_mb"] > 0
    print(f"  Name: {info['name']}")
    print(f"  Version: {info['version']}")
    print(f"  glibc: {info['glibc_version']}")
    print(f"  Size: {info['size_mb']:.1f} MB")

    print("  PASSED\n")


def test_run_binary_linux():
    """Test running a binary with rtbox (Linux only)."""
    print("=== Test: Run binary (Linux only) ===")

    if platform.system() != "Linux":
        print("  SKIPPED (not on Linux)\n")
        return

    if not is_rootfs_installed("bookworm"):
        print("  SKIPPED (bookworm not installed)\n")
        return

    # Try running /bin/true from the rootfs
    result = subprocess.run(
        [sys.executable, "-m", "rtbox", "run", "bookworm", "/bin/true"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Failed: {result.stderr}"
    print("  /bin/true: OK")

    # Try running ls
    result = subprocess.run(
        [sys.executable, "-m", "rtbox", "run", "bookworm", "/bin/ls", "/"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Failed: {result.stderr}"
    assert "bin" in result.stdout
    assert "lib" in result.stdout
    print("  /bin/ls /: OK")

    # Test that we're actually using the rootfs glibc
    # Run ldd on a binary to see which libraries it uses
    result = subprocess.run(
        [sys.executable, "-m", "rtbox", "run", "bookworm", "/usr/bin/ldd", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        assert "2.36" in result.stdout or "2.36" in result.stderr
        print("  ldd --version shows glibc 2.36: OK")

    print("  PASSED\n")


def test_cli_commands():
    """Test CLI commands work."""
    print("=== Test: CLI commands ===")

    # Test list
    result = subprocess.run(
        [sys.executable, "-m", "rtbox", "list"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"list failed: {result.stderr}"
    assert "bookworm" in result.stdout
    print("  rtbox list: OK")

    # Test info (if installed)
    if is_rootfs_installed("bookworm"):
        result = subprocess.run(
            [sys.executable, "-m", "rtbox", "info", "bookworm"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"info failed: {result.stderr}"
        assert "2.36" in result.stdout
        print("  rtbox info bookworm: OK")

    # Test shell-wrapper (if installed)
    if is_rootfs_installed("bookworm"):
        result = subprocess.run(
            [sys.executable, "-m", "rtbox", "shell-wrapper", "bookworm"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"shell-wrapper failed: {result.stderr}"
        assert "LD_LIBRARY_PATH" in result.stdout
        assert "rtbox_run" in result.stdout
        print("  rtbox shell-wrapper bookworm: OK")

    print("  PASSED\n")


def main():
    print(f"\nrtbox Integration Tests")
    print(f"Platform: {platform.system()} {platform.machine()}")
    print(f"Python: {sys.version.split()[0]}")
    print("=" * 50 + "\n")

    tests = [
        test_distros,
        test_pull_rootfs,
        test_rootfs_structure,
        test_rootfs_info,
        test_cli_commands,
        test_run_binary_linux,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  FAILED: {e}\n")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}\n")
            failed += 1

    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")

    if platform.system() != "Linux":
        print("\nNote: Run these tests on Linux to fully verify binary execution.")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
