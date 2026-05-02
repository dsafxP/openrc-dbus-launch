# TODO

## Repository Bootstrap

- [x] Initialise git repository
- [ ] Write `README.md` with project purpose, status, and build instructions (low priority)
- [x] Add `LICENSE` file (BSD-2-Clause)
- [x] Set up `meson.build` root + `meson.options` with:
  - `openrc_initddir` (default `/etc/init.d`)
  - `openrc_confddir` (default `/etc/conf.d`)
  - `rundir` (default `/run/dbus`)
  - `dbus_broker_path` (default `/usr/bin/dbus-broker`) — do **not** hard-code
    this as a string literal; learned from 66-dbus-launch §12
  - `fdpass_shim` feature option (`auto` / `enabled` / `disabled`)
- [ ] Set up subdir structure: `launcher/`, `fdpass/`, `data/`, `tests/`
- [x] Configure `pyproject.toml` for editable installs during development
- [x] Add `.gitignore` for `build/`, `__pycache__/`, `*.pyc`, `*.so`

## Socket Setup (`launcher/socket.py`)

Corresponds to `dbus.c` in 66-dbus-launch.

- [ ] Implement `create_bus_socket(path)`:
  - `unlink` stale socket if present
  - `socket(AF_UNIX, SOCK_STREAM)`
  - `bind` + `listen`
  - Set `umask(0o000)` around bind so the socket is world-accessible,
    restore afterwards
  - Do **not** use the `close(0)` fd-slot trick from 66-dbus-launch §8 —
    use explicit fd management instead
- [ ] Implement `set_bus_address_env(path, session=False)`:
  - Honour a pre-existing `DBUS_SYSTEM_BUS_ADDRESS` /
    `DBUS_SESSION_BUS_ADDRESS` if already set (preserve caller-specified address)
  - Otherwise export `unix:path=<path>`
- [ ] Compute socket path from config:
  - System bus: `{rundir}/system_bus_socket`
  - Session bus: `{XDG_RUNTIME_DIR}/{session_socket_name}`
- [ ] Write tests: socket is created, permissions are correct, env var is set

## Broker Spawning (`launcher/broker.py`)

Corresponds to `launcher_fork` + `launcher_run_broker` in `launcher.c` §4.3–4.4.

- [ ] Create `socketpair(AF_UNIX, SOCK_STREAM)` for the controller channel;
  both ends start with `CLOEXEC`
- [ ] Create a one-shot `os.pipe()` sync channel (unblocks parent after exec)
- [ ] `os.fork()`:
  - **Child**:
    - Close the launcher's end of the controller pair
    - Strip `FD_CLOEXEC` from the broker's controller fd via
      `fcntl(fd, F_SETFD, flags & ~FD_CLOEXEC)` — this is the critical
      fd-inheritance step
    - `prctl(PR_SET_PDEATHSIG, SIGTERM)` — broker dies if launcher exits,
      preventing orphaned processes
    - Write one byte to sync pipe to unblock parent
    - `os.execv(dbus_broker_path, ["dbus-broker",
        "--controller", str(fd), "--machine-id", machine_id])`
  - **Parent**:
    - Close broker's end of controller pair
    - Block on sync pipe read until child signals exec
    - Close sync pipe
    - Return broker PID + launcher's controller fd
- [ ] Implement `read_machine_id()`:
  - `Path('/etc/machine-id').read_text().strip()`
  - Fallback to `"00000000000000000000000000000001"` if missing or unreadable
  - No manual buffer management needed; avoids the partial-read bug in
    66-dbus-launch §12
- [ ] Implement broker process reaping in SIGCHLD handler:
  - `os.waitpid(broker_pid, os.WNOHANG)`
  - Distinguish broker death from service child death
  - Propagate broker exit code upward (non-zero = failure)
- [ ] Write tests: mock execv, verify fd flags, verify sync behaviour

## Controller Protocol (`launcher/controller.py`)

Corresponds to `launcher_setup` in `launcher.c` §4.5 and `policy.c` §8.
Uses `jeepney` for message construction.

- [ ] Open a jeepney connection on the controller fd (not a bus connection —
  a raw P2P fd-backed connection)
