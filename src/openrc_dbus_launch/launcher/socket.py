"""
Low-level socket management for D-Bus.
"""

import fcntl
import os
import socket
import config
from typing import Optional

from logger import log


def compute_socket_path(
    bus_type: str,
    rundir: str = config.RUNDIR,
    xdg_runtime_dir: Optional[str] = None,
) -> str:
    """
    Return the filesystem path for the bus socket.

    For system bus: rundir / "system_bus_socket"
    For session bus: XDG_RUNTIME_DIR / (default "dbus") or custom name.
    If XDG_RUNTIME_DIR is not set and bus_type is "session", fallback to
    /run/user/<uid>/dbus but note that this should normally be set.

    The exact socket name for session bus is currently fixed to "dbus".
    """
    if bus_type == 'system':
        return os.path.join(rundir, 'system_bus_socket')
    elif bus_type == 'session':
        if xdg_runtime_dir is None:
            xdg_runtime_dir = os.environ.get('XDG_RUNTIME_DIR')
        if xdg_runtime_dir is None:
            uid = os.getuid()
            xdg_runtime_dir = f'/run/user/{uid}'
        return os.path.join(xdg_runtime_dir, 'dbus')
    else:
        raise ValueError(f'Unknown bus type: {bus_type}')


def create_bus_socket(path: str) -> int:
    """
    Create, bind, and listen on a UNIX stream socket at `path`.

    The socket is created with O_NONBLOCK and FD_CLOEXEC.
    The umask is temporarily set to 0o000 to make the socket world-accessible.

    Returns the file descriptor (int) of the listening socket.
    """
    # Remove stale socket if present
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning(f'Failed to unlink {path}: {e}')

    # Create socket (Python doesn't support SOCK_NONBLOCK|SOCK_CLOEXEC directly)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    fd = sock.fileno()

    # Set non-blocking and close-on-exec flags
    sock.setblocking(False)
    flags = fcntl.fcntl(fd, fcntl.F_GETFD)
    fcntl.fcntl(fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)

    # Bind with world-accessible permissions
    old_umask = os.umask(0o000)
    try:
        sock.bind(path)
    except OSError as e:
        sock.close()
        log.error(f'bind failed for {path}: {e}')
        raise
    finally:
        os.umask(old_umask)

    # Listen for connections
    backlog = 128  # SOCK_BACKLOG default from 66-dbus-launch
    sock.listen(backlog)

    # Detach the fd from the Python socket object so it won't be closed
    # when the socket object is garbage collected.
    return sock.detach()


def set_bus_address_env(path: str, session: bool = False) -> None:
    """
    Set the appropriate DBUS_*_BUS_ADDRESS environment variable.

    If the variable is already set in the environment, it is left untouched.
    Otherwise it is set to "unix:path=<path>".

    Args:
        path: Filesystem path to the socket (as used in create_bus_socket).
        session: If True, set DBUS_SESSION_BUS_ADDRESS; else DBUS_SYSTEM_BUS_ADDRESS.
    """
    var_name = 'DBUS_SESSION_BUS_ADDRESS' if session else 'DBUS_SYSTEM_BUS_ADDRESS'
    existing = os.environ.get(var_name)
    if existing is not None:
        log.debug(f'Preserving existing {var_name}={existing}')
        return

    value = f'unix:path={path}'
    os.environ[var_name] = value
    log.info(f'Set {var_name}={value}')
