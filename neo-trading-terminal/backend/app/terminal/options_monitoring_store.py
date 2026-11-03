"""Durable scheduling primitives, owner-private observations and alert transitions."""
import json
from datetime import UTC,datetime
from uuid import uuid4
from .options_platform_risk import PlatformRiskPolicy, MonitoringSettings, EquityImport

def _json(value): return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def _page(limit,offset):
    if type(limit)!=int or not 1<=limit<=100 or type(offset)!=int or not 0<=offset<=1000000: raise ValueError('Invalid pagination')
def _owner(owner):
    if type(owner)!=int or owner<=0: raise ValueError('Authenticated owner required')

class MonitoringStoreMixin:
    def _init_monitoring(self):
        with self._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS platform_policy(owner INTEGER PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS platform_monitor(owner INTEGER PRIMARY KEY,settings TEXT NOT NULL,status TEXT NOT NULL,next_due REAL NOT NULL,lease_until REAL,token TEXT,generation TEXT,cycle INTEGER NOT NULL DEFAULT 0,last_state TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS platform_alert(id TEXT PRIMARY KEY,owner INTEGER NOT NULL,cycle INTEGER NOT NULL,key TEXT NOT NULL,state TEXT NOT NULL,payload TEXT NOT NULL,created_at REAL NOT NULL,read_at REAL,ack_at REAL,UNIQUE(owner,cycle,key,state));
            CREATE TABLE IF NOT EXISTS platform_records(id TEXT PRIMARY KEY,owner INTEGER NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,created_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS platform_records_owner ON platform_records(owner,kind,created_at);
            CREATE TRIGGER IF NOT EXISTS platform_records_no_update BEFORE UPDATE ON platform_records
              BEGIN SELECT RAISE(ABORT,'immutable platform record'); END;
            CREATE TRIGGER IF NOT EXISTS platform_records_no_delete BEFORE DELETE ON platform_records
              BEGIN SELECT RAISE(ABORT,'immutable platform record'); END;
            CREATE TABLE IF NOT EXISTS platform_heavy(id TEXT PRIMARY KEY,owner INTEGER NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,token TEXT,lease_until REAL,created_at REAL NOT NULL);
            ''')

    def get_risk_policy(self,owner):
        _owner(owner)
        with self._db() as db: row=db.execute('SELECT payload FROM platform_policy WHERE owner=?',(owner,)).fetchone()
        return PlatformRiskPolicy.model_validate_json(row[0]) if row else PlatformRiskPolicy()

    def put_risk_policy(self,owner,policy):
        from .options_platform_store import PlatformConflictError
        _owner(owner);policy=PlatformRiskPolicy.model_validate(policy.model_dump())
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT revision FROM platform_policy WHERE owner=?',(owner,)).fetchone()
            revision=row[0] if row else 0
            if policy.revision!=revision: raise PlatformConflictError('Policy revision changed')
            updated=policy.model_copy(update={'revision':revision+1})
            db.execute('INSERT INTO platform_policy VALUES(?,?,?) ON CONFLICT(owner) DO UPDATE SET revision=excluded.revision,payload=excluded.payload',(owner,revision+1,updated.model_dump_json()))
        return updated

    def get_monitoring(self,owner):
        _owner(owner)
        with self._db() as db:
            row=db.execute('SELECT settings,status,next_due,lease_until,generation,cycle FROM platform_monitor WHERE owner=?',(owner,)).fetchone()
        if not row: return dict(settings=MonitoringSettings().model_dump(),status='disabled',next_due=None,lease_until=None,generation=None,cycle=0)
        return dict(zip(('settings','status','next_due','lease_until','generation','cycle'),(json.loads(row[0]),*row[1:])))

    def put_monitoring(self,owner,settings,*,now):
        _owner(owner);settings=MonitoringSettings.model_validate(settings.model_dump())
        with self._db() as db:
            # Revoking token also fences a worker racing a configuration change.
            db.execute('INSERT INTO platform_monitor(owner,settings,status,next_due) VALUES(?,?,?,?) ON CONFLICT(owner) DO UPDATE SET settings=excluded.settings,status=excluded.status,next_due=excluded.next_due,token=NULL,lease_until=NULL,last_state=\'{}\'',(owner,settings.model_dump_json(),'pending' if settings.enabled else 'disabled',now))
        return self.get_monitoring(owner)

    def monitor_owners(self,*,limit=100):
        _page(limit,0)
        with self._db() as db: return [r[0] for r in db.execute("SELECT owner FROM platform_monitor WHERE status!='disabled' ORDER BY next_due LIMIT ?",(limit,))]

    def suspend_monitor(self,owner,*,now):
        _owner(owner)
        with self._db() as db: db.execute("UPDATE platform_monitor SET status='suspended',token=NULL,lease_until=NULL,next_due=? WHERE owner=? AND status!='disabled'",(now,owner))

    def resume_monitor(self,owner,generation,*,now):
        _owner(owner)
        with self._db() as db:
            row=db.execute('SELECT settings,generation,status FROM platform_monitor WHERE owner=?',(owner,)).fetchone()
            if row and row[2]!='disabled' and (row[1]!=generation or row[2]=='suspended'):
                interval=json.loads(row[0])['interval_seconds']
                db.execute("UPDATE platform_monitor SET status='pending',generation=?,token=NULL,lease_until=NULL,next_due=? WHERE owner=?",(generation,now+interval,owner))

    def claim_monitor(self,owner,generation,*,now,lease_seconds=60):
        _owner(owner)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT status,next_due,lease_until,cycle FROM platform_monitor WHERE owner=?',(owner,)).fetchone()
            if not row or row[0] in ('disabled','suspended') or row[1]>now or (row[0]=='running' and row[2] is not None and row[2]>now): return None
            token=str(uuid4());cycle=row[3]+1
            db.execute("UPDATE platform_monitor SET status='running',token=?,lease_until=?,generation=?,cycle=? WHERE owner=?",(token,now+lease_seconds,generation,cycle,owner))
            return dict(token=token,generation=generation,cycle=cycle)

    def claim_monitor_unavailable(self,owner,generation,*,now,lease_seconds=60):
        """One assessed->unavailable transition independent of normal due time.

        Suspended jobs remain eligible if an earlier publication was interrupted.
        Existing assessed keys, exact generation and actual lease fences still
        apply; after publication no assessed keys remain to claim again.
        """
        _owner(owner)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT status,lease_until,cycle,generation,last_state FROM platform_monitor WHERE owner=?',(owner,)).fetchone()
            if (not row or row[0]=='disabled' or row[3]!=generation
                or (row[0]=='running' and row[1] is not None and row[1]>now)
                or not any(state in ('pass','breach') for state in json.loads(row[4]).values())): return None
            token=str(uuid4());cycle=row[2]+1
            db.execute("UPDATE platform_monitor SET status='running',token=?,lease_until=?,cycle=? WHERE owner=?",(token,now+lease_seconds,cycle,owner))
            return dict(token=token,generation=generation,cycle=cycle)

    def finish_monitor(self,owner,claim,states,*,now,report=None,_check=None):
        _owner(owner)
        if any(v not in ('pass','breach','cannot_assess','disabled') for v in states.values()): raise ValueError('Invalid outcome')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT settings,last_state FROM platform_monitor WHERE owner=? AND token=? AND generation=? AND cycle=? AND status=\'running\'',(owner,claim['token'],claim['generation'],claim['cycle'])).fetchone()
            if not row: return False
            if _check: _check()
            previous=json.loads(row[1]);interval=json.loads(row[0])['interval_seconds']
            for key,state in states.items():
                old=previous.get(key)
                if state==old or state=='disabled': continue
                if state=='breach' or (old in ('pass','breach') and state in ('pass','cannot_assess')):
                    kind='data_quality' if state=='cannot_assess' else 'recovery' if state=='pass' and old=='breach' else 'transition'
                    if state=='pass' and old!='breach': continue
                    payload=dict(id=str(uuid4()),key=key,previous_outcome=old,current_outcome=state,kind=kind,report_id=report.get('report_id') if report else None,evidence_ids=sorted({x for c in (report or {}).get('checks',[]) for x in c.get('evidence_ids',[])}))
                    db.execute('INSERT OR IGNORE INTO platform_alert(id,owner,cycle,key,state,payload,created_at) VALUES(?,?,?,?,?,?,?)',(payload['id'],owner,claim['cycle'],key,state,_json(payload),now))
            if report: db.execute('INSERT INTO platform_records VALUES(?,?,?,?,?)',(report['report_id'],owner,'risk',_json(report),now))
            db.execute("UPDATE platform_monitor SET status='pending',next_due=?,token=NULL,lease_until=NULL,last_state=? WHERE owner=?",(now+interval,_json(states),owner))
            if _check: _check()
        return True

    def list_alerts(self,owner,*,limit=50,offset=0):
        _owner(owner);_page(limit,offset)
        with self._db() as db: rows=db.execute('SELECT payload,created_at,read_at,ack_at FROM platform_alert WHERE owner=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',(owner,limit,offset)).fetchall()
        return [dict(json.loads(r[0]),created_at=r[1],read_at=r[2],acknowledged_at=r[3]) for r in rows]

    def finish_monitor_unavailable(self,owner,claim,*,now,reason='acquisition_unavailable',_check=None):
        """Preserve stable check keys and atomically transition via live claim."""
        _owner(owner)
        with self._db() as db:
            row=db.execute("SELECT last_state FROM platform_monitor WHERE owner=? AND token=? AND generation=? AND cycle=? AND status='running'",
                (owner,claim['token'],claim['generation'],claim['cycle'])).fetchone()
        if not row: return False
        previous=json.loads(row[0])
        states={key:'disabled' if state=='disabled' else 'cannot_assess' for key,state in previous.items()}
        if not states: states={'monitoring_acquisition':'cannot_assess'}
        report=dict(report_id=str(uuid4()),version='platform-risk-calculation.1',evaluated_at=datetime.fromtimestamp(now,UTC).isoformat(),
            acquisition_status='unavailable',coverage='unavailable',checks=[dict(key=key,outcome=state,value=None,limit=None,reason=reason,evidence_ids=[],report_ids=[]) for key,state in states.items()])
        return self.finish_monitor(owner,claim,states,now=now,report=report,_check=_check)

    def mark_alert(self,owner,id,action,*,now):
        _owner(owner)
        if action not in ('read','acknowledge'): raise ValueError('Invalid alert action')
        column='read_at' if action=='read' else 'ack_at'
        with self._db() as db:
            db.execute(f'UPDATE platform_alert SET {column}=COALESCE({column},?) WHERE owner=? AND id=?',(now,owner,str(id)))
            row=db.execute('SELECT payload,created_at,read_at,ack_at FROM platform_alert WHERE owner=? AND id=?',(owner,str(id))).fetchone()
        return dict(json.loads(row[0]),created_at=row[1],read_at=row[2],acknowledged_at=row[3]) if row else None

    def save_private_record(self,owner,kind,payload,*,now,_check=None):
        _owner(owner)
        if kind not in ('equity','association','portfolio','fills','risk','lot_ledger'): raise ValueError('Invalid record kind')
        id=str(uuid4())
        with self._db() as db:
            if _check: _check()
            db.execute('INSERT INTO platform_records VALUES(?,?,?,?,?)',(id,owner,kind,_json(payload),now))
            if _check: _check()
        return dict(id=id,**payload)

    def list_private_records(self,owner,kind,*,limit=50,offset=0):
        _owner(owner);_page(limit,offset)
        with self._db() as db: rows=db.execute('SELECT id,payload FROM platform_records WHERE owner=? AND kind=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',(owner,kind,limit,offset)).fetchall()
        return [dict(id=r[0],**json.loads(r[1])) for r in rows]

    def import_equity(self,owner,body,*,now):
        body=EquityImport.model_validate(body.model_dump())
        return self.save_private_record(owner,'equity',body.model_dump(mode='json'),now=now)

    def import_lot_ledger(self,owner,body,*,now):
        from .options_lot_ledger import LotLedgerImport
        body=LotLedgerImport.model_validate(body.model_dump())
        return self.save_private_record(owner,'lot_ledger',body.model_dump(mode='json'),now=now)

    def get_private_record(self,owner,kind,id):
        _owner(owner)
        with self._db() as db:
            row=db.execute('SELECT id,payload FROM platform_records WHERE owner=? AND kind=? AND id=?',(owner,kind,str(id))).fetchone()
        return dict(id=row[0],**json.loads(row[1])) if row else None

    def list_associations(self,owner,baseline_id,*,limit=50,offset=0):
        _owner(owner);_page(limit,offset)
        with self._db() as db:
            rows=db.execute("SELECT id,payload FROM platform_records WHERE owner=? AND kind='association' AND json_extract(payload,'$.baseline_id')=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",(owner,str(baseline_id),limit,offset)).fetchall()
        return [dict(id=r[0],**json.loads(r[1])) for r in rows]

    def enqueue_heavy(self,owner,kind,*,now):
        _owner(owner)
        if kind not in ('scan','backtest'): raise ValueError('Unsupported heavy job')
        from .options_platform_store import PlatformConflictError
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT count(*) FROM platform_heavy WHERE status IN ('pending','running')").fetchone()[0]>=20: raise PlatformConflictError('Heavy queue full')
            id=str(uuid4());db.execute('INSERT INTO platform_heavy VALUES(?,?,?,\'pending\',NULL,NULL,?)',(id,owner,kind,now))
        return id

    def claim_heavy(self,*,now,lease_seconds=60,kind=None):
        if kind not in (None,'scan','backtest'):raise ValueError('Unsupported heavy job')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            # Running work is explicitly finished by its actual worker; lease expiry
            # alone must not duplicate blocked local broker work.
            if db.execute("SELECT 1 FROM platform_heavy WHERE status='running'").fetchone(): return None
            row=db.execute("SELECT id,owner,kind FROM platform_heavy WHERE status='pending'"+(' AND kind=?' if kind else '')+" ORDER BY created_at,id LIMIT 1",(kind,) if kind else ()).fetchone()
            if not row: return None
            token=str(uuid4());db.execute("UPDATE platform_heavy SET status='running',token=?,lease_until=? WHERE id=?",(token,now+lease_seconds,row[0]))
        return dict(id=row[0],owner=row[1],kind=row[2],token=token)

    def finish_heavy(self,owner,id,token,*,status='completed'):
        _owner(owner)
        if status not in ('completed','failed','cancelled'): raise ValueError('Invalid job state')
        with self._db() as db: return db.execute("UPDATE platform_heavy SET status=?,token=NULL,lease_until=NULL WHERE owner=? AND id=? AND token=? AND status='running'",(status,owner,str(id),token)).rowcount==1
