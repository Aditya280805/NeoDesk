"""Synchronous, session-bound portfolio collection. Call from worker threads."""
import asyncio
import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4
from app.brokers.base_broker import BrokerError
from .portfolio_contracts import PortfolioIssue, SectionObservation
from .portfolio_normalization import normalize_portfolio


class PortfolioSnapshotService:
    def __init__(self, market, store):
        self.market, self.store = market, store

    def assert_generation(self, user_id: int, expected_generation: str, *, deadline_monotonic=None) -> None:
        self._acquire(self.market.lock, deadline_monotonic)
        try:
            sess = self.market.get_session(user_id)
            if sess.generation == expected_generation and not sess.broker.is_authenticated:
                sess.generation = str(uuid4())
                sess.portfolio_cache = None
            if sess.generation != expected_generation:
                raise BrokerError('Portfolio session changed. Sign in again or refresh.')
        finally:
            self.market.lock.release()

    def _session(self, user_id, expected_generation, deadline):
        self._acquire(self.market.lock, deadline)
        try:
            self.assert_generation(user_id, expected_generation)
            return self.market.get_session(user_id)
        finally:
            self.market.lock.release()

    @staticmethod
    def _check(deadline):
        if deadline is not None and time.monotonic() >= deadline:
            raise BrokerError('Portfolio request deadline expired.')

    def _acquire(self, lock, deadline):
        self._check(deadline)
        if deadline is None:
            lock.acquire()
        elif not lock.acquire(timeout=max(0, deadline-time.monotonic())):
            raise BrokerError('Portfolio request deadline expired.')
        self._check_after_acquire(lock, deadline)

    def _check_after_acquire(self, lock, deadline):
        try:
            self._check(deadline)
        except Exception:
            lock.release()
            raise

    def fetch(self, user_id: int, *, expected_generation: str, force: bool = False, deadline_monotonic: float | None = None):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError('Portfolio collection requires a worker thread.')
        self._check(deadline_monotonic)
        sess = self._session(user_id, expected_generation, deadline_monotonic)
        self._acquire(sess.portfolio_lock, deadline_monotonic)
        try:
            self._session(user_id, expected_generation, deadline_monotonic)
            cached = sess.portfolio_cache
            if not force and cached and time.monotonic()-cached[0] < 15:
                result = cached[1].model_copy(deep=True)
                result.evidence_id = uuid4()
                result.cache_age_seconds = Decimal(str(max(0,time.monotonic()-cached[0])))
                self._session(user_id, expected_generation, deadline_monotonic)
                return result
            # Release the database connection before any broker call.
            with self.store.connect() as db:
                catalogue = [json.loads(r[0]) for r in db.execute('SELECT payload FROM instruments').fetchall()]
            observations, limited, shortened = {}, set(), set()
            for name, method in [('holdings','holdings'),('positions','positions'),('funds','limits'),('orders','order_report')]:
                self._check(deadline_monotonic)
                self._session(user_id, expected_generation, deadline_monotonic)
                started = datetime.now(UTC)
                raw, error = None, None
                self._acquire(self.market.call_lock, deadline_monotonic)
                try:
                    self._session(user_id, expected_generation, deadline_monotonic)
                    self._check(deadline_monotonic)
                    try:
                        raw = self.market.call(method, user_id=user_id, **({"deadline_monotonic":deadline_monotonic} if deadline_monotonic is not None else {}))
                    except TimeoutError:
                        raise BrokerError('Portfolio request deadline expired.') from None
                    except Exception:
                        error = 'fetch_failed'
                    self._check(deadline_monotonic)
                    self._session(user_id, expected_generation, deadline_monotonic)
                finally:
                    self.market.call_lock.release()
                if error is None:
                    try:
                        data = raw.get('data',raw) if isinstance(raw,dict) else raw
                        if isinstance(data,list) and len(data)>1000 or len(json.dumps(raw,ensure_ascii=False).encode('utf-8'))>1048576:
                            limited.add(name); raw = None
                    except (TypeError,ValueError,OverflowError,RecursionError):
                        limited.add(name); raw = None
                    def bounded(value, key=None):
                        if key in ('description','displayName','companyName','message') and isinstance(value,str) and len(value)>160:
                            shortened.add(name)
                            return value[:160]
                        if isinstance(value,dict): return {k:bounded(v,k) for k,v in value.items()}
                        if isinstance(value,list): return [bounded(v) for v in value]
                        return value
                    raw = bounded(raw)
                observations[name] = SectionObservation(raw=raw,error_code=error,retrieval_started_at=started,retrieval_finished_at=datetime.now(UTC))
            result = normalize_portfolio(observations,catalogue,observed_at=datetime.now(UTC))
            for name in limited:
                sec=result.sections[name]; sec.state='invalid'; sec.issues=[PortfolioIssue(code='payload_limit')]
            for name in shortened:
                sec=result.sections[name]; sec.issues.append(PortfolioIssue(code='string_shortened'))
                if sec.state=='available': sec.state='partial'
            def usable(name, sec):
                if sec.state in ('invalid','unavailable'): return False
                if name == 'funds': return any(v is not None for v in sec.values.values())
                return not sec.rows or any(r.quantity is not None or r.provider_pnl is not None or r.order_id for r in sec.rows)
            if not any(usable(name, sec) for name, sec in result.sections.items()):
                raise BrokerError('Kotak portfolio services are unavailable. Please refresh shortly.')
            if any(sec.state!='available' for sec in result.sections.values()): result.completeness='partial'
            self._check(deadline_monotonic)
            self._acquire(self.market.lock, deadline_monotonic)
            try:
                self.assert_generation(user_id, expected_generation)
                sess.portfolio_cache = (time.monotonic(),result.model_copy(deep=True))
            finally:
                self.market.lock.release()
            return result
        finally:
            sess.portfolio_lock.release()
