"""
Integration tests for rtbox.

These tests verify rtbox functionality. Some tests require Linux to fully work.
"""

import platform
import subprocess
import sys

from rtbox.config import get_distro_rootfs, get_rtbox_home
from rtbox.distros import Distro, get_distro, list_distros
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
    assert bookworm.glibc_version is not None
    print(f"  bookworm lookup: OK (glibc {bookworm.glibc_version})")

    # Test lookup by version
    d12 = get_distro("12")
    assert d12 is not None
    assert d12.name == "bookworm"
    print("  version lookup: OK")

    print("  PASSED\n")


def test_pull_all_rootfs():
    """Test pulling all rootfs images."""
    print("=== Test: Pull all rootfs ===")
    distros = list_distros()

    for distro in distros:
        print(f"  Pulling {distro.name}...", end=" ", flush=True)
        rootfs_path = pull_rootfs(distro, force=False)
        assert rootfs_path.exists(), f"Rootfs path doesn't exist: {rootfs_path}"
        assert is_rootfs_installed(distro.name), f"Rootfs not installed: {distro.name}"
        print("OK")

    print("  PASSED\n")


def test_rootfs_structure_all():
    """Test that all rootfs have the expected structure."""
    print("=== Test: Rootfs structure (all distros) ===")
    distros = list_distros()

    for distro in distros:
        if not is_rootfs_installed(distro.name):
            print(f"  {distro.name}: SKIPPED (not installed)")
            continue

        rootfs = get_distro_rootfs(distro.name)

        # Check for essential directories
        essential_dirs = ["lib", "usr", "etc", "bin"]
        for d in essential_dirs:
            path = rootfs / d
            assert path.exists(), f"{distro.name}: Missing directory: {d}"

        # Check for ld-linux
        ld = find_ld_linux(rootfs)
        assert ld is not None, f"{distro.name}: ld-linux not found"
        assert ld.exists(), f"{distro.name}: ld-linux does not exist: {ld}"

        # Check for library paths
        lib_paths = get_lib_paths(rootfs)
        assert len(lib_paths) > 0, f"{distro.name}: No library paths found"

        # Check for libc.so.6
        libc_found = False
        for lp in lib_paths:
            if (lp / "libc.so.6").exists():
                libc_found = True
                break
        assert libc_found, f"{distro.name}: libc.so.6 not found"

        # Detect glibc version
        glibc_ver = _detect_glibc_version(rootfs)
        assert glibc_ver == distro.glibc_version, (
            f"{distro.name}: Expected glibc {distro.glibc_version}, got {glibc_ver}"
        )

        print(f"  {distro.name}: OK (glibc {glibc_ver}, ld-linux: {ld.name})")

    print("  PASSED\n")


def test_rootfs_info_all():
    """Test rootfs info for all distros."""
    print("=== Test: Rootfs info (all distros) ===")
    distros = list_distros()

    for distro in distros:
        if not is_rootfs_installed(distro.name):
            print(f"  {distro.name}: SKIPPED (not installed)")
            continue

        info = get_rootfs_info(distro.name)
        assert info is not None, f"{distro.name}: info is None"
        assert info["name"] == distro.name
        assert info["version"] == distro.version
        assert info["glibc_version"] == distro.glibc_version
        assert info["size_mb"] > 0

        print(
            f"  {distro.name}: OK (v{info['version']}, glibc {info['glibc_version']}, {info['size_mb']:.1f} MB)"
        )

    print("  PASSED\n")


def test_run_binary_all():
    """Test running binaries with all distros (Linux only)."""
    print("=== Test: Run binary (all distros) ===")

    if platform.system() != "Linux":
        print("  SKIPPED (not on Linux)\n")
        return

    distros = list_distros()

    for distro in distros:
        if not is_rootfs_installed(distro.name):
            print(f"  {distro.name}: SKIPPED (not installed)")
            continue

        # Try running /bin/true from the rootfs
        result = subprocess.run(
            [sys.executable, "-m", "rtbox", "run", distro.name, "/bin/true"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"{distro.name} /bin/true failed: {result.stderr}"
        )

        # Try running ls
        result = subprocess.run(
            [sys.executable, "-m", "rtbox", "run", distro.name, "/bin/ls", "/"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{distro.name} /bin/ls failed: {result.stderr}"
        assert "bin" in result.stdout, f"{distro.name}: 'bin' not in ls output"
        assert "lib" in result.stdout, f"{distro.name}: 'lib' not in ls output"

        # Verify glibc version via ldd
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "rtbox",
                "run",
                distro.name,
                "/usr/bin/ldd",
                "--version",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            output = result.stdout + result.stderr
            assert distro.glibc_version in output, (
                f"{distro.name}: Expected glibc {distro.glibc_version} in ldd output, got: {output[:200]}"
            )

        print(f"  {distro.name}: OK (glibc {distro.glibc_version})")

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
    for distro in list_distros():
        assert distro.name in result.stdout, f"{distro.name} not in list output"
    print("  rtbox list: OK")

    # Test info for all installed distros
    for distro in list_distros():
        if is_rootfs_installed(distro.name):
            result = subprocess.run(
                [sys.executable, "-m", "rtbox", "info", distro.name],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, f"info {distro.name} failed: {result.stderr}"
            assert distro.glibc_version in result.stdout
            print(f"  rtbox info {distro.name}: OK")

    # Test shell-wrapper for all installed distros
    for distro in list_distros():
        if is_rootfs_installed(distro.name):
            result = subprocess.run(
                [sys.executable, "-m", "rtbox", "shell-wrapper", distro.name],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, (
                f"shell-wrapper {distro.name} failed: {result.stderr}"
            )
            assert "LD_LIBRARY_PATH" in result.stdout
            assert "rtbox_run" in result.stdout
            print(f"  rtbox shell-wrapper {distro.name}: OK")

    print("  PASSED\n")


def main():
    print(f"\nrtbox Integration Tests")
    print(f"Platform: {platform.system()} {platform.machine()}")
    print(f"Python: {sys.version.split()[0]}")
    print("=" * 50 + "\n")

    tests = [
        test_distros,
        test_pull_all_rootfs,
        test_rootfs_structure_all,
        test_rootfs_info_all,
        test_cli_commands,
        test_run_binary_all,
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
