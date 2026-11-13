"""Pure conservative portfolio evidence normalization."""
from datetime import date
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_HALF_UP, localcontext
import math
from .portfolio_contracts import PortfolioIssue, PortfolioRow, PortfolioSection, PortfolioSnapshot, SectionObservation, ValueProvenance, parse_decimal
FORMULA='portfolio.v1.decimal.1'
EXCHANGES={'nse_cm','bse_cm','nse_fo','bse_fo','cde_fo','mcx_fo'}
def cash_expiry_missing(value,holding,exchange):
    return holding and exchange in ('nse_cm','bse_cm') and str(value).strip().upper() in ('','NA','N/A','-','0','-1')
def text(v):
    return str(v) if isinstance(v,(str,int)) and not isinstance(v,bool) else None
def alias(raw,*keys):
    return next(((k,raw[k]) for k in keys if raw.get(k) is not None),(keys[0],None))
def resolve_portfolio_instrument(raw,catalogue,*,holding):
    ex=text(alias(raw,'exchangeSegment' if holding else 'exSeg','exchange')[1]); tok=text(alias(raw,'exchangeIdentifier' if holding else 'tok','token')[1]); sym=text(alias(raw,'displaySymbol' if holding else 'trdSym','symbol')[1])
    result=dict(exchange=ex,token=tok,symbol=sym,identity_status='unresolved',identity_verified=False,identity_basis='provider_fields',currency='INR' if raw.get('currency')=='INR' or raw.get('currency') is None and ex in EXCHANGES else None)
    # Contradictory provider aliases invalidate identity even before catalogue lookup.
    for keys in [('exchangeSegment','exSeg','exchange'),('exchangeIdentifier','tok','token'),('displaySymbol','trdSym','symbol')]:
        supplied={str(raw[k]) for k in keys if raw.get(k) is not None}
        if keys[0]=='displaySymbol' and holding and ex=='nse_cm':
            supplied={value[:-3] if value.endswith('-EQ') else value for value in supplied}
        if len(supplied)>1: result['identity_status']='invalid'
    for keys in [('expiry','expiryDate','expDt'),('strike','strikePrice','stkPrc'),('option_type','optionType','optTp'),('contract_type','kind'),('lot_size','lotSize')]:
        supplied=[]
        for key in keys:
            if raw.get(key) is None: continue
            if keys[0]=='expiry' and cash_expiry_missing(raw[key],holding,ex): continue
            try: value=parse_decimal(raw[key]) if keys[0] in ('strike','lot_size') else str(raw[key]).upper()
            except ValueError: result['identity_status']='invalid'; continue
            supplied.append(value)
        if any(v != supplied[0] for v in supplied[1:]): result['identity_status']='invalid'
    alias_conflict=result['identity_status']=='invalid'
    def token(c): return str(c.get('token',str(c.get('id','')).split('|')[-1]))
    candidates=[c for c in catalogue if (not ex or c.get('exchange')==ex) and ((tok and token(c)==tok) or (not tok and sym and c.get('symbol') in (sym,sym+'-EQ')))]
    if not candidates and tok and any(token(c)==tok for c in catalogue): result['identity_status']='invalid'
    if len(candidates)>1: result['identity_status']='ambiguous'
    elif len(candidates)==1:
        c=candidates[0]; conflict=alias_conflict or bool(sym and c.get('symbol') not in (sym,sym+'-EQ'))
        for keys,target in [(('expiry','expiryDate','expDt'),'expiry'),(('strike','strikePrice','stkPrc'),'strike'),(('option_type','optionType','optTp'),'option_type'),(('contract_type','kind'),'kind'),(('lot_size','lotSize'),'lot_size')]:
            _,v=alias(raw,*keys)
            if target=='expiry' and cash_expiry_missing(v,holding,ex): continue
            if target == 'lot_size':
                try: concrete=parse_decimal(c.get(target))
                except ValueError: concrete=None
                if concrete is None or concrete <= 1: continue
            if v is not None and c.get(target) is not None:
                try: same=parse_decimal(v)==parse_decimal(c[target]) if target in ('strike','lot_size') else str(v).upper()==str(c[target]).upper()
                except ValueError: same=False
                conflict |= not same
        if conflict: result['identity_status']='invalid'
        else: result.update(identity_basis='catalogue_match',instrument_id=c.get('id'),exchange=ex or text(c.get('exchange')),token=tok or text(token(c)))
    if alias_conflict: result.update(identity_status='invalid',identity_basis='provider_fields'); result.pop('instrument_id',None)
    return result