- [ ] Implement `add_listener(controller_conn, listener_fd, policy)`:
  - Construct `AddListener` message to `/org/bus1/DBus/Broker`,
    interface `org.bus1.DBus.Broker`
  - Pass `listener_fd` via `SCM_RIGHTS` ancillary data alongside the message
    (see fd-passing phase below)
  - Signature: `(oh + policy_blob)`
- [ ] Implement `add_name(controller_conn, obj_path, name, uid)`:
  - Method call to `/org/bus1/DBus/Broker`, `org.bus1.DBus.Broker.AddName`
  - Signature: `osu`
- [ ] Implement `release_name(controller_conn, name_obj_path)`:
  - Method call on the name's own path, `org.bus1.DBus.Name.Release`
  - Signature: `()`
- [ ] Implement `reset_activation(controller_conn, name_obj_path, serial)`:
  - Called when activation fails; tells broker to reject the pending request
  - Signature: `t`
- [ ] Implement `reload_config(controller_conn)`:
  - Expose `ReloadConfig` as a callable method on `/org/bus1/DBus/Controller`,
    `org.bus1.DBus.Controller`
  - Triggered by SIGHUP or by a D-Bus call from a client
- [ ] Build a permissive policy blob for `AddListener`:
  - `allow_connect = True`
  - `allow_own = True` (all names, prefix match)
  - `allow_transmit = True` (wildcard)
  - Mark with `# TODO: parse /usr/share/dbus-1/{system,session}.conf` for
    future proper policy support — see 66-dbus-launch §13 item 7
  - Propagate errors from every container open/append/close — do **not**
    silently discard intermediate failures as 66-dbus-launch does (§12)
- [ ] Write tests: message bytes, policy structure, error propagation

## fd-Passing (`fdpass/`)

The only part that genuinely requires low-level socket control.

- [ ] **Attempt pure Python first** using `socket.sendmsg()`:
  ```python
  import array
  fds = array.array('i', [fd_to_send])
  sock.sendmsg([msg_bytes],
               [(socket.SOL_SOCKET, socket.SCM_RIGHTS, fds)])
  ```
  Verify that jeepney message bytes + SCM_RIGHTS cmsg are accepted by
  dbus-broker's controller socket.
- [ ] If pure Python works: mark `fdpass_shim` as unnecessary, document why
- [ ] If pure Python does not work: implement `fdpass/fdpass.c`:
  - `send_fd_with_msg(int sock, const void *msg, size_t len, int fd)` →
    constructs `msghdr` + `cmsghdr` with `SCM_RIGHTS`, calls `sendmsg`
  - `recv_fd_with_msg(int sock, void *buf, size_t len, int *fd_out)` →
    `recvmsg` with ancillary buffer, extracts fd
  - ~60–80 lines total; no other logic in this file
  - Expose via `ctypes` in `launcher/fdpass.py` with a clean Python wrapper
- [ ] `fdpass/meson.build`: build as `fdpass.so`, install next to Python package,
  only when `fdpass_shim` option is not `disabled`
- [ ] Write tests for both paths

## Service Management (`launcher/service.py`)

Corresponds to `service.c` §6 and `service.h`.

- [ ] Define `ServiceState` enum (replaces bitmask flags from 66-dbus-launch):
  ```python
  class ServiceState(enum.Flag):
      INSERT = enum.auto()   # needs AddName to broker
      OK     = enum.auto()   # synchronised, nothing pending
      DELETE = enum.auto()   # removed from disk, needs Release
      RELOAD = enum.auto()   # config changed, needs re-registration
  ```
- [ ] Define `Service` dataclass:
  - `name: str` — D-Bus well-known name
  - `exec_path: str` — `Exec=` from `.service` file
  - `user: str | None` — `User=` from `.service` file (optional)
  - `broker_id: int` — numeric ID assigned at `AddName` time
  - `state: ServiceState`
- [ ] Implement `parse_service_file(path)` → `Service`:
  - Skip `[D-Bus Service]` header
  - Parse `key=value` lines; extract `Name`, `Exec`, `User`
  - Raise on missing `Name` or `Exec` (both mandatory per D-Bus spec)
- [ ] Implement `load_services(service_dir)` → `dict[str, Service]`:
  - Scan `service_dir` for `*.service` files
  - Allow empty directory (valid configuration; no failure — 66-dbus-launch §12)
