"""Local capability report by default; live checks require explicit --mode."""
import argparse
import asyncio
from datetime import UTC, date, datetime
import json

from app.terminal.options_market_contracts import (
    CapabilityField, DataCapabilities, MarketContract, MarketQuote, StrategyMarketEvidence,
)

DOCS = 'https://github.com/Kotak-Neo/kotak-neo-python'


def get_data_capabilities() -> DataCapabilities:
    """Static reviewed adapter inventory; no imports of SDK/config or network calls."""
    inventory = (
        ('holdings', 'supported', 'PortfolioService holdings; normalized section evidence', 'supported'),
        ('positions', 'supported', 'PortfolioService positions; non-atomic provider observations', 'supported'),
        ('orders', 'supported', 'PortfolioService order_report; read only', 'supported'),
        ('fills', 'missing', 'SDK trade_report exists; no canonical fill adapter', 'supported'),
        ('contract_identity', 'unverified', 'Legacy chain symbol is not verified instrument/underlying token', 'supported'),
        ('lot_size_expiry', 'unverified', 'Chain common mktLot/expiry not per-contract catalogue verification', 'supported'),
        ('last_volume_open_interest', 'supported', 'options_snapshot normalize_snapshot fixture-backed chain fields', 'supported'),
        ('bid_ask_depth', 'supported', 'quotes_to_evidence documented quotes.depth mapping; absent on legacy chain', 'supported'),
        ('exchange_timestamp', 'missing', 'Snapshot retrieval time only; exchange timestamp null', 'unverified'),
        ('iv', 'missing', 'No verified chain IV mapping', 'unverified'),
        ('margin', 'unverified', 'Limits available; used/total margin basis not established', 'supported'),
        ('account_pnl', 'unverified', 'Provider MTM not verified account net P&L period/basis', 'supported'),
        ('historical_options', 'unverified', 'Historical candle method exists; historical options coverage unproven', 'unverified'),
        ('settlement', 'unverified', 'No per-contract versioned physical settlement rule mapping', 'unverified'),
    )
    return DataCapabilities(adapter='terminal Market/PortfolioService/normalize_snapshot', adapter_version='reviewed with installed kotakneoapi 3.0.7; no SDK migration', fields=tuple(
        CapabilityField(name=name, status=status, source_reference=DOCS, checked_date=date(2026,11,1), adapter_evidence=evidence, official_docs_status=official)
        for name,status,evidence,official in inventory))


