__all__ = ['logcfg', 'loglvl', 'log_handler', 'log']

from datetime import datetime
from html import escape
from typing import Any, Type, Final, final
from enum import Enum
import logging as _log

from prompt_toolkit import HTML, print_formatted_text


class LogCfg:
    class Levels(Enum):
        # Flags
        ALL = -100
        UNDEFINED = -400
        # Actual levels
        INFO = _log.INFO
        DEBUG = _log.DEBUG
        WARNING = _log.WARNING
        ERROR = _log.ERROR
        CRITICAL = _log.CRITICAL

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


logcfg: Final[LogCfg] = LogCfg()
loglvl: Final[Type[LogCfg.Levels]] = logcfg.Levels


@final
class LoggerHandler:
    def __init__(self) -> None:
        """
        The LoggerHandler prints colorful logs to the terminal.
        """
        self.logger = _log.getLogger(__name__)
        self.logger.setLevel(loglvl.DEBUG.value)
        self._colors: dict[logcfg.Levels, str] = {
            loglvl.DEBUG: '#45fcff',  # Light cyan
            loglvl.INFO: '#7bd88f',  # Light green
            loglvl.WARNING: '#ff9900',  # Orange
            loglvl.ERROR: '#fc618d',  # Pinkish-red
            loglvl.CRITICAL: '#800024',  # Dark red
        }

        # At this point everything is ready to use. We should be able to use self.log from here,
        # but avoid doing so. It would be best to configure the logger in the main function rather than here.
        # If we use self.log here, it will work, sure. The main problem is that not everything in utils.config is
        # initialized at this point, raising undefined behavior.

    @staticmethod
    def get_final_message(level: loglvl, message: str) -> dict[str, str]:
        """
        Returns:

        - "logl" -> log_level
        - "time" -> timestamp
        - "msg" -> final_message
        - "fmsg" -> Well formatted string with timestamp and final_message.
        """
        # If this causes a crash, is the developer's fault.
        log_level = logcfg.int_to_str[level]
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        final_message = f'{log_level} - {message}'
        return {
            'logl': log_level,
            'time': timestamp,
            'msg': final_message,
            'fmsg': f'{timestamp} - {final_message}',
        }

    def html(self, msg: str, level: loglvl = loglvl.UNDEFINED) -> HTML:
        """Helper: Returns a formatted HTML message. Uses log levels to format the color quicker."""
        color = self._colors.get(level, '#291f1c')
        return HTML(f'<style fg="{color}">{escape(str(msg))}</style>')

    def log(self, level: loglvl, *message: Any, sep: str = ' ', end: str = '\n') -> None:
        """Prompts the `*message` into the stream with colored formatting."""
        m: str = sep.join(str(arg) for arg in message)
        final_message = self.get_final_message(level, m + end)

        # Print to stdout
        if level in logcfg.enabled_levels:
            print_formatted_text(self.html(final_message['msg'], level), sep='', end='')


log_handler = LoggerHandler()


class Logger:
    @staticmethod
    def debug(*message: Any, sep=' ', end='\n') -> None:
        log_handler.log(loglvl.DEBUG, *message, sep=sep, end=end)

    @staticmethod
    def info(*message: Any, sep=' ', end='\n') -> None:
        log_handler.log(loglvl.INFO, *message, sep=sep, end=end)

    @staticmethod
    def warning(*message: Any, sep=' ', end='\n') -> None:
        log_handler.log(loglvl.WARNING, *message, sep=sep, end=end)

    @staticmethod
    def error(*message: Any, sep=' ', end='\n') -> None:
        log_handler.log(loglvl.ERROR, *message, sep=sep, end=end)

    @staticmethod
    def critical(*message: Any, sep=' ', end='\n') -> None:
        log_handler.log(loglvl.CRITICAL, *message, sep=sep, end=end)

    @staticmethod
    def raw(*message: Any, sep=' ', end='\n') -> None:
        """
        Prompts the literal same message into the stream, with some formatting.

        Against the `log_handler.log` method, this method will simply not add the datetime and level into the stream;
        this also means that levels are not considered a rule, always printing into the stdout.

        Separators and final characters will still apply to the formatting, including injected HTML messages.
        """
        print_formatted_text(HTML(sep.join(str(arg) for arg in message) + end), sep='', end='')


log = Logger()
