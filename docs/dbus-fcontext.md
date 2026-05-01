# dbus-fcontext: Analysis of the 66-dbus-launch DBus Launcher

> Project: **66-tools** v0.1.2.0  
> Author: Eric Vidal \<eric@obarun.org\>  
> License: ISC  
> Analysed: `https://git.obarun.org/Obarun/66-tools`

---

## Table of Contents

- [dbus-fcontext: Analysis of the 66-dbus-launch DBus Launcher](#dbus-fcontext-analysis-of-the-66-dbus-launch-dbus-launcher)
  - [Table of Contents](#table-of-contents)
  - [1. High-Level Architectural Overview](#1-high-level-architectural-overview)
  - [2. Source Layout](#2-source-layout)
  - [3. Entry Point and Control Flow](#3-entry-point-and-control-flow)
  - [4. Launcher Core — `launcher.c`](#4-launcher-core--launcherc)
    - [4.1 Data Structure](#41-data-structure)
    - [4.2 Initialization — `launcher_new`](#42-initialization--launcher_new)
    - [4.3 Broker Spawning — `launcher_run` / `launcher_fork`](#43-broker-spawning--launcher_run--launcher_fork)
    - [4.4 FD Passing — `launcher_run_broker`](#44-fd-passing--launcher_run_broker)
    - [4.5 Bus Setup — `launcher_setup`](#45-bus-setup--launcher_setup)
    - [4.6 Event Loop — `launcher_loop`](#46-event-loop--launcher_loop)
    - [4.7 Message Filter — `launcher_on_message`](#47-message-filter--launcher_on_message)
    - [4.8 Environment Propagation — `launcher_update_environment`](#48-environment-propagation--launcher_update_environment)
    - [4.9 Privilege Dropping — `launcher_drop_permissions`](#49-privilege-dropping--launcher_drop_permissions)
  - [5. Socket Management — `dbus.c`](#5-socket-management--dbusc)
    - [`dbs_socket_bind`](#dbs_socket_bind)
    - [`dbs_setenv_dbus_address`](#dbs_setenv_dbus_address)
    - [`dbs_close_unref`](#dbs_close_unref)
  - [6. Service Lifecycle — `service.c`](#6-service-lifecycle--servicec)
    - [6.1 Data Structure](#61-data-structure)
    - [6.2 State Machine](#62-state-machine)
    - [6.3 Loading and Translation](#63-loading-and-translation)
    - [6.4 Synchronization with the Broker](#64-synchronization-with-the-broker)
    - [6.5 Activation, Reactivation, and Deactivation](#65-activation-reactivation-and-deactivation)
    - [6.6 Teardown](#66-teardown)
  - [7. Signal and Process Utilities — `util.c`](#7-signal-and-process-utilities--utilc)
    - [`async_spawn` / `spawn_wait` / `sync_spawn`](#async_spawn--spawn_wait--sync_spawn)
    - [`handle_signal`](#handle_signal)
    - [`fdmove`](#fdmove)
  - [8. Policy — `policy.c`](#8-policy--policyc)
  - [9. Error Handling and Resource Management](#9-error-handling-and-resource-management)
    - [Cleanup Attribute Pattern](#cleanup-attribute-pattern)
    - [Exit Codes](#exit-codes)
    - [Return Convention](#return-convention)
  - [10. Build System Analysis](#10-build-system-analysis)
    - [10.1 Project Metadata and Defaults](#101-project-metadata-and-defaults)
    - [10.2 Dependency Resolution](#102-dependency-resolution)
    - [10.3 Compiler and Linker Flags](#103-compiler-and-linker-flags)
    - [10.4 Conditional DBus Feature](#104-conditional-dbus-feature)
    - [10.5 Configuration Header Generation](#105-configuration-header-generation)
    - [10.6 Executable and Test Build](#106-executable-and-test-build)
  - [11. Interaction Between Launcher and dbus-broker](#11-interaction-between-launcher-and-dbus-broker)
  - [12. Critical Observations and Design Trade-offs](#12-critical-observations-and-design-trade-offs)
    - [Bug: Inverted condition in `launcher_on_message`](#bug-inverted-condition-in-launcher_on_message)
    - [Policy return value ignored](#policy-return-value-ignored)
    - [Hard-coded dbus-broker path](#hard-coded-dbus-broker-path)
    - [Permissive-only policy](#permissive-only-policy)
    - [`sync_spawn` blocking in the event loop](#sync_spawn-blocking-in-the-event-loop)
    - [Linear scan `service_search_byid`](#linear-scan-service_search_byid)
    - [Startup service count check](#startup-service-count-check)
    - [Machine ID handling](#machine-id-handling)
  - [13. Suggestions for Further Study and Improvement](#13-suggestions-for-further-study-and-improvement)

---

## 1. High-Level Architectural Overview

`66-dbus-launch` is a purpose-built launcher and supervisor for
[dbus-broker](https://github.com/bus1/dbus-broker), the split-privilege D-Bus
message daemon. It is one component inside the **66-tools** collection, a set
of helper programs for the [Obarun](https://web.obarun.org) Linux distribution
built around the **66** service manager.

The fundamental design goal is a clean separation of concerns that mirrors the
dbus-broker architecture itself:

```
┌──────────────────────────────────────────────────────────┐
│                     66-dbus-launch                       │
│                                                          │
│  ┌────────────┐   controller socketpair   ┌───────────┐  │
│  │  Launcher  │◄─────────────────────────►│   Broker  │  │
│  │ (parent)   │    sd_bus / org.bus1.DBus │ (child,   │  │
│  │            │                           │  exec'd)  │  │
│  └─────┬──────┘                           └─────┬─────┘  │
│        │  UNIX socket                           │        │
│  /run/dbus/system_bus_socket             clients connect │
│  /run/user/UID/dbus                      via AddListener  │
│        │                                        │        │
│  ┌─────▼──────┐   66 start / parse / remove     │        │
│  │  66 service│◄────────────────────────────────┘        │
│  │  frontend  │  (sync_spawn child processes)            │
│  │  (.dbus)   │                                          │
│  └────────────┘                                          │
└──────────────────────────────────────────────────────────┘
```

Key responsibilities of the launcher:

1. **Socket ownership**: creates, binds, and listens on the well-known D-Bus
   UNIX socket before the broker exists, so clients can connect immediately.
2. **Broker supervision**: forks `dbus-broker`, passes it a controller file
   descriptor via `execve`, and monitors it via `SIGCHLD`.
3. **Service discovery**: scans the standard D-Bus service directories
   (`/usr/share/dbus-1/system-services/` or `.../services/`) and generates
   66-native frontend files from each `.service` file found.
4. **On-demand activation**: reacts to `org.bus1.DBus.Name.Activate` signals
   from the broker by invoking `66 start <name>.dbus`.
5. **Reload**: responds to `SIGHUP` (or a `ReloadConfig` D-Bus call) to
   re-scan service files and synchronise additions, updates, and removals with
   the running broker.
6. **Environment propagation**: handles
   `org.bus1.DBus.Broker.SetActivationEnvironment` by writing received
   key=value pairs to a well-known environment file that all activated services
   import at start time.

The design deliberately avoids systemd — it uses **skalibs** (djb-style async
I/O with `iopause`), **oblibs** (Obarun library), and either **basu** or
**elogind** solely for the `sd_bus` API surface needed to speak the broker's
controller protocol.

---

## 2. Source Layout

```
src/66-dbus-launch/
├── 66-dbus-launch.c   — main(), option parsing, top-level sequencing
├── launcher.c         — core: fork/exec broker, event loop, D-Bus callbacks
├── launcher.h         — launcher_t struct, function declarations
├── dbus.c             — socket creation/binding, address env vars, vtable
├── dbus.h             — sd_bus include abstraction, extern declarations
├── service.c          — D-Bus .service parsing, 66 frontend generation,
│                        hash table, activation commands
├── service.h          — service_s struct, state flags, function declarations
├── util.c             — fdmove, posix_spawnp wrappers, signal handler
├── util.h             — utility function declarations
├── policy.c           — dbus-broker AddListener policy export (permissive)
├── policy.h           — POLICY_T type-string macros, POLICY_PRIORITY_DEFAULT
└── macro.h            — __cleanup__ helpers, DBS_EXIT_* constants

src/include/66-tools/
├── config.h.in        — Meson-processed configuration template
└── meson.build        — configure_file() invocation
```

The other tools in the project (`66-clock`, `66-ns`, `66-which`, etc.) are
completely independent single-file programs; they do not share code with
`66-dbus-launch`.

---

## 3. Entry Point and Control Flow

**File:** `src/66-dbus-launch/66-dbus-launch.c`

`main()` has an entirely sequential, no-return-on-error structure. Every step
either succeeds or calls one of the `log_die*` macros (which terminate the
process with an appropriate exit code).

```
main()
 │
 ├─ option parsing (subgetopt)
 │    -h  print help and exit
 │    -z  enable log colour if stdout is a tty
 │    -v  set global VERBOSITY
 │    -d  validate notification fd (must be ≥3, must be open via fcntl F_GETFD)
 │
 ├─ fd_sanitize()                     ensure stdin/stdout/stderr are open
 │
 ├─ dbs_socket_bind()                 create+bind+listen UNIX socket → fd
 │
 ├─ dbs_setenv_dbus_address()         export DBUS_{SYSTEM,SESSION}_BUS_ADDRESS
 │
 ├─ fd_ensure_open(notif, notif)      reserve fd slot for notifier
 │
 ├─ selfpipe_init()                   create self-pipe for signal delivery
 ├─ selfpipe_trap(SIGCHLD|SIGINT|SIGQUIT|SIGHUP|SIGTERM)
 ├─ sig_altignore(SIGPIPE)
 │
 ├─ launcher_new()                    allocate+initialise launcher_t
 │
 ├─ service_load()                    scan service dir, parse, write frontends
 │
 ├─ launcher_run()                    socketpair + fork + setup (see §4)
 │
 ├─ notify readiness                  write "\n" to notif fd, close it
 │
 ├─ launcher_loop()                   iopause on [selfpipe, controller_in]
 │
 ├─ selfpipe_finish()
 └─ service_discard_tree()            66 tree free dbus
```

The notification write (`"\n"` to the `-d` fd) occurs _after_ the broker is
fully connected and services are synchronised (`launcher_run` returns), but
_before_ entering the event loop. This satisfies the contract that a readiness
notification means the service is fully operational.

---

## 4. Launcher Core — `launcher.c`

### 4.1 Data Structure

```c
// launcher.h
struct launcher_s {
    int      fd_dbus;           // listening UNIX socket (D-Bus clients connect here)
    int      fd_controller_in;  // controller[0] — launcher reads/writes broker msgs
    int      fd_controller_out; // controller[1] — passed to dbus-broker via exec
    char     machineid[MACHINEID + 2]; // 32-char machine-id + null
    uid_t    uid;               // effective UID at startup
    gid_t    gid;               // effective GID at startup
    sd_bus  *bus_controller;    // sd_bus on fd_controller_in
    sd_bus  *bus_regular;       // connection to the running bus (for service activation)
    pid_t    bpid;              // PID of the spawned dbus-broker
    int      sync[2];           // one-shot pipe: child signals readiness to parent
    int      spfd;              // read end of the selfpipe
    uint32_t nservice;          // monotonically increasing service ID counter
    struct service_s **hservice;// pointer to the uthash hash table head
};
```

`fd_controller_in` and `fd_controller_out` are both ends of a `socketpair`.
The naming is from the _launcher's_ perspective: the launcher reads broker
messages on `in` and the broker receives them on `out` (which is passed via
`--controller`).

Both ends are created with `SOCK_CLOEXEC | SOCK_NONBLOCK`. Only `out` has its
`FD_CLOEXEC` flag stripped before `execve`, so it is the only non-standard fd
the broker process inherits.

### 4.2 Initialization — `launcher_new`

```c
// launcher.c:64
int launcher_new(launcher_t_ref *plauncher,
                 struct service_s **hservice, int socket, int sfpd)
```

Allocates with `calloc` (so all fields zero-initialise), then sets:

- `fd_dbus` ← the pre-bound socket fd
- `spfd` ← selfpipe read end
- `fd_controller_in` / `fd_controller_out` ← `-1` (not yet created)
- `uid` / `gid` ← `getuid()` / `getgid()`
- `nservice` ← `1` (IDs start at 1, never reset)
- `hservice` ← caller's hash table head pointer

`launcher_get_machine_id` reads `/etc/machine-id` (32 bytes) into
`launcher->machineid`. If the file is missing or unreadable it falls back to
the sentinel string `"00000000000000000000000000000001"`.

A `__cleanup__`-attributed local variable is used throughout, so on error paths
the partially-constructed struct is freed automatically (see §9).

### 4.3 Broker Spawning — `launcher_run` / `launcher_fork`

```c
// launcher.c:91
int launcher_run(launcher_t *launcher)
```

1. `socketpair(PF_UNIX, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0, controller)` —
   both ends start with `CLOEXEC`.
2. Stores `controller[0]` as `fd_controller_in`, `controller[1]` as
   `fd_controller_out`.
3. `pipe(launcher->sync)` — a one-shot synchronisation channel.
4. Calls `launcher_fork()`.
5. Calls `launcher_setup()`.

```c
// launcher.c:115
int launcher_fork(launcher_t *launcher)
```

`fork()` creates two paths:

**Child path:**

- Closes `sync[0]` (child only writes to `sync[1]`).
- Calls `selfpipe_finish()` to tear down the signal pipe (the broker has no
  business receiving the launcher's signals through inheritance).
- Closes `fd_controller_in` (child only uses `fd_controller_out`).
- Calls `launcher_run_broker()` — never returns on success.

**Parent path:**

- Closes `fd_controller_out` (parent only uses `fd_controller_in`).
- Records `bpid = pid`.
- Closes `sync[1]`, then reads one byte from `sync[0]` (blocking until the
  child signals readiness).
- Closes `sync[0]`.

The synchronisation pipe ensures that by the time `launcher_setup()` runs,
`dbus-broker` has already called `execve`. Without this, the launcher could
race ahead and attempt to connect over the controller socket before the broker
has started listening.

### 4.4 FD Passing — `launcher_run_broker`

```c
// launcher.c:199
int launcher_run_broker(launcher_t *launcher)
```

This runs in the child process. Steps in order:

1. **Privilege drop**: `launcher_drop_permissions()` — if `uid > 0`, calls
   `setgroups(0, NULL)`, `setgid`, `setuid` before anything else so the broker
   process runs as the correct user from the start.
2. **Death signal**: `prctl(PR_SET_PDEATHSIG, SIGTERM)` — guarantees the broker
   dies if the launcher exits, preventing orphaned broker processes.
3. **Strip `FD_CLOEXEC`** from `fd_controller_out`:
   ```c
   flags = fcntl(launcher->fd_controller_out, F_GETFD);
   fcntl(launcher->fd_controller_out, F_SETFD, flags & ~FD_CLOEXEC);
   ```
   This is the critical FD-passing step. Every other fd was created with
   `CLOEXEC` and will be closed by the kernel on `execve`. Only
   `fd_controller_out` survives into the broker.
4. **Sync**: writes one byte to `sync[1]`, unblocking the parent's read.
5. **exec**:
   ```c
   const char *const nargv[] = {
       "/usr/bin/dbus-broker",
       "--controller", fd_str,    // numeric string of fd_controller_out
       "--machine-id", launcher->machineid,
       0
   };
   execve(nargv[0], ...);
   ```
   On success this never returns. On failure, `_exit(1)` is called after the
   `goto exit` label.

Note: the commented-out `--max-matches`, `--max-objects`, `--max-bytes` options
suggest that resource limits were considered but are not currently enforced.

### 4.5 Bus Setup — `launcher_setup`

```c
// launcher.c:149
int launcher_setup(launcher_t *launcher)
```

Called in the parent after `launcher_fork()` returns.

1. `sd_bus_new()` — allocate a new bus object.
2. `sd_bus_set_fd(bus_controller, fd_controller_in, fd_controller_in)` — attach
   the socket (same fd for both input and output directions of the `sd_bus`
   stream).
3. `sd_bus_add_object_vtable(... "/org/bus1/DBus/Controller",
"org.bus1.DBus.Controller", launcher_vtable, launcher)` — expose the
   `ReloadConfig` method on the controller object. The vtable is defined in
   `dbus.c`:
   ```c
   const sd_bus_vtable launcher_vtable[] = {
       SD_BUS_VTABLE_START(0),
       SD_BUS_METHOD("ReloadConfig", NULL, NULL, launcher_on_reload_config, 0),
       SD_BUS_VTABLE_END
   };
   ```
4. `sd_bus_start()` — begin processing the bus.
5. `sd_bus_add_filter(... launcher_on_message, launcher)` — register the
   message filter that intercepts `Activate` and `SetActivationEnvironment`
   signals.
6. `launcher_add_listener()` — sends `AddListener` to the broker:
   ```c
   sd_bus_message_append(m, "oh",
       "/org/bus1/DBus/Listener/0",   // object path for this listener
       launcher->fd_dbus);             // the bound listening UNIX socket fd
   ```
   Appended to this message is the policy blob (see §8). This call hands the
   socket fd to the broker via `SCM_RIGHTS` (sd_bus handles the ancillary data
   internally when appending an `h` typed argument over a UNIX socket).
7. `launcher_connect()` — opens `bus_regular` via `sd_bus_open_user()` or
   `sd_bus_open_system()` depending on UID.
8. `service_sync_launcher_broker()` — register all pre-loaded services with the
   broker via `AddName` calls.
9. `launcher_drop_permissions()` — drops privileges in the parent as well, after
   all setup requiring elevated access is done.

### 4.6 Event Loop — `launcher_loop`

```c
// launcher.c:289
int launcher_loop(launcher_t *launcher)
```

```c
iopause_fd x[2] = {
    { .fd = launcher->spfd,            .events = IOPAUSE_READ },
    { .fd = launcher->fd_controller_in,.events = IOPAUSE_READ }
};
tain deadline = tain_infinite_relative;  // never times out
```

The loop multiplexes two event sources with skalibs' `iopause_g` (a portable
`pselect`/`ppoll` wrapper):

| Index  | fd                 | Event                               |
| ------ | ------------------ | ----------------------------------- |
| `x[0]` | `spfd` (selfpipe)  | signals converted to readable bytes |
| `x[1]` | `fd_controller_in` | D-Bus messages from broker          |

Priority ordering matters: the broker fd is tested first (`x[1]`). When a
D-Bus message is ready, `sd_bus_process()` is called in a loop (`continue` if
`r > 0`) until the queue drains. Only then is the signal pipe checked.

On `SIGTERM`/`SIGINT`/`SIGQUIT`, `handle_signal` returns `DBS_EXIT_MAIN` (= 0)
and the loop breaks. On `SIGHUP` or `SIGCHLD` of a service child (not the
broker), it returns `DBS_EXIT_CHILD` (= 1) and iteration continues. If the
broker itself exits, `compute_exit` is called on its wait status and the loop
terminates.

### 4.7 Message Filter — `launcher_on_message`

```c
// launcher.c:336
int launcher_on_message(sd_bus_message *m, void *userdata, sd_bus_error *error)
```

Two signals are handled:

**1. `org.bus1.DBus.Name.Activate` on `/org/bus1/DBus/Name/<id>`**

When a client requests activation of a well-known name the broker does not know
is running, it emits this signal on the name's object path. The numeric suffix
of the path is the `id` assigned when the name was registered via `AddName`.

```c
suffix = str_start_with(obj_path, "/org/bus1/DBus/Name/");
if (!suffix) {
    if (sd_bus_message_is_signal(m, "org.bus1.DBus.Name", "Activate")) {
        uint64_t serial;
        sd_bus_message_read(m, "t", &serial);
        // extract basename (numeric id) from obj_path
        r = service_activate(launcher, atoi(stk.s));
        if (r != 0)
            sd_bus_call_method(... obj_path, "org.bus1.DBus.Name", "Reset",
                               NULL, NULL, "t", serial);
    }
}
```

If activation fails, the broker is told to `Reset` (i.e., reject the pending
activation with an error).

**2. `org.bus1.DBus.Broker.SetActivationEnvironment` on `/org/bus1/DBus/Broker`**

```c
} else if (!strcmp(obj_path, "/org/bus1/DBus/Broker")) {
    if (sd_bus_message_is_signal(m, "org.bus1.DBus.Broker",
                                 "SetActivationEnvironment"))
        launcher_update_environment(launcher, m);
}
```

Note the logic inversion: `str_start_with` returns the _length of the matched
prefix_ (positive = match) but the code tests `!suffix` for the name branch,
which means it enters that branch when the path _does_ start with
`/org/bus1/DBus/Name/` (suffix > 0 → `!suffix` is false — wait, this seems
inverted). Looking at the actual code more carefully:

```c
suffix = str_start_with(obj_path, "/org/bus1/DBus/Name/");
if (!suffix) {            // enters when prefix NOT matched
    ...Activate path...
} else if (!strcmp(obj_path, "/org/bus1/DBus/Broker")) {
    ...SetActivationEnvironment path...
}
```

The oblibs `str_start_with` returns the length of the prefix on match, or 0 on
no match. So `!suffix` is true when the path does _not_ begin with
`/org/bus1/DBus/Name/`. The `Activate` signal path is therefore only entered
for paths that do **not** start with that prefix — the condition appears
inverted relative to the intent. This is a logic bug (see §12).

### 4.8 Environment Propagation — `launcher_update_environment`

```c
// launcher.c:392
void launcher_update_environment(launcher_t *launcher, sd_bus_message *m)
```

Reads an `a{ss}` (array of string pairs) D-Bus container from the message:

```c
sd_bus_message_enter_container(m, 'a', "{ss}");
while (!sd_bus_message_at_end(m, false)) {
    sd_bus_message_read(m, "{ss}", &key, &value);
    auto_stra(&sa, key, "=", value, "\n");
}
```

The resulting `key=value\n` lines are written atomically to either:

- `/etc/66/environment/0000-dbus` (root)
- `$HOME/.66/environment/0000-dbus` (user, resolved via `set_ownerhome_stack_byuid`)

Every service frontend includes `ImportFile=<path>` in its `[Environment]`
section, so the next `execl-envfile` invocation at service start will pick up
any changes. The file is _overwritten_ (not appended) on each update.

### 4.9 Privilege Dropping — `launcher_drop_permissions`

```c
// launcher.c:459
int launcher_drop_permissions(launcher_t *launcher)
```

Only acts when `uid > 0` (non-root):

```c
setgroups(0, NULL);    // clear all supplementary groups (non-fatal)
setgid(launcher->gid); // fatal on failure
setuid(launcher->uid); // fatal on failure
```

This is called **twice**: once in the child (before `execve` of the broker) and
once in the parent (after `launcher_setup` completes). The comment notes that
`setgroups` failure is intentionally non-fatal for compatibility with
`dbus-daemon` behaviour.

---

## 5. Socket Management — `dbus.c`

### `dbs_socket_bind`

```c
// dbus.c:92
int dbs_socket_bind(void)
```

1. Calls `dbs_get_socket_path()` to compute the socket path:
   - Root: `/run/dbus/<SS_TOOLS_DBS_SYSTEM_NAME>` (default: `system_bus_socket`)
   - User: `/run/user/<UID>/<SS_TOOLS_DBS_SESSION_NAME>` (default: `dbus`)
2. `unlink(path.s)` — removes any stale socket unconditionally.
3. `close(0)` — explicitly closes stdin (fd 0) before the socket is created, so
   `socket_open` (which allocates the next available fd) is very likely to
   receive fd 0. This is the classical djb-style fd slot reservation trick: by
   closing 0 first and immediately creating the socket, the socket will receive
   fd 0 unless something else races in. The intent is to keep the socket on a
   low, predictable fd.
4. Sets `umask(0000)` before `socket_bind()` so the socket file is created
   world-accessible (required for D-Bus clients to connect), then restores the
   old umask.
5. `socket_listen(fd, SOCK_BACKLOG)`.

### `dbs_setenv_dbus_address`

Checks for a pre-existing `DBUS_SYSTEM_BUS_ADDRESS` / `DBUS_SESSION_BUS_ADDRESS`
in the environment. If present it re-exports it unchanged (preserving any
caller-specified address); if absent it constructs `unix:path=<path>` from
`dbs_get_socket_unix_path()` and calls `setenv(..., 1)`.

### `dbs_close_unref`

```c
// dbus.c:44
sd_bus *dbs_close_unref(sd_bus *bus)
```

The comment explains the nuance: `sd_bus_flush_close_unref()` would block
waiting for queued messages. On error paths, blocking is undesirable, so this
helper only flushes (non-blocking drain attempt) then unrefs. `sd_bus_close`
is deliberately commented out to avoid the blocking wait.

---

## 6. Service Lifecycle — `service.c`

### 6.1 Data Structure

```c
// service.h
struct service_s {
    char         name[SS_MAX_SERVICE_NAME + 1]; // D-Bus well-known name
    char         exec[1024 + 1];                // Exec= line from .service file
    char         user[1024 + 1];                // User= line (optional)
    char         frontend[SS_MAX_PATH_LEN + 1]; // absolute path to .dbus frontend
    int          id;                            // broker object-path numeric id
    uint8_t      state;                         // bitmask of DBS_SERVICE_* flags
    UT_hash_handle hh;                          // uthash intrusive list node
};
```

The hash table is keyed by `name` (using `HASH_ADD_STR` / `HASH_FIND_STR` from
[uthash](https://troydhanson.github.io/uthash/)). A parallel lookup
`service_search_byid()` performs a linear scan when an activation signal arrives
with a numeric id.

### 6.2 State Machine

Services transition through a bitmask of flags:

```
DBS_SERVICE_INSERT  (1<<2)  — new, needs AddName to broker
DBS_SERVICE_PARSE   (1<<3)  — config changed, needs 66 parse -f
DBS_SERVICE_DELETE  (1<<4)  — removed from disk, needs Release + 66 remove
DBS_SERVICE_OK      (1<<1)  — synchronised, nothing pending
```

Flags are not mutually exclusive: a service can be simultaneously `INSERT |
PARSE` if it is new and needs parsing.

### 6.3 Loading and Translation

**`service_load()`** (startup only):

1. `service_get_list()` → `sastr_dir_get()` fills a stralloc with filenames from
   the service directory (regular files only, `S_IFREG`).
2. For each filename, `service_translate()`:
   - Constructs full path: `<service_dir>/<filename>`.
   - Allocates a `service_s`.
   - `service_parse()` — opens and reads the file, skips the `[D-BUS Service]`
     header line, then parses the remaining `key=value` lines with
     `environ_get_key` / `environ_get_value`. Extracts `Name`, `Exec`, `User`.
   - Validates that `name` and `exec` are non-empty (both are mandatory per the
     D-Bus specification).
   - `service_write_frontend()` — generates the 66 frontend file content and
     writes it to disk.
   - `service_add_hash()` — inserts into the hash table if not already present,
     assigns the next `nservice` ID, sets state to `DBS_SERVICE_INSERT`.

**Frontend file format** (as generated by `service_write_frontend`):

```
[Main]
Type = classic
Description = "<name> dbus service"
User = ( root|user )
Version = 0.0.1
InTree = dbus
MaxDeath = 5
TimeoutStart = 3000
TimeoutStop = 3000

[Start]
RunAs = <user>        ← only present if User= was set in .service file
Execute = (
    <exec>
)

[Environment]
ImportFile=<path to 0000-dbus>
```

`InTree = dbus` places every service in the `dbus` tree, enabling a single
`66 tree free dbus` to stop everything at shutdown.

The frontend is written to:

- Root: `<SS_SERVICE_ADMDIR>/<name>.dbus`
- User: `$HOME/<SS_SERVICE_USERDIR>/<name>.dbus`

### 6.4 Synchronization with the Broker

**`service_sync_launcher_broker()`** iterates the hash table:

```c
HASH_ITER(hh, *launcher->hservice, c, tmp) {
    if (FLAGS_ISSET(c->state, DBS_SERVICE_OK)) {
        if (FLAGS_ISSET(c->state, DBS_SERVICE_PARSE))
            service_reactivate(c);
        continue;
    }
    // build D-Bus object path: /org/bus1/DBus/Name/<id>
    if (FLAGS_ISSET(c->state, DBS_SERVICE_INSERT)) {
        sd_bus_call_method(bus_controller, NULL,
            "/org/bus1/DBus/Broker", "org.bus1.DBus.Broker", "AddName",
            NULL, NULL, "osu", path.s, c->name, 0);
        // state → DBS_SERVICE_OK
    } else if (FLAGS_ISSET(c->state, DBS_SERVICE_DELETE)) {
        sd_bus_call_method(bus_controller, NULL,
            path.s, "org.bus1.DBus.Name", "Release", NULL, NULL, "");
        service_discard(launcher, c);
    }
}
```

`AddName` signature: `(osu)` → object path, well-known name string, flags (0).
`Release` signature: `()` (no arguments) called on the name's own object path.

### 6.5 Activation, Reactivation, and Deactivation

All three operations invoke the 66 service manager as a child process via
`sync_spawn()` (blocking):

| Function                      | Command                          |
| ----------------------------- | -------------------------------- |
| `service_activate(id)`        | `66 -v <V> start <name>.dbus`    |
| `service_reactivate(service)` | `66 -v <V> parse -f <name>.dbus` |
| `service_deactivate(service)` | `66 -v <V> remove <name>.dbus`   |

`service_activate` looks up the service by numeric id in the hash table, then
appends the `.dbus` suffix before passing it to 66. The verbosity level
(`VERBOSITY` global from skalibs) is formatted as a string and passed through.

### 6.6 Teardown

**`service_discard(launcher, service)`**: calls `service_deactivate`, unlinks
the frontend file, removes the entry from the hash table.

**`service_discard_tree()`** (called at process exit from `main()`):

```c
char *nargv[] = { "66", "-T3000", "-v", fmt, "tree", "free", "dbus", 0 };
sync_spawn(nargv);
```

This removes the entire `dbus` tree from 66's supervision, stopping all services
that were in it. The `-T3000` sets a 3-second timeout for the tree removal.

---

## 7. Signal and Process Utilities — `util.c`

### `async_spawn` / `spawn_wait` / `sync_spawn`

```c
pid_t async_spawn(char **cmd)   // posix_spawnp, returns PID immediately
int   spawn_wait(pid_t p)       // waitpid with EINTR loop, returns exit code
int   sync_spawn(char **cmd)    // async_spawn + spawn_wait
```

`async_spawn` uses `posix_spawnp` with `NULL` for both `file_actions` and
`attrp`, inheriting the current environment via the `environ` extern. No fd
redirections or attribute changes are applied.

`spawn_wait` handles signals properly: `WIFSIGNALED` → `128 + WTERMSIG`,
`WIFEXITED` with non-zero status → that status, success → `0`.

### `handle_signal`

```c
// util.c:98
int handle_signal(launcher_t *launcher, pid_t ppid)
```

Drains the selfpipe with a `for(;;)` loop calling `selfpipe_read()`:

| Signal                           | Action                                                                 | Return                           |
| -------------------------------- | ---------------------------------------------------------------------- | -------------------------------- |
| `SIGHUP`                         | `service_reload(launcher)`                                             | `DBS_EXIT_CHILD` (continue loop) |
| `SIGTERM` / `SIGINT` / `SIGQUIT` | —                                                                      | `DBS_EXIT_MAIN` (exit loop)      |
| `SIGCHLD`                        | `wait_nohang` loop; if `cpid == ppid` (broker) → `compute_exit(wstat)` | varies                           |
| default                          | warning                                                                | `DBS_EXIT_WARN`                  |

`compute_exit(wstat)`: returns `DBS_EXIT_MAIN` (= 0) only if the broker exited
cleanly (`WIFEXITED && WEXITSTATUS == 0`). Any other termination returns a
non-zero code, propagating the broker's failure upward.

### `fdmove`

```c
int fdmove(int to, int from)
```

A `dup2`-with-EINTR-retry that closes the source after duplication. It is
declared but not called anywhere in the current codebase — likely a remnant from
an earlier design or a candidate for future use.

---

## 8. Policy — `policy.c`

The policy exported to `dbus-broker`'s `AddListener` call is intentionally
fully permissive. The header comment is explicit:

> At the moment, we just allow everything. The syntax of the policy is not
> stable yet.

The policy type string is built from two macros:

```c
// policy.h
#define POLICY_T_BATCH  "bt" "a(btbs)" "a(btssssuutt)" "a(btssssuutt)"
#define POLICY_T        "a(u(" POLICY_T_BATCH "))" \
                        "a(buu(" POLICY_T_BATCH "))" \
                        "a(ss)" "b" "s"
```

Three export functions each append to the message:

- `policy_export_connect` → `bt`: allow=true, priority=1
- `policy_export_own` → `a(btbs)`: one rule, allow=true, priority=1, allow_prefixes=true, prefix=""
- `policy_export_xmit` → `a(btssssuutt)`: one rule, all fields at wildcard/zero values

The return value of every `sd_bus_message_open_container` / `append` /
`close_container` call in `policy()` is stored in `r` but only the _last_
`sd_bus_message_close_container` result is actually returned. Intermediate
errors are silently ignored.

---

## 9. Error Handling and Resource Management

### Cleanup Attribute Pattern

```c
// macro.h
#define dbs_cleanup_(func)  __attribute__((__cleanup__(func)))

#define DBS_DEFINE_CLEANUP(_type, _func)        \
    static inline void _func ## p(_type *p) {   \
        if (*p) _func(*p);                      \
    } struct force_semicolon
```

Usage in `launcher_new`:

```c
dbs_cleanup_(launcher_freep) launcher_t *launcher = NULL;
```

`launcher_freep` is generated by `DBS_DEFINE_CLEANUP(launcher_t *, launcher_free)` in
`launcher.h`. When the local variable goes out of scope (on any return path,
including error), the compiler inserts a call to `launcher_freep(&launcher)`.
If the caller took ownership by setting `*plauncher = launcher; launcher = NULL`,
the cleanup is a no-op.

Similarly, `_alloc_stk_` / `_alloc_sa_` macros from oblibs use
`__attribute__((cleanup))` to automatically free stack-allocated buffers.

### Exit Codes

```c
// macro.h
#define DBS_EXIT_FATAL  -1   // unrecoverable error
#define DBS_EXIT_WARN    0   // non-fatal / continue
#define DBS_EXIT_MAIN    0   // event loop: normal exit
#define DBS_EXIT_CHILD   1   // event loop: continue iteration
```

`DBS_EXIT_WARN` and `DBS_EXIT_MAIN` share the value `0`, which can make the
return code of a function ambiguous in some contexts. Callers distinguish them
by context rather than value.

Process-level exit codes (from the documentation):

- `0` — success
- `100` — wrong usage (`LOG_EXIT_USER`)
- `111` — system call failed (`LOG_EXIT_SYS`)

### Return Convention

Functions generally return `1` on success and `-1` or `DBS_EXIT_FATAL` on
fatal error. `log_warn_return` / `log_warnu_return` / `log_warnusys_return`
macros log a warning and return the given value in one expression.

---

## 10. Build System Analysis

### 10.1 Project Metadata and Defaults

```
project('66-tools', 'c',
  version: '0.1.2.0',
  meson_version: '>=1.1.0',
  license: 'ISC',
  default_options: [
    'c_std=c99',
    'prefix=/usr',
    'enable-dbus=disabled',
    ...
  ])
```

The `enable-dbus=disabled` default means the `66-dbus-launch` binary is **not
built** unless explicitly requested. This avoids a hard dependency on basu or
elogind for users who only need the other tools.

### 10.2 Dependency Resolution

| Library         | Pkg-config / find_library | Required             | Version   |
| --------------- | ------------------------- | -------------------- | --------- |
| skalibs         | `libskarnet`              | yes                  | ≥2.14.3.0 |
| execline        | `libexecline`             | yes                  | ≥2.9.6.1  |
| oblibs          | `liboblibs`               | yes                  | ≥0.3.4.0  |
| 66              | `lib66`                   | yes                  | ≥0.8.0.0  |
| basu or elogind | pkg-config                | only if dbus enabled | —         |
| lowdown         | pkg-config                | only if docs enabled | ≥0.6.4    |

All dependencies support optional static linking via `enable-static-deps=true`,
which passes `static: true` to `find_library` and `dependency()`.

A mutual exclusion is enforced in `meson.build`:

```python
if get_option('enable-static-executable') and get_option('enable-shared'):
    error('Cannot enable both enable-static-executable and enable-shared')
if get_option('enable-static-deps') and get_option('enable-shared'):
    error('Cannot enable both enable-static-deps and enable-shared')
```

### 10.3 Compiler and Linker Flags

**Base C flags** (applied to all targets):

```
-pipe -fomit-frame-pointer
-fno-exceptions -fno-unwind-tables -fno-asynchronous-unwind-tables
-Werror=implicit-function-declaration -Werror=implicit-int
-Werror=pointer-sign -Werror=pointer-arith
-Wno-unused-value -Wno-parentheses
-ffunction-sections -fdata-sections
-D_POSIX_C_SOURCE=200809L -D_XOPEN_SOURCE=700 -D_GNU_SOURCE
```

The `-ffunction-sections -fdata-sections` flags combined with linker flag
`-Wl,--gc-sections` (enabled for static builds) remove unused code and data at
link time, keeping the binary size small.

`-fno-exceptions` and the unwind-table flags are relevant even in C, where they
suppress unnecessary EH frame generation.

**Shared library linker flags** include:

```
-Wl,--as-needed -Wl,--no-undefined -Wl,-O2
-Wl,--sort-section=alignment -Wl,--sort-common
```

`--as-needed` prevents linking against libraries that are not actually used,
which is especially important for the dbus-enabled build where elogind or basu
are pulled in.

### 10.4 Conditional DBus Feature

```python
# src/meson.build
if get_option('enable-dbus') != 'disabled'
    # Find all .c files in 66-dbus-launch/ except 66-dbus-launch.c
    find_dbus_sources_cmd = run_command('sh', '-c',
        'find "@0@" -maxdepth 1 -type f -name "*.c" ! -name "66-dbus-launch.c"'
        .format(dbus_launch_dir), check: false)

    lib66dbusbroker = static_library('66dbusbroker',
        lib66dbusbroker_sources,
        dependencies: [lib66_dep, oblibs_dep, skalibs_dep],
        install: false)      # internal only, not installed

    exe_configs += { '66-dbus-launch': {
        'sources': ['66-dbus-launch.c'],
        'deps': [lib66dbusbroker_dep, lib66_dep, oblibs_dep, skalibs_dep, dbus_dep]
    }}
endif
```

The support code is compiled into a **non-installed internal static library**
`lib66dbusbroker.a`. Only the entry point `66-dbus-launch.c` is compiled as
the executable source. This is an unusual but clean approach: it allows the
test harness to link against `lib66dbusbroker` without duplicating compilation.

The D-Bus backend is selected in `config.h`:

```c
// config.h.in
#undef SS_TOOLS_USE_BASU
#undef SS_TOOLS_USE_ELOGIND
@DEFINE_DBUS_LIB@
```

At build time, `DEFINE_DBUS_LIB` becomes either `#define SS_TOOLS_USE_BASU` or
`#define SS_TOOLS_USE_ELOGIND`. In `dbus.h`, the correct header is
conditionally included:

```c
#ifdef SS_TOOLS_USE_BASU
#  include <basu/sd-bus.h>
#  include <basu/sd-bus-vtable.h>
#else
#  ifdef SS_TOOLS_USE_ELOGIND
#    include <elogind/sd-bus.h>
#    include <elogind/sd-bus-vtable.h>
#  else
#    error No sd_bus backend configured
#  endif
#endif
```

This means the entire `sd_bus` API surface is fully abstracted; no source file
other than `dbus.h` (and the `config.h` it includes) cares which backend is in
use.

### 10.5 Configuration Header Generation

```python
# src/include/66-tools/meson.build
conf = configuration_data()
conf.set_quoted('SS_TOOLS_DBS_SYSTEM_SERVICE', dbus_system_service_dir + '/')
conf.set_quoted('SS_TOOLS_DBS_SESSION_SERVICE', dbus_session_service_dir + '/')
conf.set_quoted('SS_TOOLS_DBS_SYSTEM_NAME', dbus_system_name)
conf.set_quoted('SS_TOOLS_DBS_SESSION_NAME', dbus_session_name)
...
configure_file(input: 'config.h.in', output: 'config.h',
               configuration: conf, install: true, install_dir: INCLUDEDIR)
```

All compile-time-configurable paths and names are baked into `config.h`, which
is installed alongside the headers. This means the service directories and
socket names cannot be changed at runtime — they are hard-coded at build time.

### 10.6 Executable and Test Build

The `src/meson.build` uses a data-driven loop over `exe_configs` (a dict of
tool configs) combined with a filesystem scan of subdirectories. This avoids
per-tool boilerplate.

Optional tests are built when `test=true`:

```python
if get_option('test')
    test_dir = exe_dir / 'test'
    if fs.is_dir(test_dir)
        ...
        test('@0@_test'.format(exe), test_exe)
    endif
endif
```

Tests share the same dependency list as the executable, with the internal
`lib66dbusbroker_dep` substituted in for dbus tests.

---

## 11. Interaction Between Launcher and dbus-broker

The full sequence from process start to service activation:

```
main()
  │
  ├─ dbs_socket_bind()
  │     creates /run/dbus/system_bus_socket (or user variant)
  │     fd is stored as launcher->fd_dbus
  │
  ├─ service_load()
  │     for each .service file:
  │       parse Name/Exec/User
  │       write .dbus frontend to /etc/66/service/ (or ~/.66/service/)
  │       add to hash table with state=INSERT
  │
  ├─ launcher_run()
  │   │
  │   ├─ socketpair() → controller[0], controller[1]
  │   ├─ pipe() → sync[0], sync[1]
  │   │
  │   ├─ fork()
  │   │    ├─ CHILD: launcher_run_broker()
  │   │    │    ├─ drop privileges (if non-root)
  │   │    │    ├─ prctl(PR_SET_PDEATHSIG, SIGTERM)
  │   │    │    ├─ fcntl(controller[1], F_SETFD, flags & ~FD_CLOEXEC)
  │   │    │    ├─ write(sync[1], "\n", 1)  → unblocks parent
  │   │    │    └─ execve("/usr/bin/dbus-broker",
  │   │    │             ["--controller", "N", "--machine-id", "..."], env)
  │   │    │         dbus-broker now running, listening on controller[1]
  │   │    │
  │   │    └─ PARENT: close(controller[1])
  │   │               read(sync[0]) blocks until child writes
  │   │               close(sync[0])
  │   │
  │   └─ launcher_setup()
  │        ├─ sd_bus on controller[0]
  │        ├─ expose /org/bus1/DBus/Controller (ReloadConfig method)
  │        ├─ sd_bus_start()
  │        ├─ sd_bus_add_filter(launcher_on_message)
  │        ├─ AddListener(fd_dbus, policy)
  │        │     broker now accepting client connections on fd_dbus
  │        ├─ sd_bus_open_{user,system}() → bus_regular
  │        ├─ service_sync_launcher_broker()
  │        │     for each INSERT service:
  │        │       AddName(path, name, 0) → broker knows the name is activatable
  │        └─ launcher_drop_permissions() (parent)
  │
  ├─ write "\n" to notif fd (readiness notification)
  │
  └─ launcher_loop()
       iopause on [selfpipe, controller_in]
       │
       ├─ controller_in readable →
       │    sd_bus_process() →
       │      launcher_on_message() →
       │        Activate signal: service_activate(id)
       │          sync_spawn(["66", "-v", V, "start", "name.dbus"])
       │          on failure: Reset(serial) to broker
       │        SetActivationEnvironment: write 0000-dbus file
       │        ReloadConfig: service_reload()
       │
       ├─ selfpipe readable →
       │    handle_signal()
       │      SIGHUP: service_reload() → re-scan + sync
       │      SIGCHLD: waitpid all children; broker death → exit loop
       │      SIGTERM/INT/QUIT: exit loop
       │
       └─ loop exits

  service_discard_tree()
    sync_spawn(["66", "-T3000", "-v", V, "tree", "free", "dbus"])
```

---

## 12. Critical Observations and Design Trade-offs

### Bug: Inverted condition in `launcher_on_message`

**Location:** `launcher.c:351`

```c
suffix = str_start_with(obj_path, "/org/bus1/DBus/Name/");
if (!suffix) {
    // Activate signal handling
```

`str_start_with` (from oblibs) returns the length of the matched prefix, i.e.,
a positive non-zero value on a match. `!suffix` is therefore `true` when the
path does _not_ start with `/org/bus1/DBus/Name/`. The `Activate` branch is
thus entered for all other paths, and the `strcmp("/org/bus1/DBus/Broker")`
check in the else branch is unreachable for broker paths that also don't match
the name prefix.

The intended logic is almost certainly `if (suffix)` to handle name paths, and
`else if` for the broker path. In practice this means activation signals may
be handled for unrelated paths, and broker-originated signals may be missed.
This likely does not manifest as a visible bug in practice because the broker
only sends `Activate` on `/org/bus1/DBus/Name/<id>` paths and
`SetActivationEnvironment` on `/org/bus1/DBus/Broker`, and the actual body
of the `Activate` handler only runs if `sd_bus_message_is_signal` also passes.
However the control flow is logically incorrect and should be fixed.

### Policy return value ignored

**Location:** `policy.c:56-92`

Every `sd_bus_message_open_container` / `append` / `close_container` result is
stored in the same variable `r`, which is overwritten on every call. Only the
last `close_container` result is returned. If any intermediate container
operation fails, the error is silently discarded and the policy message will be
malformed. The `AddListener` call will then likely fail with a protocol error.

### Hard-coded dbus-broker path

**Location:** `launcher.c:207`

```c
"/usr/bin/dbus-broker"
```

This path is compiled in as a literal string, unlike the service directories
and socket names which are configurable via Meson options and baked into
`config.h`. On distributions that install `dbus-broker` elsewhere (e.g.,
`/usr/lib/dbus-broker`) this will silently fail at runtime with an `ENOENT`
from `execve`. It should be an `SS_TOOLS_BINPREFIX`-relative path or a
dedicated Meson option.

### Permissive-only policy

The broker policy currently allows all connections, name ownership, and message
transmission without restriction. The code acknowledges this explicitly. For
the system bus (root) instance this is a meaningful security gap: any client
that can connect to the socket gains unrestricted access to all services. The
dbus-broker policy format is not yet stable, so this is a known temporary
limitation.

### `sync_spawn` blocking in the event loop

Service activation (`service_activate`) calls `sync_spawn`, which blocks the
entire event loop for the duration of the `66 start` command. If that command
hangs (e.g., a service with a long `TimeoutStart`), the launcher will be
completely unresponsive to new activation requests and signals. An async
design (track child PIDs, handle completion in `SIGCHLD`) would be more robust
but significantly more complex.

### Linear scan `service_search_byid`

```c
HASH_ITER(hh, *hservice, c, tmp)
    if (c->id == id) return c;
```

The hash table is keyed by name, not id. A second hash table keyed by id, or
an array indexed by id (since IDs are monotonically assigned integers starting
at 1) would give O(1) lookup. With a typical number of D-Bus services (tens to
low hundreds) this is not a performance concern in practice.

### Startup service count check

In `main()`:

```c
r = service_load(launcher);
if (r <= 0)
    log_dieu(LOG_EXIT_SYS, "collect service");
```

`service_load` returns `1` on success and `DBS_EXIT_FATAL` (= -1) on error. It
_cannot_ return `0`, so the `r <= 0` check is equivalent to `r < 0`. More
importantly, if the service directory is empty (no `.service` files), the loop
simply does nothing and returns `1` — the launcher will start with zero
registered services, which is a valid configuration. The condition would be
wrong if `service_load` were intended to fail on an empty directory.

### Machine ID handling

```c
// launcher.c:453
launcher->machineid[r + 1] = 0;  // r is always 32 after the assignment
```

After the `exit:` label, `r` is unconditionally set to `32` regardless of
whether the `io_read` succeeded. This means the null terminator is always
placed at `machineid[33]` — one past the 32-char machine ID — which is correct
given `MACHINEID + 2` sizing. However if `io_read` returned less than 32
bytes, the remaining bytes would be uninitialised garbage. The fallback
`memcpy` path correctly zero-terminates at position 32, but the read path may
not.

---

## 13. Suggestions for Further Study and Improvement

1. **Fix `launcher_on_message` condition** (`!suffix` → `suffix`) to correctly
   route `Activate` signals only for name object paths.

2. **Make dbus-broker path configurable**: add a `dbus-broker-path` Meson option
   (defaulting to `SS_TOOLS_BINPREFIX dbus-broker`) and store it in `config.h`.

3. **Policy error propagation in `policy()`**: check each `sd_bus_message_*`
   return value and return early on failure rather than silently accumulating
   errors.

4. **Async service activation**: rather than `sync_spawn` (blocking), store the
   child PID and handle completion in the `SIGCHLD` path of `handle_signal`.
   This keeps the event loop responsive during long startups.

5. **Service ID secondary index**: maintain a small array or second hash table
   keyed on `id` to replace the linear scan in `service_search_byid`.

6. **Machine ID partial read handling**: if `io_read` returns fewer than 32
   bytes, zero-fill the remainder or fall back to the default sentinel.

7. **D-Bus configuration files**: the documentation notes that
   `/usr/share/dbus-1/{system,session}.conf` are not currently parsed.
   Supporting these files would enable per-bus policy, service restrictions, and
   limits — features the dbus-daemon always provided.

8. **`dbs_socket_bind` fd 0 trick**: the `close(0)` + `socket_open()` trick
   to land the socket on fd 0 is fragile in multi-threaded environments (though
   66-dbus-launch is single-threaded) and relies on implementation details of
   the fd allocator. A more explicit approach would use `dup2` or `fcntl` to
   move the fd to the desired slot after creation.

9. **`fdmove` is unused**: the function is defined in `util.c` and declared in
   `util.h` but never called. It should either be used where fd moves are
   needed or removed.

10. **Test coverage**: the test framework is wired up in `src/meson.build` but
    depends on a `test/` subdirectory existing inside `66-dbus-launch/`. No
    such directory exists in the current tree, so no tests are currently built
    or run for the launcher. Unit tests for `service_parse`,
    `service_write_frontend`, and the message filter logic would significantly
    improve confidence in correctness.
