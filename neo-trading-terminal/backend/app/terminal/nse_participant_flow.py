"""Bounded official-report parser. Aggregate OI is counts, never delta exposure."""
import csv
import hashlib
import io


def parse_participant_csv(text):
    if len(text.encode('utf-8')) > 1048576:
        raise ValueError('Participant report too large')
    lines = text.lstrip('\ufeff').splitlines()
    start = next((i for i,line in enumerate(lines[:10]) if line.lower().startswith('client type,')),None)
    if start is None:
        raise ValueError('Missing participant header')
    rows = csv.DictReader(io.StringIO('\n'.join(lines[start:])),skipinitialspace=True)
    expected = ('Future Index Long','Future Index Short','Option Index Call Long','Option Index Call Short','Option Index Put Long','Option Index Put Short')
    if not set(expected).issubset(rows.fieldnames or []):
        raise ValueError('Missing participant columns')
    participants = {}
    for i,row in enumerate(rows):
        if i > 20:
            raise ValueError('Unexpected participant rows')
        name = row['Client Type'].strip()
        if name not in ('FII','DII','Pro','Client'):
            continue
        if name in participants:
            raise ValueError('Duplicate participant')
        values = [int(row[k].strip()) for k in expected]
        if any(v < 0 for v in values):
            raise ValueError('Negative participant OI')
        fl,fs,cl,cs,pl,ps = values
        participants[name] = dict(index_futures_long_share=fl/(fl+fs) if fl+fs else None,
                                  net_index_futures=fl-fs,net_index_calls=cl-cs,net_index_puts=pl-ps)
    if set(participants) != {'FII','DII','Pro','Client'}:
        raise ValueError('Incomplete participant categories')
    return dict(participants=participants,unit='contracts',checksum=hashlib.sha256(text.encode()).hexdigest(),
                limitations=['End-of-day positioning, not intraday flows or measured delta.'],
                five_day_change=None,divergence_flag=None)
