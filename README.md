# rtbox - Runtime Box

Run binaries with different glibc versions from Debian rootfs images.

Designed for HPC environments where you may be stuck with an old system glibc but need to compile or run software requiring a newer version.

## Features

- **No Docker required** - Downloads rootfs directly from the official LXC image server
- **Multiple Debian versions** - bullseye (glibc 2.31), bookworm (2.36), trixie (2.40), forky (2.41)
- **Cross-architecture** - Supports amd64 and arm64
- **Simple CLI** - Easy commands for managing rootfs and running binaries

## Installation

```bash
# Using uv (recommended)
uv pip install -e .

# Or using pip
pip install -e .
```

## Quick Start

```bash
# List available Debian versions
rtbox list

# Download a rootfs (~90MB compressed)
rtbox pull bookworm

# Run a command with that glibc
rtbox run bookworm ./myapp --arg1 --arg2

# Run a build with a specific glibc
rtbox build bookworm make -j4

# Show info about installed rootfs
rtbox info bookworm

# Generate a shell wrapper script
rtbox shell-wrapper bookworm > rtbox-bookworm.sh
source rtbox-bookworm.sh
rtbox_run ./myapp
```

## Commands

| Command | Description |
|---------|-------------|
| `rtbox list` | List available distros and their glibc versions |
| `rtbox pull <distro>` | Download a rootfs |
| `rtbox run <distro> <cmd>` | Run a command with that distro's glibc |
| `rtbox build <distro> <cmd>` | Alias for run (clearer for build commands) |
| `rtbox info <distro>` | Show info about an installed rootfs |
| `rtbox shell-wrapper <distro>` | Generate a shell wrapper script |
| `rtbox remove <distro>` | Remove an installed rootfs |

## How It Works

1. Downloads minimal rootfs tarballs from [images.linuxcontainers.org](https://images.linuxcontainers.org)
2. Uses the target rootfs's `ld-linux` dynamic linker with `--library-path`
3. Sets `LD_LIBRARY_PATH` to include the rootfs libraries
4. Runs your binary with the target glibc version

## Available Distros

| Name | Debian | glibc |
|------|--------|-------|
| bullseye | 11 | 2.31 |
| bookworm | 12 | 2.36 |
| trixie | 13 | 2.40 |
| forky | 14 | 2.41 |

## Use Cases

### Compiling with a newer glibc

```bash
# Your HPC has glibc 2.17, but you need 2.36 features
rtbox pull bookworm
rtbox build bookworm make -j$(nproc)
```

### Running pre-built binaries

```bash
# Binary requires glibc 2.31+ but system has 2.17
rtbox pull bullseye
rtbox run bullseye ./prebuilt-app
```

### Using newer compiler toolchains

```bash
# Get a newer GCC from a newer Debian
rtbox pull trixie
rtbox run trixie gcc --version
```

## Environment Variables

- `RTBOX_HOME` - Override the default storage location (`~/.rtbox`)
- `LD_LIBRARY_PATH` - Additional library paths are appended to this

## Configuration

Rootfs images are stored in `~/.rtbox/rootfs/<distro>/`.

## Testing

```bash
python test_rtbox.py
```

Note: Full binary execution tests require Linux.

## License

MIT
