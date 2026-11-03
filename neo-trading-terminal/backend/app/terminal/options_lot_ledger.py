"""Explicit user-declared complete FIFO ledger; never broker-certified lot proof."""
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Annotated, Literal
from pydantic import AwareDatetime, Field, StrictBool, model_validator
from .options_market_contracts import FrozenContract, MarketDecimal
from .options_strategy_contracts import calculation_context

Identifier=Annotated[str,Field(min_length=1,max_length=160)]

class LotOpeningBalance(FrozenContract):
    contract_id: Identifier
    # A supported ledger begins flat. Nonzero unknown-cost historic lots cannot
    # be silently treated as new positions or ignored in FIFO allocation.
    quantity: Annotated[int,Field(strict=True,ge=0,le=0)]

class LotLedgerTrade(FrozenContract):
    sequence: Annotated[int,Field(strict=True,ge=0)]
    fill_id: Identifier
    contract_id: Identifier
    side: Literal['BUY','SELL']
    quantity: Annotated[int,Field(strict=True,ge=1,le=1000000)]
    price: MarketDecimal
    costs_inr: MarketDecimal
    executed_at: AwareDatetime

class LotLedgerImport(FrozenContract):
    version: Literal['user-lot-ledger.v1']='user-lot-ledger.v1'
    source: Literal['user_declared']='user_declared'
    currency: Literal['INR']='INR'
    allocation_method: Literal['FIFO']='FIFO'
    coverage_start: AwareDatetime
    coverage_end: AwareDatetime
    opening_inventory: Annotated[tuple[LotOpeningBalance,...],Field(min_length=1,max_length=20)]
    trades: Annotated[tuple[LotLedgerTrade,...],Field(max_length=1000)]
    complete: StrictBool=True

    @model_validator(mode='after')
    def validate_history(self):
        ids=[x.contract_id for x in self.opening_inventory]
        if len(set(ids))!=len(ids) or self.coverage_end<self.coverage_start:
            raise ValueError('Unique initial contracts and ordered coverage required')
        if len({x.fill_id for x in self.trades})!=len(self.trades):
            raise ValueError('Duplicate ledger fill ID')
        previous=self.coverage_start
        for i,trade in enumerate(self.trades):
            if trade.sequence!=i or trade.contract_id not in ids or not previous<=trade.executed_at<=self.coverage_end:
                raise ValueError('Complete ordered in-coverage trades required')
            previous=trade.executed_at
        return self


def assess_lot_ledger(report,rows,selected_fill_ids,ledger,*,snapshot_observed_at:datetime):
    """Attribute selected opening lots using declared complete FIFO history.

    Zero opening inventory and every subsequent trade through exactly the server
    observation time are explicit user declarations, not independently verified
    broker history. Net inventory must reconcile with verified server rows.
    """
    unavailable=dict(status='cannot_assess',source='user_declared',execution_confirmed=False,
        current_coverage_verified=False,realized_inr=None,unrealized_inr=None,yield_fraction=None,
        reason='complete compatible declared lot history and snapshot coverage required')
    try:
        ledger=LotLedgerImport.model_validate(ledger.model_dump() if isinstance(ledger,LotLedgerImport) else ledger)
    except ValueError: return unavailable
    ids=[report.request.stock_contract_id,report.request.call_contract_id]+([report.request.put_contract_id] if report.request.put_contract_id else [])
    selected=set(selected_fill_ids)
    by_id={f'{r.exchange}|{r.token}':r for r in rows}
    if (not ledger.complete or ledger.coverage_end!=snapshot_observed_at or len(by_id)!=len(rows)
        or set(by_id)!=set(ids) or {x.contract_id for x in ledger.opening_inventory}!=set(ids)
        or len(selected)!=len(selected_fill_ids) or not selected): return unavailable
    if any(not r.identity_verified or r.currency!='INR' or r.inventory_coverage!='disjoint'
        or not r.inventory_coverage_basis or r.quantity is None or r.last_price is None for r in rows): return unavailable
    trades={t.fill_id:t for t in ledger.trades}
    if not selected<=trades.keys(): return unavailable
    with localcontext(calculation_context()):
        for i,id in enumerate(ids):
            opening=[trades[f] for f in selected if trades[f].contract_id==id]
            if (not opening or any(t.side!=('SELL' if i==1 else 'BUY') for t in opening)
                or sum(t.quantity for t in opening)!=report.quantity): return unavailable
        lots={id:[] for id in ids};realized=Decimal(0);initial_capital=Decimal(0)
        for trade in ledger.trades:
            side=1 if trade.side=='BUY' else -1
            remaining=Decimal(trade.quantity);fee_per_unit=trade.costs_inr/remaining
            is_selected=trade.fill_id in selected
            queue=lots[trade.contract_id]
            if is_selected and queue and queue[0]['side']!=side: return unavailable
            if is_selected: initial_capital+=side*remaining*trade.price+trade.costs_inr
            while remaining and queue and queue[0]['side']!=side:
                lot=queue[0];closed=min(remaining,lot['quantity'])
                if lot['selected']:
                    realized+=closed*(lot['side']*(trade.price-lot['price'])-lot['fee_per_unit']-fee_per_unit)
                remaining-=closed;lot['quantity']-=closed
                if not lot['quantity']: queue.pop(0)
            if remaining:
                queue.append(dict(side=side,quantity=remaining,price=trade.price,
                    fee_per_unit=fee_per_unit,selected=is_selected))
        unrealized=Decimal(0);remaining_selected={id:Decimal(0) for id in ids}
        for id,queue in lots.items():
            if sum((lot['side']*lot['quantity'] for lot in queue),Decimal(0))!=by_id[id].quantity: return unavailable
            for lot in queue:
                if lot['selected']:
                    remaining_selected[id]+=lot['quantity']
                    unrealized+=lot['quantity']*(lot['side']*(by_id[id].last_price-lot['price'])-lot['fee_per_unit'])
        return dict(status='assessed',source='user_declared',proof_version=ledger.version,
            reason='FIFO attribution from user-declared complete flat-start ledger reconciled to server inventory',
            execution_confirmed=True,current_coverage_verified=all(q==report.quantity for q in remaining_selected.values()),
            selected_remaining_quantity={id:str(q) for id,q in remaining_selected.items()},
            realized_inr=str(realized),unrealized_inr=str(unrealized),fill_capital_inr=str(initial_capital),
            yield_fraction=str((realized+unrealized)/initial_capital) if initial_capital>0 else None,
            baseline_capital_deviation_inr=str(initial_capital-report.current_capital) if report.current_capital is not None else None,
            limitations=['User declares complete trade coverage and zero opening inventory; not broker-verified lot allocation.',
                          'Unrealized P&L uses snapshot marks and known incurred costs, excluding future closing costs.'])
