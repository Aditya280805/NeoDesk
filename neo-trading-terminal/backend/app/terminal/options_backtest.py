"""Deterministic offline event cursor, matched covered fills and physical ledger.

Pure functions permit restart from each published event. No broker calls, selection
strategy, annualization, synthetic prices, or authority to place an order.
"""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, localcontext
from math import lcm
from .options_history import stamp
from .options_history_contracts import BacktestRequest
from .options_strategy_contracts import calculation_context
from .options_strategies import _metrics
from .options_platform_risk import unitized_drawdown

ZERO=Decimal(0)
def num(value):return Decimal(str(value))
def text(value):
    s=format(value,'f');return s.rstrip('0').rstrip('.') if '.' in s else s
def when(value):return datetime.fromisoformat(value)
def _ids(e):return [e.stock_contract_id,e.call_contract_id]+([e.put_contract_id] if e.put_contract_id else [])

class HistoricalEngine:
    def __init__(self,dataset,request):
        self.dataset=dataset;self.request=BacktestRequest.model_validate(request);self.rows=dataset['rows']
        self.start=stamp(self.request.start);self.end=stamp(self.request.end)
        self.quotes={};self.contracts={};self.settlements={}
        for r in self.rows:
            target=self.contracts if r['row_type']=='contract' else self.quotes if r['row_type']=='quote' else self.settlements if r['row_type']=='settlement' else None
            if target is not None:target.setdefault(r['contract_id'],[]).append(r)
        self.plans=[];self.events=[];previous_end=None
        # Every initial holding contributes to account equity, so its source
        # coverage and corporate actions belong to the simulated universe too.
        relevant={holding.contract_id for holding in self.request.initial_inventory}
        for i,e in enumerate(self.request.entries):
            decision=stamp(e.decision_at);ids=_ids(e);relevant.update(ids)
            terms=[self.contract(id,decision) for id in ids]
            if any(t is None for t in terms):raise ValueError('decision_evidence_missing')
            stock,call=terms[:2];put=terms[2] if len(terms)==3 else None
            if stock['kind']!='equity' or call['kind']!='call' or (put and put['kind']!='put') or any(t['underlying_id']!=stock['contract_id'] for t in terms):raise ValueError('selection_identity_invalid')
            if put and (put['expiry']!=call['expiry'] or num(put['strike'])>num(call['strike'])):raise ValueError('selection_expiry_invalid')
            if call['expiry']<=e.decision_at.date().isoformat():raise ValueError('expiry_not_future')
            events=[]
            for t in terms[1:]:
                ss=[s for s in self.settlements.get(t['contract_id'],[]) if when(s['effective_at']).astimezone(e.decision_at.tzinfo).date().isoformat()==t['expiry'] and s['verified']=='true' and s['settlement_rule']==t['settlement_rule']]
                if len(ss)!=1:raise ValueError('settlement_missing_or_ambiguous')
                s=ss[0]
                if s['known_at']>s['timestamp'] or s['timestamp']!=s['effective_at'] or s['timestamp']>self.end:raise ValueError('settlement_unsupported_period')
                events.append(s)
            if len({(s['timestamp'],s['price']) for s in events})!=1:raise ValueError('settlement_conflict')
            expiry=events[0]['timestamp']
            if previous_end is not None and decision<=previous_end:raise ValueError('overlapping_positions')
            previous_end=expiry
            for id in ids:
                if self.quote(id,decision) is None:raise ValueError('decision_evidence_missing')
                # Every selected leg must have an explicit expected source window
                # that includes the decision. Missing periods are never invented.
                if not any(w['contract_id']==id and stamp(w['start'])<=decision<=stamp(w['end']) for w in dataset['declaration']['expected_intervals']):raise ValueError('unsupported_period_undeclared')
            timestamps=sorted({q['timestamp'] for q in self.quotes.get(ids[0],[]) if decision<q['timestamp']<expiry and q['timestamp']<=self.end})
            fills=None;fill_at=decision
            for t in timestamps:
                candidate=[next((q for q in self.quotes.get(id,[]) if q['timestamp']==t and q['known_at']<=t),None) for id in ids]
                if all(candidate):
                    if any(not any(w['contract_id']==id and stamp(w['start'])<=t<=stamp(w['end']) for w in dataset['declaration']['expected_intervals']) for id in ids):raise ValueError('unsupported_period_fill_undeclared')
                    if any(self.contract(id,t)!=term for id,term in zip(ids,terms)):raise ValueError('action_during_pending_entry')
                    fills=candidate;fill_at=t;break
            plan=dict(index=i,entry=e.model_dump(mode='json'),terms=terms,quotes=fills,fill_at=fill_at,expiry=expiry,settlements=events)
            self.plans.append(plan)
            self.events.append(dict(at=fill_at,order=1,kind='entry',index=i))
            self.events.append(dict(at=expiry,order=3,kind='expiry',index=i))
        if any(g['contract_id'] in relevant and self.start<=g['timestamp']<=self.end for g in dataset['coverage']['gaps']):raise ValueError('unsupported_period_quote_gap')
        for r in self.rows:
            if r['row_type']=='corporate_action' and self.start<=r['effective_at']<=self.end and r['contract_id'] in relevant:
                if r['known_at']>r['effective_at']:raise ValueError('corporate_action_late_metadata')
                for id in r['adjusted_contract_ids'].split('|'):
                    adjusted=self.contract(id,r['effective_at'])
                    if adjusted is None or adjusted['effective_at']!=r['effective_at'] or adjusted['adjustment_id']!=r['adjustment_id']:
                        raise ValueError('corporate_action_late_metadata')
                self.events.append(dict(at=r['effective_at'],order=0,kind='action',row=r))
        for t in sorted({self.start,self.end}|{stamp(t) for t in self.request.valuation_times}|{p['fill_at'] for p in self.plans}):
            self.events.append(dict(at=t,order=4,kind='valuation'))
        self.events.sort(key=lambda x:(x['at'],x['order'],x.get('index',0)))
        self.initial=self.initial_state()

    def contract(self,id,at):
        values=[r for r in self.contracts.get(id,[]) if r['effective_at']<=at and r['known_at']<=at]
        return max(values,key=lambda r:r['effective_at']) if values else None

    def quote(self,id,at):
        values=[q for q in self.quotes.get(id,[]) if q['timestamp']<=at and q['known_at']<=at]
        q=max(values,key=lambda q:q['timestamp']) if values else None
        if q is None or (when(at)-when(q['timestamp'])).total_seconds()>self.request.quote_max_age_seconds:return None
        return q

    def initial_state(self):
        inv={};basis={}
        for h in self.request.initial_inventory:
            c=self.contract(h.contract_id,self.start)
            if c is None or c['kind']!='equity':raise ValueError('initial_inventory_identity')
            inv[h.contract_id]=str(h.quantity);basis[h.contract_id]=text(h.acquisition_cost_per_unit)
        return dict(cursor=0,cash=text(self.request.initial_capital),inventory=inv,initial_basis=basis,positions={},trades=[],cash_ledger=[],equity_curve=[],attribution=[],total_fees='0',slippage_cost='0',max_exposure='0',performance_status='complete',initial_equity=None)

    def _cash(self,state,at,amount,kind,contract_id=None):
        state['cash']=text(num(state['cash'])+amount)
        state['cash_ledger'].append(dict(at=at,kind=kind,contract_id=contract_id,amount=text(amount),balance=state['cash']))

    def step(self,state):
        state=deepcopy(state)
        if state['cursor']>=len(self.events):return state
        event=self.events[state['cursor']]
        with localcontext(calculation_context()):
            if event['kind']=='entry':self._entry(state,self.plans[event['index']],event['at'])
            elif event['kind']=='expiry':self._expiry(state,self.plans[event['index']],event['at'])
            elif event['kind']=='action':self._action(state,event['row'])
            else:self._valuation(state,event['at'])
        state['cursor']+=1
        return state

    def _entry(self,s,p,at):
        e=p['entry'];ids=[t['contract_id'] for t in p['terms']];q=e['quantity'];quotes=p['quotes'];cost=self.request.costs
        lots=lcm(*(int(t['lot_size']) for t in p['terms']))
        if q%lots:raise ValueError('quantity_lot_mismatch')
        qty=q if quotes else 0
        if quotes:
            for i,quote in enumerate(quotes):
                if i==0 and self.request.mode=='owned':continue
                key='bid_quantity' if i==1 else 'ask_quantity'
                if key in quote:qty=min(qty,int(num(quote[key])))
                elif self.request.fill_policy=='depth_required':qty=0
            if self.request.mode=='owned':qty=min(qty,int(num(s['inventory'].get(ids[0],'0'))))
        qty=qty//lots*lots
        slip=cost.slippage_per_unit
        prices=[num(quote['bid' if i==1 else 'ask'])+(-slip if i==1 else slip) for i,quote in enumerate(quotes)] if quotes else []
        if any(price<0 for price in prices):qty=0
        leg_count=len(ids)-(1 if self.request.mode=='owned' else 0)
        if qty:
            # Require cash to fund purchases before using premium proceeds.
            buy_per_unit=(prices[0] if self.request.mode=='hypothetical' else ZERO)+(prices[2] if len(ids)==3 else ZERO)
            available=max(ZERO,num(s['cash'])-cost.opening_fee_inr*leg_count)
            if buy_per_unit>0:qty=min(qty,int(available/buy_per_unit)//lots*lots)
        trade=dict(index=p['index'],decision_at=e['decision_at'],filled_at=at,quantity=qty,requested_quantity=q,unfilled_quantity=q-qty,status='filled' if qty==q else 'partial' if qty else 'no_fill',legs=[])
        s['trades'].append(trade)
        if not qty:return
        for i,id in enumerate(ids):
            if i==0 and self.request.mode=='owned':continue
            direction=-1 if i==1 else 1
            s['inventory'][id]=text(num(s['inventory'].get(id,'0'))+direction*qty)
            amount=-direction*qty*prices[i]
            self._cash(s,at,amount,'fill',id)
            trade['legs'].append(dict(contract_id=id,side='sell' if direction<0 else 'buy',quantity=qty,price=text(prices[i])))
        fees=cost.opening_fee_inr*leg_count
        self._cash(s,at,-fees,'opening_fees');s['total_fees']=text(num(s['total_fees'])+fees)
        s['slippage_cost']=text(num(s['slippage_cost'])+slip*qty*leg_count)
        basis=num(s['initial_basis'][ids[0]]) if self.request.mode=='owned' else prices[0]
        metrics=_metrics(Decimal(qty),basis,num(p['terms'][1]['strike']),prices[1],num(p['terms'][2]['strike']) if len(ids)==3 else None,prices[2] if len(ids)==3 else ZERO,fees+cost.expiry_fee_inr*(len(ids)-1),self.request.initial_capital,'historical fills')
        option_cash=Decimal(qty)*(prices[1]-(prices[2] if len(ids)==3 else ZERO))-fees
        s['positions'][str(p['index'])]=dict(quantity=qty,stock_id=ids[0],option_ids=ids[1:],metrics=metrics.model_dump(mode='json'),basis=text(basis),option_cash=text(option_cash),dividends='0',action_adjusted=False)

    def _expiry(self,s,p,at):
        position=s['positions'].get(str(p['index']))
        if not position:return
        qty=num(position['quantity']);stock=position['stock_id'];price=num(p['settlements'][0]['price']);delivered=ZERO;proceeds=ZERO;expiry_fees=ZERO
        for id in position['option_ids']:
            terms=self.contract(id,at)
            if terms is None or terms['settlement_rule']!='physical-european.1':raise ValueError('settlement_terms_unavailable')
            inventory=num(s['inventory'].get(id,'0'));strike=num(terms['strike'])
            itm=price>strike if terms['kind']=='call' else price<strike
            if itm:
                # Short call and long put both deliver owned stock for strike.
                delivery=abs(inventory)
                if num(s['inventory'].get(stock,'0'))<delivery:raise ValueError('uncovered_delivery')
                s['inventory'][stock]=text(num(s['inventory'].get(stock,'0'))-delivery)
                self._cash(s,at,delivery*strike,'physical_delivery',id)
                delivered+=delivery;proceeds+=delivery*strike
            s['inventory'][id]='0'
            fee=self.request.costs.expiry_fee_inr
            self._cash(s,at,-fee,'expiry_fees',id);s['total_fees']=text(num(s['total_fees'])+fee)
            expiry_fees+=fee
        from .options_strategy_contracts import PayoffMetrics
        expected=PayoffMetrics.model_validate(position['metrics']).profit_at(price)
        realised=num(position['option_cash'])+num(position['dividends'])+proceeds-delivered*num(position['basis'])-expiry_fees
        total=realised+(qty-delivered)*(price-num(position['basis']))
        s['attribution'].append(dict(index=p['index'],settlement_price=text(price),basis_label='acquisition_cost' if self.request.mode=='owned' else 'actual_fill_cost',realised_profit=text(realised),expiry_total_profit=text(total),expiry_difference=None if position['action_adjusted'] else text(total-expected),expiry_expected_profit=None if position['action_adjusted'] else text(expected),status='corporate_action_adjusted_ledger_only' if position['action_adjusted'] else 'task2_expiry_payoff',calculation_version='options-strategy.1'))
        del s['positions'][str(p['index'])]

    def _action(self,s,row):
        at=row['effective_at'];stock=row['contract_id'];held=num(s['inventory'].get(stock,'0'))
        if row['action']=='cash_dividend':self._cash(s,at,held*num(row['amount']),'cash_dividend',stock)
        else:
            ratio=num(row['ratio'])
            if held*ratio!=(held*ratio).to_integral_value():raise ValueError('fractional_split_unsupported')
            s['inventory'][stock]=text(held*ratio)
            if stock in s['initial_basis']:
                # This acquisition basis survives closed positions and cursor
                # restart; later owned entries must use current-share basis.
                s['initial_basis'][stock]=text(num(s['initial_basis'][stock])/ratio)
            for id in row['adjusted_contract_ids'].split('|'):
                if id==stock:continue
                current=num(s['inventory'].get(id,'0'))*ratio
                terms=self.contract(id,at)
                if current%int(terms['lot_size']):raise ValueError('adjusted_lot_mismatch')
                if id in s['inventory']:s['inventory'][id]=text(current)
        for p in s['positions'].values():
            if p['stock_id']==stock:
                p['action_adjusted']=True
                if row['action']=='cash_dividend':p['dividends']=text(num(p['dividends'])+num(p['quantity'])*num(row['amount']))
                else:p['quantity']=text(num(p['quantity'])*ratio);p['basis']=text(num(p['basis'])/ratio)

    def _valuation(self,s,at):
        equity=num(s['cash']);exposure=ZERO;missing=[]
        for id,quantity in s['inventory'].items():
            q=num(quantity)
            if not q:continue
            quote=self.quote(id,at)
            if quote is None:missing.append(id);continue
            value=q*num(quote['bid' if q>0 else 'ask']);equity+=value
            if self.contract(id,at)['kind']=='equity':exposure+=abs(value)
        s['max_exposure']=text(max(exposure,num(s['max_exposure'])))
        if missing:s['performance_status']='unavailable_segments'
        point=dict(at=at,cash=s['cash'],inventory=deepcopy(s['inventory']),equity=None if missing else text(equity),missing_contracts=missing,external_flow='0')
        s['equity_curve'].append(point)
        if at==self.start:s['initial_equity']=point['equity']

    def report(self,s):
        if s['cursor']!=len(self.events):raise ValueError('unfinished_cursor')
        curve=s['equity_curve'];last=curve[-1];dd=None
        if s['performance_status']=='complete' and all(num(p['equity'])>=0 for p in curve):
            dd=unitized_drawdown([dict(observed_at=p['at'],sequence=i,equity_inr=p['equity']) for i,p in enumerate(curve)])
        return dict(version='options-backtest.1',calculation_version='options-strategy.1',dataset_hash=self.dataset['content_hash'],schema_version=self.dataset['schema_version'],cost_assumptions=self.request.costs.model_dump(mode='json'),implementation_status='implemented',dataset_status=self.dataset['declaration']['dataset_status'],live_verification='unverified',confidence='low' if self.request.fill_policy=='assume_unlimited_depth' else 'offline',assumptions=['User supplied costs; no broker verification.','Physical European settlement is explicitly declared by the dataset, not independently exchange certified.']+(['Unlimited depth explicitly assumed; low confidence.'] if self.request.fill_policy=='assume_unlimited_depth' else []),cash=s['cash'],inventory=s['inventory'],trades=s['trades'],cash_ledger=s['cash_ledger'],equity_curve=curve,attribution=s['attribution'],total_fees=s['total_fees'],slippage_cost=s['slippage_cost'],max_exposure=s['max_exposure'],performance_status=s['performance_status'],max_drawdown=text(dd) if dd is not None else None,net_profit=text(num(last['equity'])-num(s['initial_equity'])) if last['equity'] is not None and s['initial_equity'] is not None and s['performance_status']=='complete' else None,realised_cash_change=text(num(s['cash'])-self.request.initial_capital),annualized_return=None)

def run_backtest(dataset,request):
    engine=HistoricalEngine(dataset,request);state=engine.initial
    while state['cursor']<len(engine.events):state=engine.step(state)
    return engine.report(state)