def row(raw,name,index,catalogue):
    rid=f'{name}:{index}'
    if not isinstance(raw,dict): return PortfolioRow(row_id=rid,issues=[PortfolioIssue(code='invalid_row',row_id=rid)])
    identity=resolve_portfolio_instrument(raw,catalogue,holding=name=='holdings')
    r=PortfolioRow(row_id=rid,**{k:v for k,v in identity.items() if k!='instrument_id'})
    def issue(code,field=None): r.issues.append(PortfolioIssue(code=code,row_id=rid,field=field))
    if r.identity_status in ('invalid','ambiguous'): issue('identity_conflict' if r.identity_status=='invalid' else 'identity_ambiguous')
    def read(*keys,signed=False,required=False):
        key,value=alias(raw,*keys)
        try: value=parse_decimal(value,allow_negative=signed)
        except ValueError: issue('invalid_number',keys[0]); value=None
        if value is None and required: issue('missing_value',keys[0])
        return key,value
    def num(field,*keys,signed=False,required=False):
        key,v=read(*keys,signed=signed,required=required); setattr(r,field,v)
        if v is not None: r.provenance[field]=ValueProvenance(source='provider',input_paths=[key],basis='provider_reported')
        return v
    def calc(field,v,paths,basis,money=True):
        try:
            with localcontext() as ctx:
                ctx.prec=64
                v=v()
                if money: v=v.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
            setattr(r,field,v); r.provenance[field]=ValueProvenance(source='calculated',input_paths=paths,formula_version=FORMULA,basis=basis)
        except (DecimalException,OverflowError): issue('calculation_overflow',field)
    num('quantity','quantity' if name=='holdings' else 'netQty' if name=='positions' else 'qty',signed=name=='positions',required=name!='positions')
    num('average_price','averagePrice' if name=='holdings' else 'avgPrc'); num('last_price','ltp')
    if r.currency is None: issue('unknown_currency','currency')
    r.contract_type=text(alias(raw,'contract_type','kind')[1])
    _,expiry=alias(raw,'expiry','expiryDate','expDt')
    if cash_expiry_missing(expiry,name=='holdings',r.exchange): expiry=None
    if expiry is not None:
        try: r.expiry=date.fromisoformat(str(expiry))
        except ValueError: issue('identity_conflict','expiry'); r.identity_status='invalid'
    num('strike','strike','strikePrice','stkPrc'); num('lot_size','lot_size','lotSize')
    arithmetic=r.currency=='INR' and r.identity_status not in ('invalid','ambiguous')
    if name=='holdings':
        num('available_quantity','sellableQuantity'); num('invested_value','holdingCost'); num('market_value','mktValue')
        if arithmetic and r.quantity is not None:
            if r.invested_value is None and r.average_price is not None: calc('invested_value',lambda: r.quantity*r.average_price,['quantity','averagePrice'],'holdings_cost')
            if r.market_value is None and r.last_price is not None: calc('market_value',lambda: r.quantity*r.last_price,['quantity','ltp'],'holdings_mark_to_market')
        if arithmetic and r.market_value is not None and r.invested_value is not None: calc('calculated_pnl',lambda: r.market_value-r.invested_value,['mktValue|quantity*ltp','holdingCost|quantity*averagePrice'],'holdings_unrealized')
    elif name=='positions':
        b=[read(k)[1] for k in ('cfBuyQty','flBuyQty')]; s=[read(k)[1] for k in ('cfSellQty','flSellQty')]
        if all(v is not None for v in b): calc('buy_quantity',lambda: sum(b),['cfBuyQty','flBuyQty'],'buy_units',False)
        if all(v is not None for v in s): calc('sell_quantity',lambda: sum(s),['cfSellQty','flSellQty'],'sell_units',False)
        if r.quantity is None:
            if r.buy_quantity is not None and r.sell_quantity is not None: calc('quantity',lambda: r.buy_quantity-r.sell_quantity,['cfBuyQty','flBuyQty','cfSellQty','flSellQty'],'net_units',False)
            else: issue('missing_value','quantity')
        num('provider_pnl','mtm',signed=True)
        if r.provider_pnl is not None: r.provenance['provider_pnl'].basis='provider_mtm_unspecified_period'
        scale=[read(k)[1] for k in ('multiplier','genNum','genDen','prcNum','prcDen')]
        if any(v is None for v in scale): issue('missing_multiplier','multiplier')
        elif scale[2]==0 or scale[4]==0: issue('invalid_denominator','multiplier')
        elif any(v==0 for v in scale): issue('missing_multiplier','multiplier')
        else: calc('multiplier',lambda: scale[0]*scale[1]/scale[2]*scale[3]/scale[4],['multiplier','genNum','genDen','prcNum','prcDen'],'price_quantity_scale',False)
        amounts=[read(k)[1] for k in ('cfBuyAmt','buyAmt','cfSellAmt','sellAmt')]
        if arithmetic and all(v is not None for v in amounts) and r.quantity is not None and r.last_price is not None and r.multiplier is not None: calc('calculated_pnl',lambda: amounts[2]+amounts[3]-amounts[0]-amounts[1]+r.quantity*r.last_price*r.multiplier,['cfBuyAmt','buyAmt','cfSellAmt','sellAmt','netQty','ltp','multiplier','genNum','genDen','prcNum','prcDen'],'position_cash_flow_plus_open_market_value')
        elif r.provider_pnl is None: issue('unknown_basis','calculated_pnl')
        r.product=text(raw.get('prod'))
    else:
        side=raw.get('trnsTp')
        r.side={'B':'BUY','S':'SELL','BUY':'BUY','SELL':'SELL'}.get(side,'UNKNOWN') if isinstance(side,str) else 'UNKNOWN'
        if r.side=='UNKNOWN': issue('unknown_side','side')
        r.status={'open':'OPEN','pending':'PENDING','trigger pending':'TRIGGER_PENDING','complete':'FILLED','cancelled':'CANCELLED','canceled':'CANCELLED','rejected':'REJECTED'}.get(str(raw.get('ordSt','')).lower(),'UNKNOWN')
        if r.status=='UNKNOWN': issue('unknown_status','status')
        r.order_id=text(raw.get('nOrdNo')); num('order_price','prc'); num('trigger_price','trgPrc'); num('filled_quantity','fldQty'); num('pending_quantity','unFldSz')
    return r

