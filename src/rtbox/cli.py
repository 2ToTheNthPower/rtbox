"""CLI interface for rtbox."""

import sys

import click
from rich.console import Console
from rich.table import Table

from rtbox import __version__
from rtbox.distros import get_distro, list_distros
from rtbox.rootfs import (
    RootfsError,
    get_installed_rootfs,
    get_rootfs_info,
    is_rootfs_installed,
    pull_rootfs,
    remove_rootfs,
)
from rtbox.runtime import (
    RuntimeError as RtboxRuntimeError,
    get_shell_wrapper_script,
    run_with_glibc,
)


console = Console()
err_console = Console(stderr=True)


@click.group()
@click.version_option(version=__version__, prog_name="rtbox")
def main():
    """rtbox - Run binaries with different glibc versions.

    rtbox allows you to run binaries or compile software using glibc
    from different Debian distributions. This is particularly useful
    on HPCs where you might be stuck with an old glibc but need a
    newer version.

    Examples:

        rtbox list                    # List available distros
        rtbox pull bookworm           # Download Debian bookworm rootfs
        rtbox run bookworm ./myapp    # Run myapp with bookworm's glibc
        rtbox build bookworm make     # Run make with bookworm's glibc
    """
    pass


@main.command("list")
@click.option("--installed", "-i", is_flag=True, help="Show only installed rootfs")
def list_cmd(installed: bool):
    """List available Debian distributions."""
    distros = list_distros()
    installed_names = get_installed_rootfs()

    table = Table(title="Available Debian Distributions")
    table.add_column("Name", style="cyan")
    table.add_column("Version", style="magenta")
    table.add_column("glibc", style="green")
    table.add_column("Status", style="yellow")

    for distro in distros:
        if installed and distro.name not in installed_names:
            continue

        status = "[green]installed[/green]" if distro.name in installed_names else ""
        table.add_row(
            distro.name,
            distro.version,
            distro.glibc_version,
            status,
        )

    console.print(table)


@main.command()
@click.argument("distro")
@click.option("--force", "-f", is_flag=True, help="Force re-download even if exists")
def pull(distro: str, force: bool):
    """Download a Debian rootfs.

    DISTRO can be a codename (e.g., bookworm) or version number (e.g., 12).
    """
    distro_obj = get_distro(distro)
    if not distro_obj:
        console.print(f"[red]Unknown distro: {distro}[/red]")
        console.print("Run 'rtbox list' to see available distros.")
        sys.exit(1)

    console.print(f"Pulling rootfs for [cyan]{distro_obj.name}[/cyan] (Debian {distro_obj.version}, glibc {distro_obj.glibc_version})")

    try:
        pull_rootfs(distro_obj, force=force)
        console.print(f"[green]Successfully installed {distro_obj.name}[/green]")
    except RootfsError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@main.command()
@click.argument("distro")
def remove(distro: str):
    """Remove an installed rootfs."""
    distro_obj = get_distro(distro)
    if not distro_obj:
        console.print(f"[red]Unknown distro: {distro}[/red]")
        sys.exit(1)

    if not is_rootfs_installed(distro_obj.name):
        console.print(f"[yellow]Rootfs for {distro_obj.name} is not installed.[/yellow]")
        sys.exit(1)

    if remove_rootfs(distro_obj.name):
        console.print(f"[green]Removed rootfs for {distro_obj.name}[/green]")
    else:
        console.print(f"[red]Failed to remove rootfs for {distro_obj.name}[/red]")
        sys.exit(1)


@main.command()
@click.argument("distro")
def info(distro: str):
    """Show information about an installed rootfs."""
    distro_obj = get_distro(distro)
    if not distro_obj:
        console.print(f"[red]Unknown distro: {distro}[/red]")
        sys.exit(1)

    info_data = get_rootfs_info(distro_obj.name)
    if not info_data:
        console.print(f"[yellow]Rootfs for {distro_obj.name} is not installed.[/yellow]")
        console.print(f"Run: rtbox pull {distro_obj.name}")
        sys.exit(1)

    table = Table(title=f"Rootfs Info: {distro_obj.name}")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Name", info_data["name"])
    table.add_row("Debian Version", info_data["version"])
    table.add_row("glibc Version", info_data["glibc_version"])
    table.add_row("Path", info_data["path"])
    table.add_row("Size", f"{info_data['size_mb']:.1f} MB")

    console.print(table)


