"""Strict adapter for the explicitly dated official NSE ban publication."""
import csv
import io
import re
import hashlib
import time
import json
from datetime import UTC, date, datetime
from contextlib import nullcontext

import httpx

SOURCE_URL = 'https://nsearchives.nseindia.com/content/fo/fo_secban.csv'
MONTHS = {name:index for index,name in enumerate(
    ('JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'),1)}


class BanReports:
    """Separate official namespace; bounded reuse with immutable revisions."""
    def __init__(self,store):
        self.store = store

    def fetch(self,trade_date,*,deadline):
        def check():
            if time.monotonic() >= deadline:
                raise TimeoutError('Ban publication acquisition deadline exhausted')
        check()
        with self.store.connect() as db:
            row = db.execute('SELECT payload FROM analytics_source_revisions WHERE source=? AND report_date=? ORDER BY retrieved_at DESC LIMIT 1',
                ('nse-ban-official',trade_date.isoformat())).fetchone()
        check()
        if row:
            cached = json.loads(row[0])
            age = (datetime.now(UTC)-datetime.fromisoformat(cached['retrieved_at'])).total_seconds()
            if 0 <= age < 300 and cached.get('trade_date') == trade_date.isoformat() and cached.get('source') == SOURCE_URL and cached.get('provenance') == 'official_https_fetch':
                return cached
        result = fetch_ban_publication(trade_date,deadline=deadline)
        check()
        with self.store.connect() as db:
            db.execute('INSERT INTO analytics_source_revisions VALUES (?,?,?,?,?) ON CONFLICT(source,report_date,checksum) DO UPDATE SET retrieved_at=excluded.retrieved_at,payload=excluded.payload',
                ('nse-ban-official',trade_date.isoformat(),result['checksum'],result['retrieved_at'],json.dumps(result,allow_nan=False)))
        check()
        return result


def fetch_ban_publication(expected_trade_date: date, *, deadline: float, client=None) -> dict:
    """Read only the fixed official URL; never follow a redirect or retry."""
    def remaining():
        value = deadline-time.monotonic()
        if value <= 0:
            raise TimeoutError('Ban publication acquisition deadline exhausted')
        return min(value,5)
    timeout = remaining()
    with (httpx.Client(follow_redirects=False) if client is None else nullcontext(client)) as source:
        with source.stream('GET',SOURCE_URL,timeout=timeout,follow_redirects=False) as response:
            response.raise_for_status()
            chunks, size = [],0
            for chunk in response.iter_bytes():
                remaining()
                size += len(chunk)
                if size > 65536:
                    raise ValueError('Ban publication exceeds size limit')
                chunks.append(chunk)
    remaining()
    body = b''.join(chunks).decode('utf-8-sig')
    result = parse_ban_publication(body,expected_trade_date)
    result.update(checksum=hashlib.sha256(body.encode('utf-8')).hexdigest(),
        retrieved_at=datetime.now(UTC).isoformat(),provenance='official_https_fetch')
    return result


def parse_ban_publication(body: str, expected_trade_date: date) -> dict:
    if not isinstance(body,str) or len(body.encode('utf-8')) > 65536:
        raise ValueError('Invalid bounded ban publication')
    lines = body.lstrip('\ufeff').splitlines()
    match = re.fullmatch(r'Securities in Ban For Trade Date (\d{2})-([A-Z]{3})-(\d{4}):',lines[0] if lines else '')
    if not match or match[2] not in MONTHS:
        raise ValueError('Missing explicit publication trade date')
    trade_date = date(int(match[3]),MONTHS[match[2]],int(match[1]))
    if trade_date != expected_trade_date:
        raise ValueError('Publication trade date does not match requested date')
    symbols = []
    for row in csv.reader(io.StringIO('\n'.join(lines[1:])),strict=True):
        if not row:
            continue
        if len(row) != 2 or row[0] != str(len(symbols)+1) or not re.fullmatch(r'[A-Z0-9&_.-]{1,40}',row[1]) or row[1] in symbols:
            raise ValueError('Invalid ban publication record')
        symbols.append(row[1])
    # Empty-day wording is not established by the observed official fixture.
    if not symbols:
        raise ValueError('Unverified empty publication format')
    return dict(trade_date=trade_date.isoformat(),symbols=symbols,source=SOURCE_URL,
        scope='published_stock_derivative_ban_list',complete_account_coverage=False)