def normalize_portfolio(observations,catalogue,*,observed_at):
    sections={}
    for name in ('holdings','positions','orders','funds'):
        obs=observations.get(name,SectionObservation(error_code='fetch_failed')); sec=PortfolioSection(state='available',retrieval_started_at=obs.retrieval_started_at,retrieval_finished_at=obs.retrieval_finished_at); sections[name]=sec
        if obs.error_code:
            sec.state='unavailable'; sec.issues=[PortfolioIssue(code='timeout' if obs.error_code=='timeout' else 'fetch_failed')]; continue
        data=obs.raw.get('data',obs.raw if name=='funds' else None) if isinstance(obs.raw,dict) else None
        if not isinstance(data,dict if name=='funds' else list):
            sec.state='invalid'; sec.issues=[PortfolioIssue(code='invalid_envelope')]; continue
        if name=='funds':
            for target,key in [('available','Net'),('reserved','MarginUsed'),('realized','RealizedMtomPrsnt'),('unrealized','UnrealizedMtomPrsnt')]:
                try: v=parse_decimal(data.get(key),allow_negative=True)
                except ValueError: v=None; sec.issues.append(PortfolioIssue(code='invalid_number',field=target))
                if v is None: sec.issues.append(PortfolioIssue(code='missing_value',field=target))
                sec.values[target]=v
                if v is not None: sec.provenance[target]=ValueProvenance(source='provider',input_paths=[key],basis='provider_funds_INR')
            if data.get('currency') not in (None,'INR'):
                sec.values={k:None for k in sec.values}; sec.issues.append(PortfolioIssue(code='unknown_currency'))
        else:
            sec.source_count=len(data); sec.rows=[row(raw,name,i,catalogue) for i,raw in enumerate(data)]
        if sec.issues or any(r.issues for r in sec.rows): sec.state='partial'
    def total(name,field):
        sec=sections[name]
        if sec.state in ('invalid','unavailable') or any(getattr(r,field) is None or r.identity_status in ('invalid','ambiguous') or r.currency is None or r.quantity is None for r in sec.rows): return None
        try:
            with localcontext() as ctx:
                ctx.prec=64
                return sum((getattr(r,field) for r in sec.rows),Decimal(0))
        except DecimalException:
            sec.issues.append(PortfolioIssue(code='calculation_overflow',field=field)); sec.state='partial'
            return None
    summary={k:total('holdings',f) for k,f in [('invested','invested_value'),('holdings_value','market_value'),('holdings_pnl','calculated_pnl')]}; summary.update(sections['funds'].values)
    summary.update(positions_provider_pnl=total('positions','provider_pnl'),positions_calculated_pnl=total('positions','calculated_pnl'))
    starts=[s.retrieval_started_at for s in sections.values() if s.retrieval_started_at]; ends=[s.retrieval_finished_at for s in sections.values() if s.retrieval_finished_at]; states=[s.state for s in sections.values()]
    completeness='complete' if all(s=='available' for s in states) else 'unavailable' if all(s=='unavailable' for s in states) else 'invalid' if all(s=='invalid' for s in states) else 'partial'
    # Risk inputs/underlying inventory proof intentionally remain absent: current
    # provider aliases do not establish grouping, margin denominator or P&L period.
    return PortfolioSnapshot(retrieval_started_at=min(starts,default=observed_at),retrieval_finished_at=max(ends,default=observed_at),source_observed_at=min(starts,default=observed_at),sections=sections,summary=summary,completeness=completeness,limitations=['Section observations are non-atomic.','Provider MTM and calculated cash-flow P&L have distinct bases; holdings and positions may overlap.'])

