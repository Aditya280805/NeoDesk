"""Allowlisted bounded official-report acquisition and reproducible revisions."""
import json
import re
from datetime import UTC, date, datetime
import httpx

from .nse_participant_flow import parse_participant_csv


class ParticipantReports:
    def __init__(self,store):
        self.store = store

    def import_report(self,report_date,text):
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
        with self.store.connect() as db:
            db.execute('INSERT OR IGNORE INTO analytics_source_revisions VALUES (?,?,?,?,?)',
                       ('nse-participant-oi',report_date.isoformat(),result['checksum'],result['retrieved_at'],json.dumps(result,allow_nan=False)))
        return result

    def cached(self,report_date,checksum=None):
        sql = 'SELECT payload FROM analytics_source_revisions WHERE source=? AND report_date=?'
        args = ['nse-participant-oi',report_date.isoformat()]
        if checksum:
            sql += ' AND checksum=?'
            args.append(checksum)
        sql += ' ORDER BY retrieved_at DESC LIMIT 1'
        with self.store.connect() as db:
            row = db.execute(sql,args).fetchone()
        return json.loads(row[0]) if row else None

    def fetch(self,report_date):
        if not isinstance(report_date,date) or report_date>datetime.now(UTC).date():
            raise ValueError('Invalid published report date')
        cached = self.cached(report_date)
        if cached:
            return cached
        url = f'https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{report_date:%d%m%Y}.csv'
        with httpx.Client(timeout=5,follow_redirects=False) as client:
            with client.stream('GET',url) as response:
                response.raise_for_status()
                chunks, size = [],0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size>1048576:
                        raise ValueError('Participant report too large')
                    chunks.append(chunk)
        return self.import_report(report_date,b''.join(chunks).decode('utf-8-sig'))
