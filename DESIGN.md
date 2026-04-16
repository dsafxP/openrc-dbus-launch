# `openrc-dbus-launch` Design Document

## References

1. D-Bus basics

   * [https://dbus.freedesktop.org/doc/dbus-tutorial.html](https://dbus.freedesktop.org/doc/dbus-tutorial.html)
   * [https://dbus.freedesktop.org/doc/dbus-specification.html](https://dbus.freedesktop.org/doc/dbus-specification.html)
   * [https://dbus.freedesktop.org/doc/dbus-api-design.html](https://dbus.freedesktop.org/doc/dbus-api-design.html)

2. Reference daemon behavior

   * [https://dbus.freedesktop.org/doc/dbus-daemon.1.html](https://dbus.freedesktop.org/doc/dbus-daemon.1.html)
   * [https://dbus.freedesktop.org/doc/dbus-daemon.1.html#configuration_file](https://dbus.freedesktop.org/doc/dbus-daemon.1.html#configuration_file)
   * `/usr/share/dbus-1/system.conf`
   * `/usr/share/dbus-1/session.conf`
   * `/etc/dbus-1/`

3. dbus-broker architecture

   * [https://man.archlinux.org/man/dbus-broker.1.en](https://man.archlinux.org/man/dbus-broker.1.en)
   * [https://man.archlinux.org/man/dbus-broker-launch.1.en](https://man.archlinux.org/man/dbus-broker-launch.1.en)
   * [https://github.com/bus1/dbus-broker/wiki/Integration](https://github.com/bus1/dbus-broker/wiki/Integration)
   * [https://github.com/bus1/dbus-broker/blob/main/docs/dbus-broker.rst](https://github.com/bus1/dbus-broker/blob/main/docs/dbus-broker.rst)
   * [https://github.com/bus1/dbus-broker/tree/main/src/launch](https://github.com/bus1/dbus-broker/tree/main/src/launch)

4. Socket and controller model

   * `man 7 unix`
   * `man 3 sd_listen_fds`
   * `man 3 sd_notify`
   * [https://man7.org/linux/man-pages/man7/daemon.7.html](https://man7.org/linux/man-pages/man7/daemon.7.html)
   * [https://man7.org/linux/man-pages/man7/unix.7.html](https://man7.org/linux/man-pages/man7/unix.7.html)

5. OpenRC service design

   * [https://github.com/OpenRC/openrc/blob/master/user-guide.md](https://github.com/OpenRC/openrc/blob/master/user-guide.md)
   * [https://github.com/OpenRC/openrc/blob/master/service-script-guide.md](https://github.com/OpenRC/openrc/blob/master/service-script-guide.md)
   * [https://github.com/OpenRC/openrc](https://github.com/OpenRC/openrc)

6. Existing non-systemd experience

   * https://wiki.gentoo.org/wiki/Hard_dependencies_on_systemd
   * https://git.obarun.org/Obarun/66-tools/-/tree/dev/src/66-dbus-launch

7. Development and testing tools

   * [https://jeepney.readthedocs.io/en/latest/](https://jeepney.readthedocs.io/en/latest/)
   * `busctl`
   * `gdbus`
   * `dbus-send`
   * `dbus-monitor`
   * `dbus-run-session`
   * `dbus-test-tool`