- [ ] Implement `ServiceRegistry`:
  - `dict[str, Service]` keyed by name (primary)
  - `dict[int, Service]` keyed by broker ID (secondary index for O(1) activation
    lookup — avoids the linear scan in 66-dbus-launch §12)
  - `add(service)`, `remove(name)`, `by_id(broker_id)`, `by_name(name)`
- [ ] Write tests: parser handles all `.service` fields, empty dir, malformed
  files, duplicate names

## Activation (`launcher/activation.py`)

Corresponds to `service_activate` / `service_deactivate` in `service.c` §6.5,
replacing 66-specific commands with direct exec or `rc-service`.

- [ ] Implement `activate_service(service)` **asynchronously**:
  - Use `asyncio.create_subprocess_exec` (or track PIDs manually with
    `os.fork` + SIGCHLD) — do **not** block the event loop as 66-dbus-launch
    does with `sync_spawn` (§12)
  - Strategy A (preferred): exec `Exec=` directly, let the service claim its
    name on the bus
  - Strategy B (fallback): `rc-service <name> start` for services wrapped as
    OpenRC scripts
  - On failure: call `Reset` on the broker to reject the activation
- [ ] Track in-flight activations: `dict[int, asyncio.Task]` keyed by broker ID
  so duplicate activation requests for the same name are not double-spawned
- [ ] Handle `SIGCHLD` for activated service children:
  - Distinguish from broker PID
  - Log exit status; do not re-activate automatically (let the broker re-request
    if needed)
- [ ] Write tests: activation triggers exec, duplicate requests are deduplicated,
  failure triggers Reset

## Event Loop (`launcher/main.py`)

Corresponds to `launcher_loop` in `launcher.c` §4.6 and `handle_signal` in
`util.c` §7.

- [ ] Use `asyncio` event loop (or `selectors.DefaultSelector` if asyncio proves
  too heavy):
  - Wait on: controller fd, signal wakeup fd
  - Process all pending controller messages before checking signals
    (mirrors 66-dbus-launch priority ordering: broker fd first)
- [ ] Set up signal handling via `loop.add_signal_handler` or
  `signal.set_wakeup_fd`:
  - `SIGTERM` / `SIGINT` / `SIGQUIT` → clean shutdown
  - `SIGHUP` → reload (re-scan service dir, sync with broker)
  - `SIGCHLD` → reap children, detect broker death
  - `SIGPIPE` → ignore
- [ ] Implement message dispatch (`on_message`):
  - `org.bus1.DBus.Name.Activate` on `/org/bus1/DBus/Name/<id>`:
    use `str.startswith("/org/bus1/DBus/Name/")` — returns bool, not length,
    so the inverted-condition bug from 66-dbus-launch §12 cannot occur
  - `org.bus1.DBus.Broker.SetActivationEnvironment` on `/org/bus1/DBus/Broker`:
    write `key=value` pairs to env file
  - Unknown paths/interfaces: silently ignore (do not crash)
- [ ] Implement `update_environment(msg)`:
  - Parse `a{ss}` container from message
  - Write `key=value\n` lines to:
    - System: `/etc/dbus-broker-openrc/environment`
    - Session: `$XDG_RUNTIME_DIR/dbus-broker-openrc/environment`
  - Overwrite (not append) on each update, matching 66-dbus-launch behaviour
- [ ] Implement `reload(registry, controller_conn)`:
  - Re-scan service directory
  - Diff against current registry: compute adds, removes, unchanged
  - Call `AddName` for new services, `Release` for removed ones
  - Update registry
- [ ] Implement clean shutdown sequence:
  - Send `Release` for all registered names
  - `SIGTERM` to broker PID, wait for it to exit
  - Remove socket file
- [ ] Write tests: signal dispatch, message routing, reload diff logic

## Privilege Handling (`launcher/privileges.py`)

Corresponds to `launcher_drop_permissions` in `launcher.c` §4.9.

- [ ] Implement `drop_permissions(uid, gid)`:
  - Only act when `uid > 0` (non-root)
  - `os.setgroups([])` — clear supplementary groups; non-fatal on failure
    (matches dbus-daemon compatibility behaviour from 66-dbus-launch §4.9)
  - `os.setgid(gid)` — fatal on failure
  - `os.setuid(uid)` — fatal on failure
