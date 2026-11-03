"""Bounded private CSV/Parquet import; immutable owner manifest and raw records.

No pickle, archives, network access, symbol inference, forward filling or logs.
Parquet financial columns accept Arrow decimal/string/null types only. Floats
are deliberately rejected rather than accepting lossy execution evidence.
"""
import csv
import hashlib
import io
import json
from datetime import datetime, date, timedelta, UTC
from decimal import Decimal
from uuid import uuid4
from pydantic import TypeAdapter, AwareDatetime
from .options_history_contracts import ImportDeclaration, exact_money, MAX_BYTES, MAX_ROWS
from .options_platform_store import _owner
from .options_market_contracts import decimal_text

MONEY={'strike','deliverable_quantity','bid','ask','bid_quantity','ask_quantity','price','amount','ratio'}
BASE={'row_type','record_id','contract_id','timestamp','effective_at','known_at','source'}
FIELDS={
 'contract':{'kind','underlying_id','exchange','currency','lot_size','expiry','strike','deliverable_quantity','adjustment_id','settlement_rule'},
 'quote':{'bid','ask','bid_quantity','ask_quantity'},
 'settlement':{'price','settlement_rule','verified'},
 'corporate_action':{'action','amount','ratio','adjustment_id','adjusted_contract_ids'},
}
ALL=BASE|set().union(*FIELDS.values())
TIME=TypeAdapter(AwareDatetime)

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def stamp(value):return TIME.validate_python(value).astimezone(UTC).isoformat()

class HistoryValidationError(ValueError):
    def __init__(self,row,code='invalid_schema'):
        self.row=row;self.code=code;self.message=f'Historical row {row}: {code}.'
        super().__init__(self.message)

def _normalise(raw):
    if not isinstance(raw,dict) or None in raw or any(k not in ALL for k in raw):raise ValueError()
    r={k:v for k,v in raw.items() if v is not None and v!=''}
    if any(not isinstance(v,(str,Decimal)) or len(str(v))>500 for v in r.values()):raise ValueError()
    r={k:str(v) for k,v in r.items()}
    kind=r.get('row_type')
    if kind not in FIELDS or not BASE.issubset(r) or set(r)-BASE-FIELDS[kind]:raise ValueError()
    if any(not r[k].strip() or len(r[k])>120 for k in ('record_id','contract_id')):raise ValueError()
    for k in ('timestamp','effective_at','known_at'):r[k]=stamp(r[k])
    for k in MONEY&r.keys():r[k]=decimal_text(exact_money(r[k]))
    def required(*keys):
        if any(k not in r for k in keys):raise ValueError()
    if kind=='contract':
        required('kind','underlying_id','exchange','currency','lot_size','deliverable_quantity','adjustment_id','settlement_rule')
        if r['kind'] not in ('equity','call','put') or r['exchange']!='NSE' or r['currency']!='INR':raise ValueError()
        if not r['lot_size'].isdigit() or not 0<int(r['lot_size'])<=1000000:raise ValueError()
        if Decimal(r['deliverable_quantity'])!=1:raise ValueError() # adjusted contracts must express per-current-share strikes/lots
        if r['settlement_rule']!='physical-european.1':raise ValueError()
        if r['kind']=='equity':
            if 'expiry' in r or 'strike' in r:raise ValueError()
        else:
            required('expiry','strike');date.fromisoformat(r['expiry'])
    elif kind=='quote':
        required('bid','ask')
        if Decimal(r['bid'])>Decimal(r['ask']) or r['effective_at']!=r['timestamp']:raise ValueError()
    elif kind=='settlement':
        required('price','settlement_rule','verified')
        if r['settlement_rule']!='physical-european.1' or r['verified']!='true':raise ValueError()
    else:
        required('action','adjustment_id','adjusted_contract_ids')
        if r['action'] not in ('cash_dividend','split'):raise ValueError()
        required('amount' if r['action']=='cash_dividend' else 'ratio')
        if r['action']=='split' and Decimal(r['ratio'])<=0:raise ValueError()
    return r

