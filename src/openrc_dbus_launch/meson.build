py.install_sources(
  [
    '__main__.py',
    'cli.py',
    'constants.py',
    'logger.py',
  ],
  subdir: 'openrc_dbus_launch',
)

# The generated config.py lives in the build dir; install it alongside the package.
install_data(
  meson.project_build_root() / 'config.py',
  install_dir: py.get_install_dir() / 'openrc_dbus_launch',
)
