"""Single-process durable backtest worker sharing the global heavy lease.

Inputs and completed reports are immutable. The event cursor and ledger publish
in the same SQLite transaction, fenced by the claimed generation token. Recovery
is startup-only after the preceding local worker has stopped, never lease expiry.
"""
import asyncio
import hashlib
import json
import re
import time
from threading import Event
from uuid import uuid4
from .options_history import HistoryStore, canonical
from .options_history_contracts import BacktestRequest
from .options_backtest import HistoricalEngine
from .options_platform_store import _owner, PlatformConflictError, PlatformStoreBusyError

TERMINAL={'completed','cancelled','failed'}

class BacktestService:
    def __init__(self,platform,*,clock=time.time):
        self.platform=platform;self.history=HistoryStore(platform);self.clock=clock
        self.task=None;self.stopping=Event();self.pending=None;self.active_claim=None;self.last_error=None
        with platform._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS options_backtest_inputs(id TEXT PRIMARY KEY,owner INTEGER NOT NULL,request TEXT NOT NULL,input_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS options_backtest_jobs(id TEXT PRIMARY KEY,owner INTEGER NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS options_backtest_reports(id TEXT PRIMARY KEY,owner INTEGER NOT NULL,payload TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS backtest_input_no_update BEFORE UPDATE ON options_backtest_inputs BEGIN SELECT RAISE(ABORT,'immutable backtest inputs'); END;
            CREATE TRIGGER IF NOT EXISTS backtest_input_no_delete BEFORE DELETE ON options_backtest_inputs BEGIN SELECT RAISE(ABORT,'immutable backtest inputs'); END;
            CREATE TRIGGER IF NOT EXISTS backtest_report_no_update BEFORE UPDATE ON options_backtest_reports BEGIN SELECT RAISE(ABORT,'immutable backtest report'); END;
            CREATE TRIGGER IF NOT EXISTS backtest_report_no_delete BEFORE DELETE ON options_backtest_reports BEGIN SELECT RAISE(ABORT,'immutable backtest report'); END;
            ''')

    def create(self,owner,request):
        _owner(owner);r=BacktestRequest.model_validate(request)
        dataset=self.history.load(owner,r.dataset_id)
        if dataset is None:raise KeyError('Dataset not found')
        engine=HistoricalEngine(dataset,r) # fail unsupported inputs before queuing
        now=self.clock();id=str(uuid4());body=r.model_dump(mode='json')
        input_hash=hashlib.sha256(canonical(dict(request=body,dataset_hash=dataset['content_hash'])).encode()).hexdigest()
        job=dict(id=id,status='queued',cursor=0,event_count=len(engine.events),state=engine.initial,next_due=now,cancel_requested=False,created_at=now,error=None)
        with self.platform._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT count(*) FROM platform_heavy WHERE status IN ('pending','running')").fetchone()[0]>=20:raise PlatformConflictError('Heavy queue full')
            db.execute("INSERT INTO platform_heavy VALUES(?,?,?,'pending',NULL,NULL,?)",(id,owner,'backtest',now))
            db.execute('INSERT INTO options_backtest_inputs VALUES(?,?,?,?)',(id,owner,canonical(body),input_hash))
            db.execute('INSERT INTO options_backtest_jobs VALUES(?,?,?)',(id,owner,canonical(job)))
        return self.get(owner,id)

    def get(self,owner,id):
        _owner(owner)
        with self.platform._db() as db:
            row=db.execute('SELECT j.payload,i.request,i.input_hash FROM options_backtest_jobs j JOIN options_backtest_inputs i ON i.id=j.id WHERE j.owner=? AND j.id=?',(owner,str(id))).fetchone()
            report=db.execute('SELECT payload FROM options_backtest_reports WHERE owner=? AND id=?',(owner,str(id))).fetchone()
        if row is None:return None
        job=json.loads(row[0]);job.pop('state',None)
        return dict(job,request=json.loads(row[1]),input_hash=row[2],report=json.loads(report[0]) if report else None)

    def list(self,owner,*,limit=50,offset=0):
        _owner(owner)
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=1000000:raise ValueError('Invalid page')
        with self.platform._db() as db:ids=[r[0] for r in db.execute('SELECT id FROM options_backtest_jobs WHERE owner=? ORDER BY rowid DESC LIMIT ? OFFSET ?',(owner,limit,offset))]
        return [self.get(owner,id) for id in ids]

    def cancel(self,owner,id):
        _owner(owner)
        with self.platform._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM options_backtest_jobs WHERE owner=? AND id=?',(owner,str(id))).fetchone()
            if row is None:return None
            job=json.loads(row[0])
            if job['status'] not in TERMINAL:
                job['cancel_requested']=True
                heavy=db.execute('SELECT status FROM platform_heavy WHERE id=?',(str(id),)).fetchone()
                if heavy[0]!='running':
                    job['status']='cancelled';db.execute("UPDATE platform_heavy SET status='cancelled' WHERE id=?",(str(id),))
                db.execute('UPDATE options_backtest_jobs SET payload=? WHERE id=?',(canonical(job),str(id)))
        return self.get(owner,id)

    def defer(self,owner,id,*,next_due):
        """Infrastructure backoff only; never alters immutable simulation inputs."""
        _owner(owner)
        with self.platform._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT j.payload FROM options_backtest_jobs j JOIN platform_heavy h ON h.id=j.id WHERE j.owner=? AND j.id=? AND h.status='pending'",(owner,str(id))).fetchone()
            if row:
                job=json.loads(row[0]);job['next_due']=next_due
                db.execute('UPDATE options_backtest_jobs SET payload=? WHERE id=?',(canonical(job),str(id)))

    def recover(self):
        with self.platform._db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE platform_heavy SET status='pending',token=NULL,lease_until=NULL WHERE kind='backtest' AND status='running'")

    def _publish(self,claim,job,report):
        with self.platform._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT j.payload,i.input_hash FROM options_backtest_jobs j JOIN platform_heavy h ON h.id=j.id JOIN options_backtest_inputs i ON i.id=j.id WHERE h.id=? AND h.owner=? AND h.token=? AND h.status='running' AND h.kind='backtest'",(claim['id'],claim['owner'],claim['token'])).fetchone()
            if row is None:return False
            current=json.loads(row[0])
            if current['cancel_requested']:
                # Discard the unpublished event, retaining the last durable cursor.
                job=current;job['status']='cancelled';report=None
            if report is not None:
                report=dict(report,input_hash=row[1],request_id=claim['id'])
                db.execute('INSERT INTO options_backtest_reports VALUES(?,?,?)',(claim['id'],claim['owner'],canonical(report)))
            db.execute('UPDATE options_backtest_jobs SET payload=? WHERE id=?',(canonical(job),claim['id']))
            db.execute('UPDATE platform_heavy SET status=?,token=NULL,lease_until=NULL WHERE id=? AND token=?',(job['status'] if job['status'] in TERMINAL else 'pending',claim['id'],claim['token']))
        return True

    def tick_sync(self):
        if self.pending:
            claim,job,report=self.pending
            self._publish(claim,job,report);self.pending=None;self.active_claim=None;self.last_error=None
            return True
        # Check our due time before claiming. claim_heavy's explicit kind filter
        # cannot acquire scans; any running kind prevents a second heavy worker.
        if self.active_claim is None:
            with self.platform._db() as db:
                first=db.execute("SELECT j.payload FROM platform_heavy h JOIN options_backtest_jobs j ON j.id=h.id WHERE h.kind='backtest' AND h.status='pending' ORDER BY h.created_at,h.id LIMIT 1").fetchone()
            if first is None or json.loads(first[0])['next_due']>self.clock():return False
            self.active_claim=self.platform.claim_heavy(now=self.clock(),lease_seconds=900,kind='backtest')
        claim=self.active_claim
        if claim is None:return False
        with self.platform._db() as db:
            row=db.execute('SELECT j.payload,i.request FROM options_backtest_jobs j JOIN options_backtest_inputs i ON i.id=j.id WHERE j.id=? AND j.owner=?',(claim['id'],claim['owner'])).fetchone()
        job=json.loads(row[0]);report=None
        if job['next_due']>self.clock():
            self.pending=(claim,job,None)
            self._publish(claim,job,None);self.pending=None;self.active_claim=None;return False
        try:
            if job['cancel_requested']:job['status']='cancelled'
            else:
                r=BacktestRequest.model_validate_json(row[1]);dataset=self.history.load(claim['owner'],r.dataset_id)
                engine=HistoricalEngine(dataset,r)
                job['state']=engine.step(job['state']);job['cursor']=job['state']['cursor'];job['status']='queued';job['next_due']=self.clock()
                if job['cursor']==len(engine.events):job['status']='completed';report=engine.report(job['state'])
        except PlatformStoreBusyError:raise
        except Exception as exc:
            job['status']='failed';code=str(exc)
            job['error']=code if re.fullmatch(r'[a-z_]{1,80}',code) else 'calculation_unavailable'
        self.pending=(claim,job,report)
        self._publish(claim,job,report);self.pending=None;self.active_claim=None;self.last_error=None
        return True

    async def tick(self):return await asyncio.to_thread(self.tick_sync)

    async def start(self):
        if self.task and not self.task.done():return
        self.stopping.clear()
        if self.pending is None and self.active_claim is None:await asyncio.to_thread(self.recover)
        async def run():
            while not self.stopping.is_set():
                try:await self.tick()
                except PlatformStoreBusyError:self.last_error='backtest_storage_busy'
                except Exception:self.last_error='backtest_worker_unavailable'
                await asyncio.sleep(0.1)
        self.task=asyncio.create_task(run())

    async def stop(self):
        self.stopping.set()
        # Await actual event publication. No recovery or second worker can overlap.
        if self.task:await self.task;self.task=None
