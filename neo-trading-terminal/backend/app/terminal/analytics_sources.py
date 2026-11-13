"""Allowlisted bounded official-report acquisition and reproducible revisions."""
import json
import re
import time
from datetime import UTC, date, datetime
import httpx

from .nse_participant_flow import parse_participant_csv


class ParticipantReports:
    def __init__(self,store):
        self.store = store

    @staticmethod
    def parse_report(report_date,text):
        match = re.search(r'\b(\d{1,2}[-/][A-Za-z]{3}[-/]\d{4}|\d{1,2}/\d{1,2}/\d{4})\b',text[:1000])
        if match is None:
            raise ValueError('Participant report observation date required')
        parsed = None
        for fmt in ('%d-%b-%Y','%d/%b/%Y','%d/%m/%Y'):
            try:
                parsed = datetime.strptime(match.group(),fmt).date()
                break
            except ValueError:
                pass
        if parsed != report_date:
            raise ValueError('Report date does not match requested observation date')
        result = parse_participant_csv(text)
        result.update(report_date=report_date.isoformat(),retrieved_at=datetime.now(UTC).isoformat(),
                      source='nse-participant-oi',provenance='validated-import')
        return result

    def import_report(self,report_date,text,*,_official_fetch=False):
        result = self.parse_report(report_date,text)
        if _official_fetch:
            result['provenance']='official_https_fetch'
        with self.store.connect() as db:
            db.execute('INSERT OR IGNORE INTO analytics_source_revisions VALUES (?,?,?,?,?)',
                       ('nse-participant-oi-official' if _official_fetch else 'nse-participant-oi',report_date.isoformat(),result['checksum'],result['retrieved_at'],json.dumps(result,allow_nan=False)))
        return result

    def cached(self,report_date,checksum=None,*,_official=False):
        sql = 'SELECT payload FROM analytics_source_revisions WHERE source=? AND report_date=?'
        args = ['nse-participant-oi-official' if _official else 'nse-participant-oi',report_date.isoformat()]
        if checksum:
            sql += ' AND checksum=?'
            args.append(checksum)
        sql += ' ORDER BY retrieved_at DESC LIMIT 1'
        with self.store.connect() as db:
            row = db.execute(sql,args).fetchone()
        return json.loads(row[0]) if row else None

    def fetch(self,report_date,*,deadline=None):
        if not isinstance(report_date,date) or report_date>datetime.now(UTC).date():
            raise ValueError('Invalid published report date')
        cached = self.cached(report_date,_official=True)
        if cached and cached.get('provenance')=='official_https_fetch':
            return cached
        url = f'https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{report_date:%d%m%Y}.csv'
        with httpx.Client(timeout=5,follow_redirects=False) as client:
            with client.stream('GET',url) as response:
                response.raise_for_status()
                chunks, size = [],0
                for chunk in response.iter_bytes():
                    if deadline is not None and time.monotonic()>=deadline:
                        raise TimeoutError('Participant acquisition deadline exhausted')
                    size += len(chunk)
                    if size>1048576:
                        raise ValueError('Participant report too large')
                    chunks.append(chunk)
        return self.import_report(report_date,b''.join(chunks).decode('utf-8-sig'),_official_fetch=True)
