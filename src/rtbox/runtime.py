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
    """Find the ld-linux dynamic linker in the rootfs.

    Important: We must return the actual file, not a symlink, because symlinks
    in the rootfs may be absolute paths that would resolve to the host system's
    linker instead of the rootfs one.
    """
    # Common locations for ld-linux - prefer arch-specific paths first
    # because lib64 often contains symlinks with absolute paths
    candidates = [
        # x86_64 - check the actual lib path first, not lib64 symlink
        rootfs_path / "lib" / "x86_64-linux-gnu" / "ld-linux-x86-64.so.2",
        rootfs_path / "lib64" / "ld-linux-x86-64.so.2",
        # aarch64
        rootfs_path / "lib" / "aarch64-linux-gnu" / "ld-linux-aarch64.so.1",
        rootfs_path / "lib" / "ld-linux-aarch64.so.1",
        # Generic
        rootfs_path / "lib" / "ld-linux.so.2",
    ]

    for candidate in candidates:
        if candidate.exists():
            # If it's a symlink, check if it's absolute (points outside rootfs)
            if candidate.is_symlink():
                link_target = os.readlink(candidate)
                if link_target.startswith("/"):
                    # Absolute symlink - skip it, it would resolve to host
                    continue
            return candidate

    # Try to find it with glob, preferring non-symlinks
    for pattern in ["lib/*/ld-linux*.so*", "lib*/ld-linux*.so*"]:
        matches = list(rootfs_path.glob(pattern))
        if matches:
            # Filter out absolute symlinks and prefer .so.2/.so.1 files
            valid = []
            for m in matches:
                if m.is_symlink():
                    link_target = os.readlink(m)
                    if link_target.startswith("/"):
                        continue
                if ".so.2" in m.name or ".so.1" in m.name:
                    valid.append(m)
            if valid:
                return valid[0]
            # Fallback to any match that's not an absolute symlink
            for m in matches:
                if m.is_symlink():
                    link_target = os.readlink(m)
                    if link_target.startswith("/"):
                        continue
                return m

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
) -> dict[str, str]:
    """Build the environment for running with a different glibc.

    We start with a minimal clean environment to avoid interference from
    host glibc-related variables that can cause crashes like "stack smashing
    detected" when the host and target glibc versions differ.
    """
    # Safe variables to pass through from the host environment
    safe_vars = [
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "COLORTERM",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XDG_RUNTIME_DIR",
        "XDG_SESSION_TYPE",
        "DBUS_SESSION_BUS_ADDRESS",
        "SSH_AUTH_SOCK",
        "SSH_TTY",
        "TMPDIR",
        "TEMP",
        "TMP",
        # CI/CD variables
        "CI",
        "GITHUB_ACTIONS",
        "RUNNER_OS",
    ]

    # Start with a clean environment, only including safe variables
    env = {}
    for var in safe_vars:
        if var in os.environ:
            env[var] = os.environ[var]

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


def resolve_command(rootfs_path: Path, command: list[str]) -> list[str]:
    """Resolve command paths relative to the rootfs.

    If the command starts with an absolute path (e.g., /bin/ls), prepend
    the rootfs path to it so we run the binary from the rootfs, not the host.
    """
    if not command:
        return command

    result = list(command)
    executable = result[0]

    # If it's an absolute path, prepend the rootfs
    if executable.startswith("/"):
        rootfs_executable = rootfs_path / executable.lstrip("/")
        if rootfs_executable.exists():
            result[0] = str(rootfs_executable)

    return result


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
        command: Command and arguments to run (absolute paths like /bin/ls
                 are resolved to the rootfs)
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

    # Resolve command paths relative to rootfs
    resolved_command = resolve_command(rootfs_path, command)

    # Build a clean environment to avoid host glibc interference
    env = build_runtime_env(rootfs_path, extra_lib_paths)

    # Add any user-specified environment variables
    if env_vars:
        env.update(env_vars)

    # Build the full command: ld-linux --library-path <paths> <command>
    lib_path = env.get("LD_LIBRARY_PATH", "")

    # The command to run: use ld.so directly with --library-path
    # Note: We don't use --inhibit-rpath because user binaries may have RPATH
    # pointing to custom library locations (common on HPCs with module systems).
    # Our library path is searched first, so rootfs libs take precedence.
    full_command = [
        str(ld_linux),
        "--library-path",
        lib_path,
        *resolved_command,
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

    # Resolve command paths relative to rootfs
    resolved_command = resolve_command(rootfs_path, command)

    # Build a clean environment to avoid host glibc interference
    env = build_runtime_env(rootfs_path, extra_lib_paths)

    # Add any user-specified environment variables
    if env_vars:
        env.update(env_vars)

    # Build the full command
    lib_path = env.get("LD_LIBRARY_PATH", "")
    full_command = [
        str(ld_linux),
        "--library-path",
        lib_path,
        *resolved_command,
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
    "{ld_linux}" --library-path "$LD_LIBRARY_PATH" "$@"
}}

# If arguments were passed, run them
if [ $# -gt 0 ]; then
    rtbox_run "$@"
fi
"""
    return script
