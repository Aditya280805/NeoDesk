"""Strict adapter for the explicitly dated official NSE ban publication."""
import csv
import io
import re
from datetime import date

SOURCE_URL = 'https://nsearchives.nseindia.com/content/fo/fo_secban.csv'
MONTHS = {name:index for index,name in enumerate(
    ('JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'),1)}


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
