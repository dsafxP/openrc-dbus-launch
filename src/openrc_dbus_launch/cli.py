__all__ = ['flags', 'lazy_init_flags']

from dataclasses import dataclass
from typing import Final, NoReturn, Optional, final

import click

from logger import *


@final
@dataclass
class CLIFlags:
    log_level: loglvl = loglvl.INFO
    pass


flags: Final[CLIFlags] = CLIFlags()
"""Single module-level instance, access the given CLI flags."""

_help = ['-h', '--help']


# noinspection PyUnusedLocal
def _on_help(ctx: click.Context, param: click.Parameter, value: bool) -> Optional[NoReturn]:
    if not value or ctx.resilient_parsing:
        return
    click.echo(ctx.get_help())
    ctx.close()
    # For some reason, click.exceptions.Exit does not work here.
    # This is a weird solution, I know.
    raise Exception('cli.help')
    # raise click.exceptions.Exit(1)


# noinspection PyUnusedLocal
def _log_level_callback(ctx: click.Context, param: click.Parameter, value: str) -> loglvl:
    return logcfg.str_to_int[value]


@click.command(context_settings={'help_option_names': _help})
@click.option(
    *_help,
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_on_help,
    help='Show this message and exit.',
)
@click.option(
    *['-Ll', '--log-level'],
    default=logcfg.int_to_str[flags.log_level],
    type=click.Choice(logcfg.level_keys, case_sensitive=False),
    show_default=True,
    callback=_log_level_callback,
    help='Logging verbosity.',
)
def lazy_init_flags(**kwargs) -> None:
    # wizardry
    for key, value in kwargs.items():
        if hasattr(flags, key):
            setattr(flags, key, value)

    if flags.disable_simulation or flags.virtual_users == 0:  # pyrefly: ignore[missing-attribute]
        flags.disable_simulation = True  # pyrefly: ignore[missing-attribute]
        flags.virtual_users = 0  # pyrefly: ignore[missing-attribute]