def legacy_chain_to_evidence(snapshot: dict, *, catalogue=()) -> StrategyMarketEvidence:
    """Adapt normalized legacy snapshots without guessing symbol identity or lot metadata.

    Evidence-local IDs are explicitly not broker instrument tokens. Expiry must parse
    as a date; unspecified provider-selected expiry cannot form an option contract.
    """
    from app.terminal.options_snapshot import expiry_identity
    from uuid import UUID
    snapshot_id = UUID(snapshot['snapshot_id'])
    if snapshot.get('exchange') != 'nse_fo':
        raise ValueError('Canonical strategy scope is NSE only')
    observed_at = snapshot['retrieved_at']
    limitations = ['Legacy row IDs are evidence-local, not verified broker tokens.',
                  'Underlying identity, lot size and settlement are unverified; unavailable values remain null.',
                  'LTP/OI are indicative only; executable bid/ask and exchange timestamps unavailable.']
    try:
        expiry = date.fromisoformat(expiry_identity(snapshot['expiry']))
    except (ValueError, KeyError):
        return StrategyMarketEvidence(evidence_id=snapshot_id, observed_at=observed_at, source='kotak-legacy-chain', completeness='unavailable', limitations=tuple(limitations+['Expiry cannot be resolved; no canonical option rows emitted.']))
    rows = snapshot['rows']
    if not isinstance(rows, list) or len(rows)>200:
        raise ValueError('Unexpected legacy chain size')
    if len(catalogue)>5000:
        raise ValueError('Catalogue input too large')
    contracts, quotes = [], []
    for index,row in enumerate(rows):
        identifier=f'legacy-row:{snapshot_id}:{index}'
        # A full metadata tuple can resolve an option token, but cannot establish
        # the cash underlying ID from a symbol. Defaulted master lot metadata
        # remains unverified, even where an exact option catalogue match exists.
        matches=[item for item in catalogue if item.get('exchange')=='nse_fo' and item.get('kind')=='OPTION'
                 and item.get('symbol')==row['symbol'] and expiry_identity(item.get('expiry',''))==expiry.isoformat()
                 and str(item.get('option_type','')).upper()==('CE' if row['side']=='CALL' else 'PE')
                 and str(item.get('strike'))==str(row['strike'])]
        if len(matches)>1:
            raise ValueError('Ambiguous catalogue contract match')
        lot=None
        if matches:
            match=matches[0]
            if not match.get('token') or match.get('id') != 'nse_fo|'+str(match['token']):
                raise ValueError('Contradictory catalogue token')
            identifier=match['id']
            # Catalogue parser may supply a default lot. There is no raw-field
            # provenance here, so publishing it would turn absence into data.
            lot=None
            metadata=match.get('source_metadata',{})
            raw_lot=metadata.get('lLotSize','')
            if metadata.get('source')=='kotak-scrip-master' and isinstance(raw_lot,str) and raw_lot.isascii() and raw_lot.isdecimal() and len(raw_lot)<=7:
                candidate=int(raw_lot)
                if 0<candidate<=1000000:
                    lot=candidate
        contracts.append(MarketContract(instrument_id=identifier,kind={'CALL':'call','PUT':'put'}[row['side']],expiry=expiry,strike=row['strike'],lot_size=lot,basis='exact option metadata catalogue match; underlying unverified' if matches else 'unverified legacy chain row',provenance=('normalize_snapshot','local catalogue; lot may be parser default') if matches else ('normalize_snapshot',)))
        quotes.append(MarketQuote(contract_id=identifier,observed_at=observed_at,last=row['ltp'],volume=row.get('volume'),open_interest=row.get('open_interest'),source='kotak-legacy-chain',provenance=('normalize_snapshot:quote.ltp,volume,openInterest',)))
    return StrategyMarketEvidence(evidence_id=snapshot_id, observed_at=observed_at,contracts=tuple(contracts),quotes=tuple(quotes),source='kotak-legacy-chain',completeness='partial' if contracts else 'unavailable',limitations=tuple(limitations))


def quotes_to_evidence(rows: list, contracts: tuple[MarketContract, ...], observed_at: datetime) -> StrategyMarketEvidence:
    """Map documented kotakneoapi 3.x all-quotes fields by exact segment/token.

    lstup_time is not mapped: last-update semantics are not exchange-time proof.
    Depth prices with zero quantity remain reported values, never an execution guarantee.
    """
    if not isinstance(rows,list) or len(rows)>50 or len(contracts)>50:
        raise ValueError('Quote batch exceeds documented 50 instrument limit')
    expected={item.instrument_id:item for item in contracts}
    if len(expected)!=len(contracts):
        raise ValueError('Duplicate contract')
    quotes=[]
    for row in rows:
        segment=row['exchange']
        if segment not in ('nse_fo','nse_cm'):
            raise ValueError('Unexpected quote exchange')
        token=str(row['exchange_token'])
        identifier=segment+'|'+token
        # Bare IDs are allowed only when explicitly supplied by caller.
        if identifier not in expected and token in expected:
            identifier=token
        if identifier not in expected:
            raise ValueError('Quote token not requested')
        contract=expected[identifier]
        if segment != ('nse_cm' if contract.kind=='equity' else 'nse_fo'):
            raise ValueError('Quote segment contradicts contract')
        values={}
        depth=row.get('depth')
        if depth is not None:
            if not isinstance(depth,dict):
                raise ValueError('Malformed depth')
            for side,price,quantity in (('buy','bid','bid_quantity'),('sell','ask','ask_quantity')):
                levels=depth.get(side,[])
                if not isinstance(levels,list) or len(levels)>5:
                    raise ValueError('Malformed depth levels')
                if levels:
                    # Validate every level before selecting best price, avoiding
                    # dependence on undocumented provider ordering.
                    checked=[MarketQuote(contract_id=identifier,observed_at=observed_at,last=level.get('price'),volume=level.get('quantity'),source='kotak-quotes',provenance=('quotes.depth',)) for level in levels]
                    checked=[level for level in checked if level.last is not None]
                    if checked:
                        best=(max if side=='buy' else min)(checked,key=lambda level:level.last)
                        values[price],values[quantity]=best.last,best.volume
        quotes.append(MarketQuote(contract_id=identifier,observed_at=observed_at,last=row.get('ltp'),volume=row.get('last_volume'),open_interest=row.get('open_int'),source='kotak-quotes',provenance=('kotakneoapi 3.0.7 quotes all; documented depth buy/sell price/quantity',),**values))
    return StrategyMarketEvidence(observed_at=observed_at,contracts=contracts,quotes=tuple(quotes),source='kotak-quotes',completeness='partial',limitations=('Quote retrieval time is not verified exchange time.', 'Identity/settlement flags retain caller evidence; depth is not a fill guarantee.'))


