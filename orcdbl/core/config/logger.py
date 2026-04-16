__all__ = ['logcfg', 'loglvl', 'internal_log']

import logging as internal_log
from enum import Enum
from typing import Final, Type


class LogCfg:
    class Levels(Enum):
        # Flags
        ALL = -100
        UNDEFINED = -400
        # Actual levels
        INFO = internal_log.INFO
        DEBUG = internal_log.DEBUG
        WARNING = internal_log.WARNING
        ERROR = internal_log.ERROR
        CRITICAL = internal_log.CRITICAL

    int_to_str: dict[Levels, str] = {
        Levels.INFO: 'INFO',
        Levels.DEBUG: 'DEBUG',
        Levels.WARNING: 'WARNING',
        Levels.ERROR: 'ERROR',
        Levels.CRITICAL: 'CRITICAL',
    }
    str_to_int: dict[str, Levels] = {
        'INFO': Levels.INFO,
        'DEBUG': Levels.DEBUG,
        'WARNING': Levels.WARNING,
        'ERROR': Levels.ERROR,
        'CRITICAL': Levels.CRITICAL,
    }

    level_keys: list[str] = str_to_int.keys()  # pyrefly: ignore[bad-assignment]
    # This is built on the main function by using build_enabled_levels.
    enabled_levels: list[Levels] = [Levels.CRITICAL]

    def lazy_build_enabled_log_levels(self, against: Levels) -> None:
        lvl = self.Levels
        if against == lvl.ALL:
            self.enabled_levels += [
                lvl.DEBUG,
                lvl.INFO,
                lvl.WARNING,
                lvl.ERROR,
            ]
            return

        # Specific level - only that level
        self.enabled_levels += list({against})


# Log instances
logcfg: Final[LogCfg] = LogCfg()
loglvl: Final[Type[LogCfg.Levels]] = logcfg.Levels