@main.command()
@click.argument("distro")
@click.argument("command", nargs=-1, required=True)
@click.option("--lib-path", "-L", multiple=True, help="Additional library paths")
@click.option("--env", "-e", multiple=True, help="Environment variables (KEY=VALUE)")
@click.option("--cwd", "-C", help="Working directory")
def run(distro: str, command: tuple, lib_path: tuple, env: tuple, cwd: str | None):
    """Run a command with a specific glibc version.

    DISTRO is the distribution name (e.g., bookworm).
    COMMAND is the command and arguments to run.

    Examples:

        rtbox run bookworm ./myapp --arg1 --arg2
        rtbox run bookworm -L /opt/mylibs ./myapp
        rtbox run bookworm -e LD_DEBUG=libs ./myapp
    """
    distro_obj = get_distro(distro)
    if not distro_obj:
        console.print(f"[red]Unknown distro: {distro}[/red]")
        sys.exit(1)

    # Parse environment variables
    env_vars = {}
    for e in env:
        if "=" in e:
            key, value = e.split("=", 1)
            env_vars[key] = value
        else:
            console.print(f"[red]Invalid environment variable: {e}[/red]")
            console.print("Use format: KEY=VALUE")
            sys.exit(1)

    try:
        exit_code = run_with_glibc(
            distro_obj.name,
            list(command),
            extra_lib_paths=list(lib_path) if lib_path else None,
            working_dir=cwd,
            env_vars=env_vars if env_vars else None,
        )
        sys.exit(exit_code)
    except RtboxRuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@main.command()
@click.argument("distro")
@click.argument("command", nargs=-1, required=True)
@click.option("--lib-path", "-L", multiple=True, help="Additional library paths")
@click.option("--env", "-e", multiple=True, help="Environment variables (KEY=VALUE)")
@click.option("--cwd", "-C", help="Working directory")
def build(distro: str, command: tuple, lib_path: tuple, env: tuple, cwd: str | None):
    """Run a build command with a specific glibc version.

    This is an alias for 'run' that's semantically clearer for build commands.

    Examples:

        rtbox build bookworm make -j4
        rtbox build bookworm cmake --build build/
        rtbox build trixie cargo build --release
    """
    distro_obj = get_distro(distro)
    if not distro_obj:
        console.print(f"[red]Unknown distro: {distro}[/red]")
        sys.exit(1)

    # Parse environment variables
    env_vars = {}
    for e in env:
        if "=" in e:
            key, value = e.split("=", 1)
            env_vars[key] = value
        else:
            console.print(f"[red]Invalid environment variable: {e}[/red]")
            sys.exit(1)

    console.print(f"[dim]Building with glibc {distro_obj.glibc_version} from {distro_obj.name}...[/dim]")

    try:
        exit_code = run_with_glibc(
            distro_obj.name,
            list(command),
            extra_lib_paths=list(lib_path) if lib_path else None,
            working_dir=cwd,
            env_vars=env_vars if env_vars else None,
        )
        sys.exit(exit_code)
    except RtboxRuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@main.command()
@click.argument("distro")
def shell_wrapper(distro: str):
    """Generate a shell wrapper script for a distro.

    This outputs a shell script that can be sourced or used to run
    commands with the specified glibc version.

    Example:

        rtbox shell-wrapper bookworm > rtbox-bookworm.sh
        source rtbox-bookworm.sh
        rtbox_run ./myapp
    """
    distro_obj = get_distro(distro)
    if not distro_obj:
        err_console.print(f"[red]Unknown distro: {distro}[/red]")
        sys.exit(1)

    try:
        script = get_shell_wrapper_script(distro_obj.name)
        # Print to stdout so it can be redirected to a file
        print(script)
    except RtboxRuntimeError as e:
        err_console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