def to_legacy_portfolio(snapshot):
    def finite(v):
        if v is None: return None
        n=float(v); return n if math.isfinite(n) else None
    result={k:finite(snapshot.summary.get(k)) for k in ('available','reserved','realized','unrealized','invested','holdings_value','holdings_pnl')}
    result.update(source=snapshot.source,equity=None,synced_at=snapshot.source_observed_at.isoformat(),quality=snapshot.completeness,evidence_id=str(snapshot.evidence_id),valuation_error=None,section_errors={})
    for name,sec in snapshot.sections.items():
        if sec.state in ('invalid','unavailable'): result['section_errors'][name]=sec.issues[0].code if sec.issues else 'fetch_failed'
        if name=='funds': continue
        result[name]=[]
        for r in sec.rows:
            item=dict(instrument_id=f'{r.exchange}|{r.token}' if r.token and r.exchange and r.identity_basis=='catalogue_match' else None,symbol=r.symbol,exchange=r.exchange,kind='EQUITY' if name=='holdings' else 'LIVE',quantity=finite(r.quantity),average_price=finite(r.average_price),ltp=finite(r.last_price),pnl=finite(r.provider_pnl if r.provider_pnl is not None else r.calculated_pnl),quality='partial' if r.issues else 'available')
            if name=='holdings': item.update(sellable_quantity=finite(r.available_quantity),invested=finite(r.invested_value),current_value=finite(r.market_value))
            elif name=='positions': item['product']=r.product
            else: item.update(id=r.order_id,side=r.side,status=r.status,fill_price=finite(r.average_price),limit_price=finite(r.order_price))
            result[name].append(item)
    return result