def fetch_strategy_market_evidence(market, store, user_id: int, context, deadline: float | None = None) -> StrategyMarketEvidence:
    """Explicit worker-thread acquisition; bounded chain and one 50-token quote batch.

    Market.call enforces signed-in session isolation and request deadlines. This
    helper never runs from CLI local mode and never changes broker credentials.
    """
    from app.terminal.options_snapshot import normalize_snapshot
    generation=market.session_generation(user_id)
    def require_generation():
        if market.session_generation(user_id)!=generation:
            raise ValueError('Broker session changed during market evidence acquisition')
    raw=market.call('option_chain',user_id=user_id,exchange=context.exchange,underlying=context.underlying,
                    expiry=context.expiry,instrument_type='option',count=20,deadline_monotonic=deadline)
    require_generation()
    snapshot=normalize_snapshot(raw,context)
    catalogue=store.search(query=context.underlying,exchange='nse_fo',kind='OPTION',limit=5000)['items']
    evidence=legacy_chain_to_evidence(snapshot,catalogue=catalogue)
    matched=tuple(contract for contract in evidence.contracts if contract.instrument_id.startswith('nse_fo|'))
    if not matched or len(matched)>50:
        require_generation()
        return evidence
    require_generation()
    rows=market.call('quotes',user_id=user_id,instrument_tokens=[{'exchange_segment':'nse_fo','instrument_token':item.instrument_id.split('|',1)[1]} for item in matched],quote_type='all',deadline_monotonic=deadline)
    enriched=quotes_to_evidence(rows,matched,datetime.now(UTC))
    by_id={quote.contract_id:quote for quote in enriched.quotes}
    require_generation()
    return evidence.model_copy(update={'quotes':tuple(by_id.get(quote.contract_id,quote) for quote in evidence.quotes),
                                       'limitations':evidence.limitations+enriched.limitations})


async def _delegate_live(mode: str, base_url: str):
    from app.terminal.options_evals import broker_smoke, replay
    return await (broker_smoke(base_url) if mode=='live-broker' else replay('live-model'))


def run_live_check(mode: str, base_url: str) -> dict:
    if mode not in ('live-broker','live-model'):
        raise ValueError('Explicit live mode required')
    try:
        report=asyncio.run(_delegate_live(mode,base_url))
        passed=report.get('passed')==report.get('total') and bool(report.get('total'))
        return {'mode':mode,'status':'passed' if passed else 'failed','details':'Existing safe smoke/evaluation checks completed.'}
    except Exception:
        return {'mode':mode,'status':'unavailable','details':'Check provider configuration, access/quota, authentication and connectivity; details suppressed.'}


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('local','live-broker','live-model'),default='local')
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    args=parser.parse_args(argv)
    report=get_data_capabilities().model_dump(mode='json') if args.mode=='local' else run_live_check(args.mode,args.base_url)
    print(json.dumps(report,sort_keys=True))
    return 0 if report.get('status','passed')=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
