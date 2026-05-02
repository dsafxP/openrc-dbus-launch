project(
  'openrc-dbus-launch',
  'c',                        # keep 'c' ready for fdpass_shim; drop if shim lands in its own subdir
  version: '0.0.1.dev0',
  license: 'BSD-2-Clause',
  meson_version: '>= 1.1.0',
  default_options: ['warning_level=2'],
)

# Python installation
py = import('python').find_installation(
  'python3',
  required: true,
  # modules: ['jeepney'],       # hard-fail early if the runtime dep is missing (how is this failing lol)
)

# Resolve user-facing options into variables used by subdirs + config header
openrc_initddir  = get_option('openrc_initddir')
openrc_confddir  = get_option('openrc_confddir')
rundir           = get_option('rundir')
dbus_broker_path = get_option('dbus_broker_path')
fdpass_shim      = get_option('fdpass_shim')

# Validate that dbus_broker_path looks like an absolute path.
# Meson has no built-in path validator, so a quick assert catches the
# most obvious mistake (someone passing a bare name like 'dbus-broker').
assert(
  dbus_broker_path.startswith('/'),
  'dbus_broker_path must be an absolute path, got: ' + dbus_broker_path,
)

# Bake resolved paths into a config module importable from Python source
configure_file(
  input:  'src/openrc_dbus_launch/config.py.in',
  output: 'config.py',                           # lands in the build dir
  configuration: {
    'DBUS_BROKER_PATH' : dbus_broker_path,
    'RUNDIR'           : rundir,
    'OPENRC_INITDDIR'  : openrc_initddir,
    'OPENRC_CONFDDIR'  : openrc_confddir,
    'VERSION'          : meson.project_version(),
  },
)

# Optional fdpass shim
if fdpass_shim.allowed()
  # subdir('fdpass')        # uncomment when the subdir exists
  message('fdpass_shim: enabled (subdir pending)')
endif

# Subdirectories
subdir('src/openrc_dbus_launch')
# subdir('data')            # init scripts, conf.d templates — add when ready
# subdir('tests')           # add when ready
