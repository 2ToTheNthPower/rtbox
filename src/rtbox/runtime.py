"""Runtime execution - run binaries with a specific glibc version."""

import os
import subprocess
from pathlib import Path

from rtbox.config import get_distro_rootfs
from rtbox.distros import get_distro
from rtbox.rootfs import is_rootfs_installed


class RuntimeError(Exception):
    """Error during runtime execution."""

    pass


def find_ld_linux(rootfs_path: Path) -> Path | None:
    """Find the ld-linux dynamic linker in the rootfs."""
    # Common locations for ld-linux
    candidates = [
        # x86_64
        rootfs_path / "lib64" / "ld-linux-x86-64.so.2",
        rootfs_path / "lib" / "x86_64-linux-gnu" / "ld-linux-x86-64.so.2",
        # aarch64
        rootfs_path / "lib" / "ld-linux-aarch64.so.1",
        rootfs_path / "lib" / "aarch64-linux-gnu" / "ld-linux-aarch64.so.1",
        # Generic
        rootfs_path / "lib" / "ld-linux.so.2",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Try to find it with glob
    for pattern in ["lib*/ld-linux*.so*", "lib/*/ld-linux*.so*"]:
        matches = list(rootfs_path.glob(pattern))
        if matches:
            # Prefer .so.2 files
            for m in matches:
                if ".so.2" in m.name or ".so.1" in m.name:
                    return m
            return matches[0]

    return None


def get_lib_paths(rootfs_path: Path) -> list[Path]:
    """Get all library paths from the rootfs."""
    lib_paths = []

    # Standard library directories
    candidates = [
        rootfs_path / "lib",
        rootfs_path / "lib64",
        rootfs_path / "lib" / "x86_64-linux-gnu",
        rootfs_path / "lib" / "aarch64-linux-gnu",
        rootfs_path / "usr" / "lib",
        rootfs_path / "usr" / "lib64",
        rootfs_path / "usr" / "lib" / "x86_64-linux-gnu",
        rootfs_path / "usr" / "lib" / "aarch64-linux-gnu",
    ]

    for path in candidates:
        if path.exists() and path.is_dir():
            lib_paths.append(path)

    return lib_paths


def build_runtime_env(
    rootfs_path: Path,
    extra_lib_paths: list[str] | None = None,
    preserve_env: bool = True,
) -> dict[str, str]:
    """Build the environment for running with a different glibc."""
    env = dict(os.environ) if preserve_env else {}

    # Remove environment variables that can interfere with glibc/ld.so
    # These can cause crashes or unexpected behavior when using a different glibc
    problematic_vars = [
        "LD_PRELOAD",
        "LD_AUDIT",
        "LD_DEBUG",
        "LD_PROFILE",
        "LD_BIND_NOW",
        "LD_BIND_NOT",
        "LD_DYNAMIC_WEAK",
        "MALLOC_CHECK_",
        "MALLOC_PERTURB_",
        "MALLOC_MMAP_THRESHOLD_",
        "MALLOC_TRIM_THRESHOLD_",
        "MALLOC_TOP_PAD_",
        "MALLOC_MMAP_MAX_",
        "MALLOC_ARENA_MAX",
        "MALLOC_ARENA_TEST",
        "GLIBC_TUNABLES",
        "LIBC_FATAL_STDERR_",
        # Stack canary related - these can cause "stack smashing detected"
        # when the canary format differs between glibc versions
        "__GL_THREADED_OPTIMIZATIONS",
    ]
    for var in problematic_vars:
        env.pop(var, None)

    # Get library paths from the rootfs
    lib_paths = get_lib_paths(rootfs_path)
    lib_path_strs = [str(p) for p in lib_paths]

    # Add extra library paths if provided
    if extra_lib_paths:
        lib_path_strs.extend(extra_lib_paths)

    # Set LD_LIBRARY_PATH
    env["LD_LIBRARY_PATH"] = ":".join(lib_path_strs)

    # Set other relevant environment variables
    env["RTBOX_ROOTFS"] = str(rootfs_path)

    return env


def run_with_glibc(
    distro_name: str,
    command: list[str],
    extra_lib_paths: list[str] | None = None,
    working_dir: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> int:
    """
    Run a command using the glibc from a specific distro's rootfs.

    This works by using the ld-linux dynamic linker from the target rootfs
    and setting LD_LIBRARY_PATH to include the rootfs libraries.

    Args:
        distro_name: Name of the distro (e.g., "bookworm")
        command: Command and arguments to run
        extra_lib_paths: Additional library paths to include
        working_dir: Working directory for the command
        env_vars: Additional environment variables to set

    Returns:
        Exit code of the command
    """
    distro = get_distro(distro_name)
    if not distro:
        raise RuntimeError(f"Unknown distro: {distro_name}")

    if not is_rootfs_installed(distro_name):
        raise RuntimeError(
            f"Rootfs for {distro_name} is not installed. Run: rtbox pull {distro_name}"
        )

    rootfs_path = get_distro_rootfs(distro_name)

    # Find the dynamic linker
    ld_linux = find_ld_linux(rootfs_path)
    if not ld_linux:
        raise RuntimeError(
            f"Could not find ld-linux in rootfs at {rootfs_path}. "
            "The rootfs may be incomplete or corrupted."
        )

    # Build the environment
    env = build_runtime_env(rootfs_path, extra_lib_paths)

    # Add any user-specified environment variables
    if env_vars:
        env.update(env_vars)

    # Build the full command: ld-linux --library-path <paths> <command>
    lib_path = env.get("LD_LIBRARY_PATH", "")

    # The command to run: use ld.so directly with --library-path
    # Use --inhibit-rpath to ignore RPATH/RUNPATH in binaries, forcing use of our library path
    full_command = [
        str(ld_linux),
        "--inhibit-rpath",
        "",
        "--library-path",
        lib_path,
        *command,
    ]

    # Run the command
    try:
        result = subprocess.run(
            full_command,
            env=env,
            cwd=working_dir,
        )
        return result.returncode
    except FileNotFoundError as e:
        raise RuntimeError(f"Command not found: {e}")
    except PermissionError as e:
        raise RuntimeError(f"Permission denied: {e}")


def exec_with_glibc(
    distro_name: str,
    command: list[str],
    extra_lib_paths: list[str] | None = None,
    env_vars: dict[str, str] | None = None,
) -> None:
    """
    Replace the current process with the command using a different glibc.

    This is similar to run_with_glibc but uses os.execve to replace the
    current process entirely.
    """
    distro = get_distro(distro_name)
    if not distro:
        raise RuntimeError(f"Unknown distro: {distro_name}")

    if not is_rootfs_installed(distro_name):
        raise RuntimeError(
            f"Rootfs for {distro_name} is not installed. Run: rtbox pull {distro_name}"
        )

    rootfs_path = get_distro_rootfs(distro_name)

    # Find the dynamic linker
    ld_linux = find_ld_linux(rootfs_path)
    if not ld_linux:
        raise RuntimeError(f"Could not find ld-linux in rootfs at {rootfs_path}")

    # Build the environment
    env = build_runtime_env(rootfs_path, extra_lib_paths)

    # Add any user-specified environment variables
    if env_vars:
        env.update(env_vars)

    # Build the full command
    # Use --inhibit-rpath to ignore RPATH/RUNPATH in binaries, forcing use of our library path
    lib_path = env.get("LD_LIBRARY_PATH", "")
    full_command = [
        str(ld_linux),
        "--inhibit-rpath",
        "",
        "--library-path",
        lib_path,
        *command,
    ]

    # Replace the current process
    os.execve(str(ld_linux), full_command, env)


def get_shell_wrapper_script(distro_name: str) -> str:
    """
    Generate a shell script that sets up the environment for a distro.

    This can be sourced in a shell to set up the environment variables
    needed to run commands with a different glibc.
    """
    distro = get_distro(distro_name)
    if not distro:
        raise RuntimeError(f"Unknown distro: {distro_name}")

    if not is_rootfs_installed(distro_name):
        raise RuntimeError(f"Rootfs for {distro_name} is not installed")

    rootfs_path = get_distro_rootfs(distro_name)
    ld_linux = find_ld_linux(rootfs_path)
    lib_paths = get_lib_paths(rootfs_path)
    lib_path_str = ":".join(str(p) for p in lib_paths)

    script = f"""#!/bin/bash
# rtbox wrapper script for {distro_name} (glibc {distro.glibc_version})
# Source this script or use it as a prefix for commands

export RTBOX_ROOTFS="{rootfs_path}"
export RTBOX_DISTRO="{distro_name}"
export LD_LIBRARY_PATH="{lib_path_str}"

# Function to run commands with the rtbox glibc
rtbox_run() {{
    "{ld_linux}" --inhibit-rpath "" --library-path "$LD_LIBRARY_PATH" "$@"
}}

# If arguments were passed, run them
if [ $# -gt 0 ]; then
    rtbox_run "$@"
fi
"""
    return script
