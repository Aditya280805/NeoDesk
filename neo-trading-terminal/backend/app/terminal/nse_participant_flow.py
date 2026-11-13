"""Bounded official-report parser. Aggregate OI is counts, never delta exposure."""
import csv
import hashlib
import io
import math


def parse_participant_csv(text):
    if len(text.encode('utf-8')) > 1048576:
        raise ValueError('Participant report too large')
    lines = text.lstrip('\ufeff').splitlines()
    start = next((i for i,line in enumerate(lines[:10]) if line.lower().startswith('client type,')),None)
    if start is None:
        raise ValueError('Missing participant header')
    rows = csv.DictReader(io.StringIO('\n'.join(lines[start:])),skipinitialspace=True)
    expected = ('Future Index Long','Future Index Short','Option Index Call Long','Option Index Call Short','Option Index Put Long','Option Index Put Short')
    if len(rows.fieldnames or [])!=len(set(rows.fieldnames or [])):
        raise ValueError('Duplicate participant columns')
    if not set(expected).issubset(rows.fieldnames or []):
        raise ValueError('Missing participant columns')
    participants = {}
    raw_counts = {}
    for i,row in enumerate(rows):
        if i > 20:
            raise ValueError('Unexpected participant rows')
        name = row['Client Type'].strip()
        if name not in ('FII','DII','Pro','Client'):
            continue
        if name in participants:
            raise ValueError('Duplicate participant')
        values = [int(row[k].strip()) for k in expected]
        if any(not 0<=v<=1000000000000 for v in values):
            raise ValueError('Participant OI outside bounded contract-count range')
        fl,fs,cl,cs,pl,ps = values
        raw_counts[name] = dict(call_long=cl,call_short=cs,put_long=pl,put_short=ps)
        participants[name] = dict(index_futures_long_share=fl/(fl+fs) if fl+fs else None,
                                  net_index_futures=fl-fs,net_index_calls=cl-cs,net_index_puts=pl-ps)
    if set(participants) != {'FII','DII','Pro','Client'}:
        raise ValueError('Incomplete participant categories')
    fii,pro,client = (raw_counts[name] for name in ('FII','Pro','Client'))
    cl,cs,pl,ps = (fii[key]+pro[key] for key in ('call_long','call_short','put_long','put_short'))
    divergence = None
    if cl+cs and pl+ps and client['call_long']+client['call_short']:
        call_share,put_share,client_call_share = cl/(cl+cs),pl/(pl+ps),client['call_long']/(client['call_long']+client['call_short'])
        divergence = 'BEARISH_INSTITUTIONAL_DIVERGENCE' if call_share<.3 and put_share>.7 and client_call_share>.7 else 'BULLISH_INSTITUTIONAL_ACCUMULATION' if call_share>.7 and put_share<.3 and client_call_share<.3 else 'NONE'
    return dict(participants=participants,unit='contracts',checksum=hashlib.sha256(text.encode()).hexdigest(),
                limitations=['End-of-day positioning, not intraday flows or measured delta.'],
                institutional_retail_divergence_flag=divergence,positioning_heuristic='combined_FII_Pro_call_put_directional_share_gt70pct_and_opposite_Client_call_share_gt70pct.v1',
                five_day_change=None,divergence_flag=None)


def participant_history_change(current,history,*,sessions_complete,price_return=None):
    if history and history[-1]['checksum']!=current['checksum']:
        raise ValueError('Participant history contradicts selected current report')
    if not sessions_complete or len(history)!=6:
        return dict(five_day_change=None,divergence_flag=None,history_reason='six_complete_source_declared_sessions_required')
    dates = [report['report_date'] for report in history]
    if any(a>=b for a,b in zip(dates,dates[1:])):
        raise ValueError('Participant sessions must be ordered and distinct')
    first,last = history[0]['participants'],history[-1]['participants']
    keys = ('net_index_futures','net_index_calls','net_index_puts')
    changes = {name:{key:last[name][key]-first[name][key] for key in keys} for name in first}
    flags = None
    if price_return is not None:
        if not math.isfinite(price_return):
            raise ValueError('Finite price return required')
        flags = {name:price_return*changes[name]['net_index_futures']<0 for name in ('FII','DII')}
    result = dict(five_day_change=changes,divergence_flag=flags,history_dates=dates,
        divergence_basis='directional_price_vs_net_index_futures_contract_count_change_heuristic',
        history_completeness='user_declared_six_ordered_sessions')
    if flags is None:
        result['history_reason']='aligned_price_return_unavailable'
    return result