- [ ] Call once in the broker child (before exec) and once in the launcher
  parent (after `AddListener` completes)
- [ ] Write tests: verify uid/gid are set, verify non-root guard

## Entry Point and Readiness (`launcher/main.py`)

Corresponds to `main()` in `66-dbus-launch.c` §3.

- [ ] Argument parsing:
  - `--system` / `--session` (bus type)
  - `--broker-path` (override compiled-in path at runtime)
  - `--verbose` / `-v`
  - `--notification-fd N` (fd to write `\n` to when fully ready — for OpenRC
    `supervise-daemon` or other supervisors that understand readiness protocols)
- [ ] Startup sequence (fail-fast on each step):
  1. Sanitise stdin/stdout/stderr (ensure they are open)
  2. `create_bus_socket()`
  3. `set_bus_address_env()`
  4. Set up signal handlers
  5. `load_services(service_dir)` — allow empty, never fatal on its own
  6. `spawn_broker()` + wait for sync
  7. `add_listener()` + `add_name()` for all loaded services
  8. Drop privileges
  9. Write `\n` to notification fd if provided (readiness signal)
  10. Enter event loop
  11. On exit: clean shutdown sequence
- [ ] Write integration test: full startup sequence with a mock broker

## OpenRC Integration (`data/`)

- [ ] Write `data/dbus-broker.initd.in` init script template:
  - `#!/sbin/openrc-run` shebang — mandatory, any other interpreter breaks
    dependency handling
  - `command="@LAUNCHER@"`
  - `command_background="yes"`
  - `pidfile="/run/dbus/dbus-broker-launch.pid"`
  - `depend()`: `need localmount`, `after bootmisc`, `use elogind`
  - `start_pre()`: `checkpath -d -m 0755 /run/dbus`
  - `stop_post()`: remove socket file
- [ ] Write `data/dbus-broker.confd.in`:
  - `DBUS_BROKER_ARGS=""` — extra args passed through to the launcher
  - Document `--system` / `--session` usage
- [ ] Wire up `data/meson.build`:
  - `configure_file()` to substitute `@LAUNCHER@`, `@RUNDIR@`, `@VERSION@`
  - Install init script as executable (`install_mode: 'rwxr-xr-x'`)
- [ ] Manually test: `rc-service dbus-broker start/stop/restart/status`

## Tests (`tests/`)

Items from 66-dbus-launch §13 that had zero test coverage — highest priority
targets for this project.

- [ ] `tests/test_service_parse.py`:
  - Valid `.service` file → correct `Service` fields
  - Missing `Name=` → exception
  - Missing `Exec=` → exception
  - Extra unknown keys ignored
  - Empty service directory → empty registry, no error
- [ ] `tests/test_controller_messages.py`:
  - `AddListener` message has correct signature and structure
  - `AddName` message has correct signature
  - Policy blob is well-formed (no silently discarded intermediate errors)
  - `Reset` is sent on activation failure
- [ ] `tests/test_message_filter.py`:
  - `Activate` signal on `/org/bus1/DBus/Name/5` → dispatched to activation
  - `Activate` signal on `/org/bus1/DBus/Broker` → ignored (not a name path)
  - `SetActivationEnvironment` on `/org/bus1/DBus/Broker` → env update called
  - `SetActivationEnvironment` on a name path → ignored
- [ ] `tests/test_activation.py`:
  - Activation calls exec with correct args
  - Duplicate activation of same ID is not double-spawned
  - Failed activation sends `Reset` to broker
- [ ] `tests/test_reload.py`:
  - New `.service` file added → `AddName` called
  - `.service` file removed → `Release` called
  - Unchanged file → no broker call
- [ ] `tests/test_privileges.py`:
  - `drop_permissions` is a no-op when `uid == 0`
  - `drop_permissions` calls `setgid` then `setuid` in correct order
- [ ] Wire up `tests/meson.build` and confirm `meson test` runs cleanly

## Packaging and Distribution

- [ ] Verify install paths work for common prefixes (`/usr`, `/usr/local`)
- [ ] Test on Alpine Linux
- [ ] Test on Gentoo