def parse_history(payload,format,declaration):
    declaration=ImportDeclaration.model_validate(declaration)
    if type(payload) is not bytes or len(payload)>MAX_BYTES:raise HistoryValidationError(0,'size_limit')
    if format not in ('csv','parquet'):raise HistoryValidationError(0,'unsupported_format')
    try:
        if format=='csv':
            csv.field_size_limit(4096)
            reader=csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))
            if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)) or set(reader.fieldnames)-ALL:raise ValueError()
            iterator=reader
        else:
            import pyarrow as pa
            import pyarrow.parquet as pq
            parquet=pq.ParquetFile(io.BytesIO(payload),thrift_string_size_limit=1024*1024,thrift_container_size_limit=100000)
            if parquet.metadata.num_rows>MAX_ROWS or parquet.metadata.num_columns>len(ALL) or sum(parquet.metadata.row_group(i).total_byte_size for i in range(parquet.num_row_groups))>64*1024*1024:raise HistoryValidationError(0,'size_limit')
            schema=parquet.schema_arrow
            if len(schema.names)!=len(set(schema.names)) or set(schema.names)-ALL:raise ValueError()
            for f in schema:
                if not (pa.types.is_string(f.type) or pa.types.is_null(f.type) or (f.name in MONEY and pa.types.is_decimal(f.type))):raise ValueError()
            iterator=(r for b in parquet.iter_batches(batch_size=1024,use_threads=False) for r in b.to_pylist())
        records=[];ids={};keys={}
        for number,raw in enumerate(iterator,2):
            if number>MAX_ROWS+1:raise HistoryValidationError(number,'row_limit')
            try:r=_normalise(raw)
            except Exception:raise HistoryValidationError(number) from None
            key=(r['row_type'],r['contract_id'],r['effective_at'])
            if r['record_id'] in ids or key in keys:
                if ids.get(r['record_id'])!=r or keys.get(key)!=r:raise HistoryValidationError(number,'contradictory_duplicate')
                continue
            ids[r['record_id']]=r;keys[key]=r;records.append(r)
        if not records:raise ValueError()
    except HistoryValidationError:raise
    except Exception:raise HistoryValidationError(0) from None
    contracts={r['contract_id'] for r in records if r['row_type']=='contract'}
    versions=[r for r in records if r['row_type']=='contract']
    for number,r in enumerate(records,2):
        if r['row_type']!='contract' and r['contract_id'] not in contracts:raise HistoryValidationError(number,'invalid_reference')
        if r['row_type']=='contract' and r['underlying_id'] not in contracts:raise HistoryValidationError(number,'invalid_reference')
        if r['row_type']=='corporate_action':
            adjusted=r['adjusted_contract_ids'].split('|')
            affected={v['contract_id'] for v in versions if v['underlying_id']==r['contract_id']}
            if set(adjusted)!=affected or any(not any(v['contract_id']==id and v['effective_at']==r['effective_at'] and v['known_at']<=r['effective_at'] and v['adjustment_id']==r['adjustment_id'] for v in versions) for id in adjusted):raise HistoryValidationError(number,'adjustment_metadata_missing')
    gaps=[];expected=0
    quotes={(r['contract_id'],r['timestamp']) for r in records if r['row_type']=='quote'}
    for window in declaration.expected_intervals:
        if window.contract_id not in contracts:raise HistoryValidationError(0,'invalid_reference')
        t=window.start
        while t<=window.end:
            expected+=1
            if expected>MAX_ROWS:raise HistoryValidationError(0,'coverage_limit')
            if (window.contract_id,stamp(t)) not in quotes:gaps.append(dict(contract_id=window.contract_id,timestamp=stamp(t)))
            t+=timedelta(seconds=window.interval_seconds)
    records.sort(key=lambda r:(r['effective_at'],r['row_type'],r['contract_id'],r['record_id']))
    public=declaration.model_dump(mode='json');public['expected_intervals']=[dict(w, start=stamp(w['start']),end=stamp(w['end'])) for w in public['expected_intervals']]
    content_hash=hashlib.sha256(canonical(dict(rows=records,declaration=public)).encode()).hexdigest()
    return dict(rows=records,content_hash=content_hash,declaration=public,coverage=dict(expected_quotes=expected,gaps=gaps,status='gaps' if gaps else 'declared_complete'),range=dict(start=min(r['timestamp'] for r in records),end=max(r['timestamp'] for r in records)),schema_version='options-history.1')

class HistoryStore:
    def __init__(self,platform):
        self.platform=platform
        with platform._db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS options_history(id TEXT PRIMARY KEY,owner INTEGER NOT NULL,manifest TEXT NOT NULL,raw TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS history_no_update BEFORE UPDATE ON options_history BEGIN SELECT RAISE(ABORT,'immutable history'); END;
            CREATE TRIGGER IF NOT EXISTS history_no_delete BEFORE DELETE ON options_history BEGIN SELECT RAISE(ABORT,'immutable history'); END;''')
    def save(self,owner,parsed):
        _owner(owner);id=str(uuid4())
        manifest={k:v for k,v in parsed.items() if k!='rows'}
        manifest.update(id=id,status='validated',row_count=len(parsed['rows']),created_at=datetime.now(UTC).isoformat(),live_verification='unverified',implementation_status='implemented')
        with self.platform._db() as db:db.execute('INSERT INTO options_history VALUES(?,?,?,?)',(id,owner,canonical(manifest),canonical(parsed)))
        return manifest
    def get(self,owner,id):
        _owner(owner)
        with self.platform._db() as db:r=db.execute('SELECT manifest FROM options_history WHERE owner=? AND id=?',(owner,str(id))).fetchone()
        return json.loads(r[0]) if r else None
    def load(self,owner,id):
        _owner(owner)
        with self.platform._db() as db:r=db.execute('SELECT raw FROM options_history WHERE owner=? AND id=?',(owner,str(id))).fetchone()
        return json.loads(r[0]) if r else None
    def list(self,owner,*,limit=50,offset=0):
        _owner(owner)
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=1000000:raise ValueError('Invalid page')
        with self.platform._db() as db:rows=db.execute('SELECT manifest FROM options_history WHERE owner=? ORDER BY rowid DESC LIMIT ? OFFSET ?',(owner,limit,offset)).fetchall()
        return [json.loads(r[0]) for r in rows]
