__all__ = ['ORCDBL', 'odl']

from typing import Final, final

from orcdbl.core.config.logger import *
from orcdbl.core.constants import *
from orcdbl.utils.cli import *
from orcdbl.utils.logger import *


def _main() -> int:
    try:
        log.info('main hit')
        return 0
    except Exception as e:
        log.critical(e)
        return exitc.ABORTED
    finally:
        ...


@final
class ORCDBL:
    """OpenRC D-Bus Launch"""

    @staticmethod
    def run() -> int:
        # We lazily initialize stuff here so that we can catch any issues early
        try:
            # noinspection PyArgumentList
            lazy_init_flags(standalone_mode=False)
        except Exception as e:
            # Yes, this is the weird solution mentioned at `cli._on_help`.
            if f'{e}' == 'cli.help':
                return 0

        logcfg.lazy_build_enabled_log_levels(flags.log_level)

        return _main()


odl: Final[ORCDBL] = ORCDBL()
"""
Short name for `ORCDBL` (OpenRC D-Bus Launch). We do not expose the class directly, but you may 
import it manually if you wish.
"""
