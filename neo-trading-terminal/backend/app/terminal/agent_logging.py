"""
Structured Agno framework logging.

Adapted from agent-template/src/utils/logger.py.  Integrates with
NeoDesk's existing OptionsLogFilter so that provider exception bodies,
credentials, and prompt text are never emitted by the ``agno`` or
``agno-team`` loggers during options runs.

Call ``setup_agent_logging()`` once during FastAPI lifespan, before
entering the MCP lifespan.
"""
import logging
import os
import sys


def _make_handler(level: int) -> logging.StreamHandler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
    ))
    return handler


def setup_agno_logging() -> None:
    """Configure Agno agent and team loggers with structured formatting.

    The ``OptionsLogFilter`` from ``options_model`` is attached to each
    handler so that log records emitted during an active options run
    have their message, arguments, and exception details suppressed.
    This prevents SDK internals from leaking provider secrets or
    broker credentials into log sinks.
    """
    from agno.utils.log import configure_agno_logging
    from app.terminal.options_model import OptionsLogFilter

    debug = os.getenv('AGNO_DEBUG', 'false').lower() == 'true'
    level = logging.DEBUG if debug else logging.WARNING

    log_filter = OptionsLogFilter()

    for logger_name in ('agno', 'agno-team'):
        target = logging.getLogger(logger_name)
        target.setLevel(level)
        if not any(getattr(h, '_neodesk_agno', False) for h in target.handlers):
            handler = _make_handler(level)
            handler._neodesk_agno = True
            target.addHandler(handler)
        for handler in target.handlers:
            if not any(isinstance(f, OptionsLogFilter) for f in handler.filters):
                handler.addFilter(log_filter)
        target.propagate = False

    configure_agno_logging(
        custom_agent_logger=logging.getLogger('agno'),
        custom_team_logger=logging.getLogger('agno-team'),
        enable_log_tracebacks=False,
    )


setup_agent_logging = setup_agno_logging
