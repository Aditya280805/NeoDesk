"""Durable scan cursor and a single heavy lease shared with future backtests."""
import asyncio
import hashlib
import json
import time
import math
from email.utils import parsedate_to_datetime
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4
from fastapi import HTTPException
from .options_platform_store import _owner, PlatformConflictError, PlatformStoreBusyError
import logging
from .options_scanner import ScanCriteria, scan_evidence, rank_candidates
from .options_snapshot import OptionsContext
from .options_readiness import fetch_strategy_market_evidence
from .market import MarketQuotaError

def _json(value): return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)

def retry_delay(value,now):
    try:seconds=float(value)
    except (ValueError,TypeError):
        try:seconds=parsedate_to_datetime(str(value)).timestamp()-now
        except (ValueError,TypeError,OverflowError):seconds=60
    if not math.isfinite(seconds):seconds=60
    return max(60,min(300,seconds))

class ScanJobStore:
    def __init__(self,platform):
        self.platform=platform
        with platform._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS platform_scans(id TEXT PRIMARY KEY,owner INTEGER NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS platform_scan_reports(id TEXT PRIMARY KEY,owner INTEGER NOT NULL,payload TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS scan_report_no_update BEFORE UPDATE ON platform_scan_reports BEGIN SELECT RAISE(ABORT,'immutable scan report'); END;
            CREATE TRIGGER IF NOT EXISTS scan_report_no_delete BEFORE DELETE ON platform_scan_reports BEGIN SELECT RAISE(ABORT,'immutable scan report'); END;
            ''')

    def create(self,owner,criteria,universe,*,now):
        _owner(owner);criteria=ScanCriteria.model_validate(criteria.model_dump())
        id=str(uuid4());job=dict(id=id,owner=owner,status='queued',criteria=criteria.model_dump(mode='json'),universe=universe,
            cursor=0,contracts_visited=0,candidates=[],exclusions=[],evidence_ids=[],retries=0,next_due=now,created_at=now,deadline=now+900,cancel_requested=False,coverage_partial=False)
        with self.platform._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT count(*) FROM platform_heavy WHERE status IN ('pending','running')").fetchone()[0]>=20: raise PlatformConflictError('Heavy queue full')
            db.execute("INSERT INTO platform_heavy VALUES(?,?,?,'pending',NULL,NULL,?)",(id,owner,'scan',now))
            db.execute('INSERT INTO platform_scans VALUES(?,?,?)',(id,owner,_json(job)))
        return job

    def get(self,owner,id):
        _owner(owner)
        with self.platform._db() as db:
            row=db.execute('SELECT payload FROM platform_scans WHERE owner=? AND id=?',(owner,str(id))).fetchone()
            report=db.execute('SELECT payload FROM platform_scan_reports WHERE owner=? AND id=?',(owner,str(id))).fetchone()
        return dict(json.loads(row[0]),report=json.loads(report[0]) if report else None) if row else None

    def list(self,owner,*,limit=50,offset=0):
        _owner(owner)
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=1000000: raise ValueError('Invalid page')
        with self.platform._db() as db: rows=db.execute('SELECT payload FROM platform_scans WHERE owner=? ORDER BY rowid DESC LIMIT ? OFFSET ?',(owner,limit,offset)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def cancel(self,owner,id):
        _owner(owner)
        with self.platform._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM platform_scans WHERE owner=? AND id=?',(owner,str(id))).fetchone()
            if not row: return None
            job=json.loads(row[0])
            if job['status'] not in ('completed','partial','cancelled','failed'):
                job['cancel_requested']=True
                heavy=db.execute('SELECT status FROM platform_heavy WHERE id=?',(str(id),)).fetchone()
                if heavy[0]!='running':
                    job['status']='cancelled';db.execute("UPDATE platform_heavy SET status='cancelled' WHERE id=?",(str(id),))
                db.execute('UPDATE platform_scans SET payload=? WHERE id=?',(_json(job),str(id)))
        return job

    def recover(self):
        # Single backend process startup only. Actual workers survive orchestration
        # cancellation within a process; start refuses while any local tick exists.
        with self.platform._db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE platform_heavy SET status='pending',token=NULL,lease_until=NULL WHERE kind='scan' AND status='running'")

    def claim(self,*,now):
        with self.platform._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM platform_heavy WHERE status='running'").fetchone(): return None
            rows=db.execute("SELECT h.id,s.payload FROM platform_heavy h JOIN platform_scans s ON h.id=s.id WHERE h.status='pending' AND h.kind='scan' ORDER BY h.created_at,h.id").fetchall()
            for id,payload in rows:
                job=json.loads(payload)
                if job['next_due']>now: continue
                token=str(uuid4());job['status']='running'
                db.execute("UPDATE platform_heavy SET status='running',token=?,lease_until=? WHERE id=?",(token,now+900,id))
                db.execute('UPDATE platform_scans SET payload=? WHERE id=?',(_json(job),id))
                return job,token
        return None

    def publish(self,job,token,*,terminal=False):
        with self.platform._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT s.payload FROM platform_scans s JOIN platform_heavy h ON h.id=s.id WHERE h.id=? AND h.owner=? AND h.token=? AND h.status='running'",(job['id'],job['owner'],token)).fetchone()
            if not row: return False
            current=json.loads(row[0])
            if current['cancel_requested']:
                current['status']='cancelled';job=current;terminal=True
            if terminal and job['status'] in ('completed','partial'):
                report=dict(version='options-scan.1',calculation_version='options-strategy.1',ranking_policy='exact-expiry-net-yield.1',criteria=job['criteria'],universe=job['universe'],
                    evidence_ids=job['evidence_ids'],candidates=rank_candidates(job['candidates']),exclusions=job['exclusions'],underlyings_covered=job['cursor'],
                    underlyings_total=len(job['universe']['underlyings']),contracts_visited=job['contracts_visited'],contracts_total=job['universe']['total_contracts'],
                    visited_combinations=job.get('visited_combinations',0),total_combinations=job.get('total_combinations',0),missing_combinations=job.get('missing_combinations',0),
                    underlyings_with_evidence=len(job['evidence_ids']),missing_underlyings=max(0,len(job['universe']['underlyings'])-len(job['evidence_ids'])),completed_at=datetime.now(UTC).isoformat(),limitations=['One lot per combination; yield is maximum expiry net profit/current capital, not a universal risk adjusted score.','Broker margin unavailable.'])
                db.execute('INSERT INTO platform_scan_reports VALUES(?,?,?)',(job['id'],job['owner'],_json(report)))
            db.execute('UPDATE platform_scans SET payload=? WHERE id=?',(_json(job),job['id']))
            db.execute('UPDATE platform_heavy SET status=?,token=NULL,lease_until=NULL WHERE id=?',('completed' if terminal and job['status']=='partial' else job['status'] if terminal else 'pending',job['id']))
        return True

def catalogue_universe(store,as_of):
    """Raw descriptor establishes stock-v-index scope; never inspect symbols."""
    result=store.search(exchange='nse_fo',kind='OPTION',limit=5000)
    rows=result['items'];total=result.get('total',len(rows));eligible=[];groups={};unknown=0
    for row in rows:
        meta=row.get('source_metadata',{})
        if meta.get('source')!='kotak-scrip-master' or meta.get('pInstType') not in ('OPTSTK','OPTIDX'):
            unknown+=1;continue
        if meta['pInstType']!='OPTSTK': continue
        # Expiry parsing uses the existing explicit date normalizer; unknown stays out.
        from .options_snapshot import expiry_identity
        try: expiry=datetime.strptime(expiry_identity(str(row.get('expiry',''))),'%Y-%m-%d').date()
        except ValueError: unknown+=1;continue
        if expiry<=as_of.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Kolkata')).date(): continue
        underlying=row.get('underlying')
        if not underlying: unknown+=1;continue
        eligible.append(row['id']);groups.setdefault(underlying,set()).add(expiry.isoformat())
    ids=sorted(eligible)
    return dict(version='nse-stock-options-universe.1',as_of=as_of.isoformat(),instrument_ids=ids,hash=hashlib.sha256(_json(ids).encode()).hexdigest(),
        status='complete' if total==len(rows) and unknown==0 and bool(ids) else 'unavailable',total_contracts=len(ids),catalogue_total=total,unknown_contracts=unknown,
        underlyings=[dict(underlying=u,expiries=sorted(groups[u])) for u in sorted(groups)],coverage_evidence='kotak-scrip-master exact pInstType=OPTSTK; bounded complete catalogue required')

class OptionsScannerService:
    def __init__(self,platform,*,clock=time.time,acquire=None,universe=None):
        self.platform=platform;self.jobs=ScanJobStore(platform.store);self.clock=clock
        self.acquire=acquire or self._acquire;self.universe=universe or (lambda:catalogue_universe(platform.agent.store,datetime.now(UTC)))
        self.task=None;self.tick_task=None;self.stopping=Event();self.pending_publication=None;self.last_error=None

    async def _publish(self,job,token,*,terminal=False,generation=None):
        def commit():
            market=self.platform.agent.market
            with market.lock:
                if generation is not None and market.session_generation(job['owner'])!=generation:
                    # Discard the unpublished outcome; preserve the durable cursor.
                    current=self.jobs.get(job['owner'],job['id']);current.pop('report',None)
                    current['status']='cancelled'
                    return self.jobs.publish(current,token,terminal=True)
                return self.jobs.publish(job,token,terminal=terminal)
        try:
            await asyncio.to_thread(commit)
            self.pending_publication=None;self.last_error=None
        except PlatformStoreBusyError:
            retries=1 if self.pending_publication is None else self.pending_publication[4]+1
            self.pending_publication=(job,token,terminal,generation,retries,self.clock()+min(60,5*retries))
            self.last_error='scan_publication_busy'
            logging.getLogger(__name__).warning('Scan publication deferred after storage contention')

    def create(self,owner,criteria): return self.jobs.create(owner,criteria,self.universe(),now=self.clock())

    def _acquire(self,owner,entry,deadline,check):
        a=self.platform.agent;parts=[]
        for expiry in entry['expiries']:
            check();parts.append(fetch_strategy_market_evidence(a.market,a.store,owner,OptionsContext(underlying=entry['underlying'],expiry=expiry),deadline=deadline))
            if sum(len(p.contracts) for p in parts)>=500:break
        # Evidence stays bounded and never invents identity/stock metadata absent
        # from Task1. The pure scanner exposes precise missing-leg exclusions.
        from .options_market_contracts import StrategyMarketEvidence
        contracts={c.instrument_id:c for p in parts for c in p.contracts};quotes={q.contract_id:q for p in parts for q in p.quotes}
        evidence=StrategyMarketEvidence(contracts=tuple(contracts.values())[:500],quotes=tuple(q for id,q in quotes.items() if id in set(list(contracts)[:500]))[:500],observed_at=datetime.now(UTC),source='kotak-scanner',completeness='partial',limitations=('Current per-contract corporate-action identity and exchange timestamps require independent verification.',))
        holdings=()
        # Portfolio proof is server acquired, never accepted with public criteria.
        if entry.get('_scope')=='owned':
            generation=a.market.session_generation(owner)
            snapshot=a.mcp.portfolio_service.fetch(owner,expected_generation=generation,force=True,deadline_monotonic=deadline)
            a.mcp.portfolio_service.assert_generation(owner,generation,deadline_monotonic=deadline)
            holdings=self.platform._holdings(snapshot,evidence)
        check();return evidence,holdings

    async def tick(self):
        if self.pending_publication is not None:
            job,token,terminal,generation,retries,due=self.pending_publication
            if self.clock()<due:return False
            await self._publish(job,token,terminal=terminal,generation=generation)
            return True
        claimed=await asyncio.to_thread(self.jobs.claim,now=self.clock())
        if not claimed:return False
        job,token=claimed
        try:
            criteria=ScanCriteria.model_validate(job['criteria']);entries=job['universe']['underlyings']
            if job['cancel_requested']: job['status']='cancelled';await self._publish(job,token,terminal=True);return True
            if job['universe']['status']!='complete' or job['cursor']>=len(entries) or job['cursor']>=100 or job['contracts_visited']>=1000 or self.clock()>=job['deadline']:
                if job['universe']['status']!='complete':job['exclusions'].append(dict(reason='universe_unavailable',status='cannot_assess'))
                job['status']='completed' if job['universe']['status']=='complete' and job['cursor']>=len(entries) and not job.get('coverage_partial') else 'partial'
                await self._publish(job,token,terminal=True);return True
            def operation(deadline,admission_check):
                generation=self.platform.agent.market.session_generation(job['owner'])
                def check():
                    admission_check()
                    if self.platform.agent.market.session_generation(job['owner'])!=generation:raise InterruptedError()
                    current=self.jobs.get(job['owner'],job['id'])
                    if self.stopping.is_set() or current['cancel_requested']: raise InterruptedError()
                    if self.clock()>=job['deadline']: raise TimeoutError()
                evidence,holdings=self.acquire(job['owner'],dict(entries[job['cursor']],_scope=criteria.scope),deadline,check)
                check()
                remaining=1000-job['contracts_visited']
                truncated=len(evidence.contracts)>remaining
                if truncated:
                    ids={c.instrument_id for c in evidence.contracts[:remaining]}
                    evidence=evidence.model_copy(update={'contracts':evidence.contracts[:remaining],'quotes':tuple(q for q in evidence.quotes if q.contract_id in ids),'completeness':'partial'})
                market=self.platform.agent.market
                if not market.lock.acquire(timeout=max(0,deadline-time.monotonic())):raise TimeoutError()
                try:
                    check()
                    if market.session_generation(job['owner'])!=generation:raise ValueError('Session changed')
                    self.platform.store.save_market_evidence(job['owner'],evidence,_check=check)
                finally:market.lock.release()
                result=scan_evidence(criteria,evidence,holdings,datetime.fromtimestamp(self.clock(),UTC),combination_limit=max(0,1000-job.get('visited_combinations',0)))
                result['coverage_partial']=truncated or evidence.completeness!='complete'
                check();return evidence,result,generation
            try:
                evidence,result,generation=await self.platform._admitted(job['owner'],operation,background=True)
            except MarketQuotaError as quota:
                raise HTTPException(429,'Broker quota',headers={'Retry-After':str(quota.retry_after)}) from None
            job['evidence_ids'].append(str(evidence.evidence_id));job['candidates']+=result['candidates'];job['exclusions']+=result['exclusions']
            job['contracts_visited']+=len(evidence.contracts);job['cursor']+=1;job['retries']=0;job['next_due']=self.clock()+5
            for key in ('visited_combinations','total_combinations','missing_combinations'):job[key]=job.get(key,0)+result[key]
            job['coverage_partial']=job.get('coverage_partial',False) or result['coverage_partial'] or result['partial']
            job['status']='partial' if result['budget_exhausted'] else 'queued'
            terminal=result['budget_exhausted'] or job['cursor']>=len(entries)
            if terminal and job['status']!='partial':job['status']='partial' if job['coverage_partial'] else 'completed'
            await self._publish(job,token,terminal=terminal,generation=generation)
        except HTTPException as exc:
            # Admission timeouts may leave shielded broker work alive. Keep the
            # shared heavy lease until the actual worker exits, including cancel.
            survivors=tuple(self.platform.agent.workers.get(job['owner'],()))
            if survivors: await asyncio.gather(*(asyncio.shield(t) for t in survivors),return_exceptions=True)
            if exc.status_code in (409,429):
                job['retries']+=1;retry=(exc.headers or {}).get('Retry-After','60')
                job['next_due']=self.clock()+retry_delay(retry,self.clock());job['status']='paused_quota'
                terminal=job['retries']>=3
                if terminal:job['status']='partial'
                await self._publish(job,token,terminal=terminal)
            else:
                job['coverage_partial']=True
                job['exclusions'].append(dict(underlying=entries[job['cursor']]['underlying'],reason='acquisition_unavailable',status='cannot_assess'))
                job['cursor']+=1;job['status']='queued';job['next_due']=self.clock()+5
                await self._publish(job,token)
        except InterruptedError:
            job['status']='cancelled' if not self.stopping.is_set() else 'queued';job['next_due']=self.clock()+5
            await self._publish(job,token,terminal=job['status']=='cancelled')
        except asyncio.CancelledError:
            survivors=tuple(self.platform.agent.workers.get(job['owner'],()))
            if survivors:await asyncio.gather(*(asyncio.shield(t) for t in survivors),return_exceptions=True)
            job['status']='queued';job['next_due']=self.clock()+5
            await self._publish(job,token)
            raise
        except Exception:
            # Publication errors are infrastructure failures, never leg outcomes.
            # A lifecycle retry recovers the unchanged durable cursor.
            if job['cursor']>=len(entries):raise
            job['coverage_partial']=True
            job['exclusions'].append(dict(underlying=entries[job['cursor']]['underlying'],reason='acquisition_unavailable',status='cannot_assess'))
            job['cursor']+=1;job['status']='queued';job['next_due']=self.clock()+5
            await self._publish(job,token)
        return True

    async def start(self):
        if (self.task and not self.task.done()) or (self.tick_task and not self.tick_task.done()): return
        if self.platform.agent.workers:return # never recover over actual local work
        self.stopping.clear()
        if self.pending_publication is None:await asyncio.to_thread(self.jobs.recover)
        async def run():
            while True:
                self.tick_task=asyncio.create_task(self.tick())
                try:await asyncio.shield(self.tick_task)
                except Exception:
                    self.last_error='scan_tick_failed'
                    logging.getLogger(__name__).exception('Scan lifecycle tick failed; recovering after worker completion')
                    if not self.platform.agent.workers and self.pending_publication is None:
                        try:await asyncio.to_thread(self.jobs.recover)
                        except Exception:logging.getLogger(__name__).exception('Scan recovery deferred')
                await asyncio.sleep(1)
        self.task=asyncio.create_task(run())

    async def stop(self):
        self.stopping.set()
        if self.task:
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass
            self.task=None
