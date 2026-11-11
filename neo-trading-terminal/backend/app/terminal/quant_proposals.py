"""Server-only candidate templates and selection; never an additional MCP tool."""
from itertools import groupby
from uuid import NAMESPACE_URL, UUID, uuid5
from decimal import Decimal, ROUND_HALF_UP
from .analytics_contracts import StrategyProposal, ProposalLeg


def candidate_proposals(contracts,evidence_id,valued_at):
    if len(contracts)>1000:
        raise ValueError('Candidate universe too large')
    verified = [r for r in contracts if r.get('identity_verified') is True and r.get('option_type') in ('CALL','PUT') and r.get('underlying_key') and r.get('exchange') in ('nse_fo','bse_fo') and r.get('currency')=='INR']
    group_key = lambda r:(r['underlying_key'],r['exchange'],r['currency'],str(r['expiry']),r['option_type'],r['lot_size'])
    verified.sort(key=lambda r:(group_key(r),float(r['strike'])))
    proposals = []
    for _,group in groupby(verified,key=group_key):
        rows = list(group)
        for low,high in zip(rows,rows[1:]):
            if float(low['strike'])>=float(high['strike']):
                continue
            call = low['option_type']=='CALL'
            buy,sell = (low,high) if call else (high,low)
            legs = tuple(ProposalLeg(contract_id=r['contract_id'],underlying_key=r['underlying_key'],exchange=r['exchange'],currency=r['currency'],expiry=r['expiry'],side=side,quantity=r['lot_size'],
                        lot_size=r['lot_size'],strike=r['strike'],option_type=r['option_type']) for r,side in ((buy,'BUY'),(sell,'SELL')))
            template = 'bull_call_spread' if call else 'bear_put_spread'
            identity = f'{evidence_id}:{template}:{buy["contract_id"]}:{sell["contract_id"]}'
            proposals.append(StrategyProposal(proposal_id=uuid5(NAMESPACE_URL,identity),evidence_id=evidence_id,
                                              template=template,valued_at=valued_at,legs=legs))
            if len(proposals)>=20:
                return tuple(proposals)
    return tuple(proposals)


def select_proposal(candidates,proposal_id,evidence_id):
    selected = next((p for p in candidates if p.proposal_id==UUID(str(proposal_id)) and p.evidence_id==UUID(str(evidence_id))),None)
    if selected is None:
        raise ValueError('Proposal not present in captured evidence')
    return selected


def spread_payoff(proposal,quotes,*,roundtrip_cost_paise=None):
    proposal = StrategyProposal.model_validate(proposal.model_dump())
    buy,sell = proposal.legs
    def quote(leg,side):
        row = quotes[leg.contract_id]
        bid,ask = Decimal(str(row['bid'])),Decimal(str(row['ask']))
        if not bid.is_finite() or not ask.is_finite() or bid<0 or ask<bid:
            raise ValueError('Invalid bid-ask quotes')
        return ask if side=='BUY' else bid
    debit = quote(buy,'BUY')-quote(sell,'SELL')
    width = abs(buy.strike-sell.strike)
    if debit<0 or debit>width:
        raise ValueError('Quotes inconsistent with debit spread bounds')
    paise = lambda amount:int((amount*100).quantize(Decimal(1),rounding=ROUND_HALF_UP))
    profit,loss = paise((width-debit)*buy.quantity),paise(debit*buy.quantity)
    breakeven = buy.strike+debit if buy.option_type=='CALL' else buy.strike-debit
    if roundtrip_cost_paise is not None and (type(roundtrip_cost_paise) is not int or roundtrip_cost_paise<0):
        raise ValueError('Verified nonnegative paise costs required')
    return dict(gross_max_profit_paise=profit,gross_max_loss_paise=loss,gross_breakeven=str(breakeven),
                net_max_profit_paise=profit-roundtrip_cost_paise if roundtrip_cost_paise is not None else None,
                net_max_loss_paise=loss+roundtrip_cost_paise if roundtrip_cost_paise is not None else None,
                limitations=['Same-expiry terminal payoff; entry fills estimated at ask/bid. Net figures require a supplied cost scenario.'])
