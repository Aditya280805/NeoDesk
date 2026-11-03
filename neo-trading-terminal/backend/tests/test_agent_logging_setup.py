import logging


def test_setup_preserves_handlers_and_suppresses_sensitive_run_records():
    from app.terminal.agent_logging import setup_agno_logging
    from app.terminal.options_model import options_run
    for name in ('agno', 'agno-team'):
        logger = logging.getLogger(name)
        existing = logging.StreamHandler()
        logger.addHandler(existing)
        try:
            setup_agno_logging()
            setup_agno_logging()
            assert existing in logger.handlers
            assert sum(getattr(h, '_neodesk_agno', False) for h in logger.handlers) == 1
            record = logging.LogRecord(name, logging.ERROR, '', 1, 'secret=%s', ('sensitive',), None)
            token = options_run.set(True)
            try:
                for filt in existing.filters:
                    filt.filter(record)
                assert 'sensitive' not in record.getMessage()
            finally:
                options_run.reset(token)
        finally:
            logger.removeHandler(existing)
