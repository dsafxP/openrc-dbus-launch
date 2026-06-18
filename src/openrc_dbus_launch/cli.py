__all__ = ['flags', 'cli']

from dataclasses import dataclass
from typing import Final, NoReturn, final

import click

from config import VERSION
from constants import *
from logger import *


@final
@dataclass
class CLIFlags:
    log_level: loglvl = loglvl.INFO
    pass


flags: Final[CLIFlags] = CLIFlags()
"""Single module-level instance, access the given CLI flags."""

_help = ['-h', '--help']
_version = ['-V', '--version']


# noinspection PyUnusedLocal
def _log_level_callback(ctx: click.Context, param: click.Parameter, value: str) -> loglvl:
    return logcfg.str_to_int[value]


def lazy_init_flags(**kwargs) -> None:
    # wizardry
    for key, value in kwargs.items():
        if hasattr(flags, key):
            setattr(flags, key, value)


@click.command(context_settings={'help_option_names': _help})
@click.version_option(
    VERSION,
    '-V',
    '--version',
)
@click.option(
    *['-Ll', '--log-level'],
    default=logcfg.int_to_str[flags.log_level],
    type=click.Choice(logcfg.level_keys, case_sensitive=False),
    show_default=True,
    callback=_log_level_callback,
    help='Logging verbosity.',
)
def cli(**kwargs) -> NoReturn:
    # We lazily initialize stuff here so that we can catch any issues early
    lazy_init_flags(**kwargs)

    logcfg.lazy_build_enabled_log_levels(flags.log_level)

    raise SystemExit(_main())


def _main() -> int:
    try:
        log.info('main hit')
        return 0
    except Exception as e:
        log.critical(e)
        return exitc.ABORTED
    finally:
        ...
