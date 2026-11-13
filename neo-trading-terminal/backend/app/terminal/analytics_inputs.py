"""Bounded declared historical inputs; user imports never become live verification."""
import hashlib
import math
from datetime import date, datetime, UTC
from typing import Literal, Annotated
from zoneinfo import ZoneInfo
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator, StrictBool

from .analytics_contracts import Contract
from .options_snapshot import OptionsContext
from .options_history_contracts import Money


class HistoricalBar(Contract):
    time: AwareDatetime
    open: float = Field(gt=0, allow_inf_nan=False)
    high: float = Field(gt=0, allow_inf_nan=False)
    low: float = Field(gt=0, allow_inf_nan=False)
    close: float = Field(gt=0, allow_inf_nan=False)
    volume: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def prices(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError('Contradictory OHLC')
        return self


class DeclaredRiskPosition(Contract):
    contract_id: str = Field(min_length=1,max_length=100)
    underlying: str = Field(min_length=1,max_length=100)
    kind: Literal['equity','future','option']
    quantity: int = Field(strict=True,ge=-1000000,le=1000000)
    spot: float = Field(ge=1e-8,le=1e12,allow_inf_nan=False)
    forward: float | None = Field(default=None,ge=1e-8,le=1e12,allow_inf_nan=False)
    strike: float | None = Field(default=None,ge=1e-8,le=1e12,allow_inf_nan=False)
    expiry_at: AwareDatetime | None = None
    iv: float | None = Field(default=None,ge=1e-8,le=10,allow_inf_nan=False)
    rate: float | None = Field(default=None,ge=-1,le=1,allow_inf_nan=False)
    option_type: Literal['CALL','PUT'] | None = None

    @model_validator(mode='after')
    def option_inputs(self):
        if self.kind=='option' and any(getattr(self,key) is None for key in ('forward','strike','expiry_at','iv','rate','option_type')):
            raise ValueError('Option full repricing inputs required')
        return self


class DeclaredRiskObservation(Contract):
    date: date
    session: int = Field(strict=True,ge=0)
    spot: float | None = Field(default=None,ge=1e-8,le=1e12,allow_inf_nan=False)
    iv: float | None = Field(default=None,ge=1e-8,le=10,allow_inf_nan=False)


class DeclaredSurfaceRow(Contract):
    contract_id: str = Field(min_length=1,max_length=100)
    side: Literal['CALL','PUT']
    strike: float = Field(ge=1e-8,le=1e12,allow_inf_nan=False)
    expiry_at: AwareDatetime
    forward: float = Field(ge=1e-8,le=1e12,allow_inf_nan=False)
    rate: float = Field(ge=-1,le=1,allow_inf_nan=False)
    iv: float = Field(ge=1e-8,le=10,allow_inf_nan=False)
    open_interest: int = Field(strict=True,ge=0,le=1000000000)
    lot_size: int = Field(strict=True,gt=0,le=100000)


class DeclaredAssetHistory(Contract):
    asset_id: str = Field(min_length=1,max_length=100)
    kind: Literal['cash_equity','cash_etf','option','future']
    sector: str | None = Field(default=None,min_length=1,max_length=100)
    value_paise: int = Field(strict=True,ge=0,le=1000000000000000)
    adjusted_prices: tuple[Annotated[float,Field(ge=1e-8,le=1e12,allow_inf_nan=False)],...] = Field(max_length=5000)
    beginning_values_paise: tuple[Annotated[int,Field(strict=True,ge=0,le=1000000000000000)],...] = Field(default=(),max_length=4999)


class DeclaredClosedTrade(Contract):
    trade_id: str = Field(min_length=1,max_length=100)
    closed_at: AwareDatetime
    net_pnl_paise: int = Field(strict=True,ge=-1000000000000000,le=1000000000000000)


class DeclaredFeeTransaction(Contract):
    transaction_id: str = Field(min_length=1,max_length=100)
    product: Literal['option','future','delivery','intraday']
    side: Literal['BUY','SELL','EXERCISE']
    trade_date: date
    turnover_inr: Money
    turnover_basis: Literal['option_premium','option_intrinsic','futures_notional','cash_trade_value']
    cost_source: str = Field(min_length=1,max_length=1000)
    brokerage_inr: Money | None = None
    exchange_rate: Money | None = None
    sebi_rate: Money | None = None
    slippage_inr: Money | None = None

    @model_validator(mode='after')
    def applicable(self):
        basis = 'option_intrinsic' if self.side=='EXERCISE' else 'option_premium' if self.product=='option' else 'futures_notional' if self.product=='future' else 'cash_trade_value'
        if self.turnover_basis!=basis or self.side=='EXERCISE' and self.product!='option':
            raise ValueError('Transaction turnover basis differs from applicable charge basis')
        if self.trade_date<date(2024,10,1):
            raise ValueError('No supported historical statutory schedule')
        if any(value is not None and value>1 for value in (self.exchange_rate,self.sebi_rate)):
            raise ValueError('Fee rates must be fractional')
        if self.trade_date>datetime.now(UTC).astimezone(ZoneInfo('Asia/Kolkata')).date():
            raise ValueError('Future statutory schedules are not established')
        if any(value is not None and value>10000000000 for value in (self.turnover_inr,self.brokerage_inr,self.slippage_inr)):
            raise ValueError('Fee estimate amount exceeds bounded exact-paise range')
        return self


class DeclaredComplianceRule(Contract):
    contract_id: str = Field(min_length=1,max_length=100)
    source: str = Field(min_length=1,max_length=1000)
    revision: str = Field(min_length=1,max_length=100)
    instrument_scope: Literal['stock_derivative','index_derivative','cash']
    valid_from: date
    valid_until: date
    lot_size: int | None = Field(default=None,strict=True,gt=0,le=100000)
    ban_active: StrictBool | None = None
    base_futeq: float | None = Field(default=None,ge=-1e12,le=1e12,allow_inf_nan=False)
    current_futeq: float | None = Field(default=None,ge=-1e12,le=1e12,allow_inf_nan=False)
    futeq_basis: Literal['per_contract','declared_underlying_aggregate'] = 'per_contract'
    underlying_futeq_limit: float | None = Field(default=None,gt=0,le=1e12,allow_inf_nan=False)

    @model_validator(mode='after')
    def limit_basis(self):
        if self.underlying_futeq_limit is not None and self.futeq_basis!='declared_underlying_aggregate':
            raise ValueError('Underlying position limit requires explicitly aggregated FutEq basis')
        return self


class DeclaredParticipantReport(Contract):
    report_date: date
    csv: str = Field(min_length=1,max_length=1048576)


class DeclaredProposalCostScenario(Contract):
    template: Literal['bull_call_spread','bear_put_spread']
    buy_contract_id: str = Field(min_length=1,max_length=100)
    sell_contract_id: str = Field(min_length=1,max_length=100)
    expiry: date
    quantity: int = Field(strict=True,gt=0,le=1000000)
    valued_at: AwareDatetime
    buy_bid: Money
    buy_ask: Money
    sell_bid: Money
    sell_ask: Money
    roundtrip_cost_paise: int = Field(strict=True,ge=0,le=9007199254740991)
    source: str = Field(min_length=1,max_length=1000)

    @model_validator(mode='after')
    def coherent(self):
        if self.buy_contract_id==self.sell_contract_id or self.buy_bid>self.buy_ask or self.sell_bid>self.sell_ask:
            raise ValueError('Distinct contracts and uncrossed captured quote scenario required')
        return self


class DeclaredCashFutureBasis(Contract):
    underlying: str = Field(min_length=1,max_length=100)
    future_contract_id: str = Field(min_length=1,max_length=100)
    expiry_at: AwareDatetime
    spot: float = Field(gt=0,le=1e12,allow_inf_nan=False)
    future_price: float = Field(gt=0,le=1e12,allow_inf_nan=False)
    spot_observed_at: AwareDatetime
    future_observed_at: AwareDatetime
    source: str = Field(min_length=1,max_length=1000)


class HistoricalAnalyticsInput(Contract):
    schema_version: Literal['analytics-input.1'] = 'analytics-input.1'
    context: OptionsContext
    provenance: str = Field(min_length=1, max_length=1000)
    licence: str = Field(min_length=1, max_length=1000)
    observed_at: AwareDatetime
    bars: tuple[HistoricalBar, ...] = Field(default=(), max_length=500)
    vix_history: tuple[float, ...] = Field(default=(), max_length=500)
    return_dates: tuple[AwareDatetime, ...] = Field(default=(), max_length=5000)
    cash_flow_adjusted_returns: tuple[float, ...] = Field(default=(), max_length=5000)
    return_frequency: Literal['daily'] = 'daily'
    benchmark_returns: tuple[float, ...] = Field(default=(), max_length=5000)
    bank_returns: tuple[float, ...] = Field(default=(), max_length=5000)
    risk_positions: tuple[DeclaredRiskPosition,...] = Field(default=(),max_length=100)
    risk_history: dict[str,tuple[DeclaredRiskObservation,...]] = Field(default_factory=dict,max_length=100)
    risk_history_basis: Literal['current_contract_equivalent_source_declared'] | None = None
    surface_rows: tuple[DeclaredSurfaceRow,...] = Field(default=(),max_length=500)
    iv_history_dates: tuple[AwareDatetime,...] = Field(default=(),max_length=5000)
    iv_history: tuple[float,...] = Field(default=(),max_length=5000)
    iv_history_basis: Literal['constant_tenor_atm_source_declared'] | None = None
    realized_volatility: float | None = Field(default=None,gt=0,le=10,allow_inf_nan=False)
    realized_volatility_basis: Literal['annualized_daily_log_returns_source_declared'] | None = None
    cash_future_basis: DeclaredCashFutureBasis | None = None
    surface_spot: float | None = Field(default=None,ge=1e-8,le=1e12,allow_inf_nan=False)
    gex_sign_assumption: Literal['calls_positive_puts_negative'] | None = None
    asset_price_dates: tuple[AwareDatetime,...] = Field(default=(),max_length=5000)
    cash_assets: tuple[DeclaredAssetHistory,...] = Field(default=(),max_length=100)
    cash_sleeve_history_complete: StrictBool = False
    closed_trades: tuple[DeclaredClosedTrade,...] = Field(default=(),max_length=10000)
    trade_history_complete: StrictBool = False
    trade_period_start: AwareDatetime | None = None
    trade_period_end: AwareDatetime | None = None
    fee_transactions: tuple[DeclaredFeeTransaction,...] = Field(default=(),max_length=200)
    compliance_rules: tuple[DeclaredComplianceRule,...] = Field(default=(),max_length=100)
    participant_report_date: date | None = None
    participant_csv: str | None = Field(default=None,max_length=1048576)
    participant_history: tuple[DeclaredParticipantReport,...] = Field(default=(),max_length=6)
    participant_sessions_complete: StrictBool = False
    participant_price_return_5sessions: float | None = Field(default=None,ge=-1,le=1000,allow_inf_nan=False)
    proposal_cost_scenarios: tuple[DeclaredProposalCostScenario,...] = Field(default=(),max_length=20)
    ledger_csv: str | None = Field(default=None,max_length=1048576)
    ledger_mapping: dict | None = None

    @model_validator(mode='after')
    def aligned(self):
        if self.ledger_csv is not None:
            from .optional_ledger import summarize_ledger,normalize_ledger_csv
            if self.ledger_mapping is not None:
                object.__setattr__(self,'ledger_csv',normalize_ledger_csv(self.ledger_csv,self.ledger_mapping))
                object.__setattr__(self,'ledger_mapping',None)
            summarize_ledger(self.ledger_csv)
        if self.cash_future_basis is not None:
            basis=self.cash_future_basis
            if basis.underlying!=self.context.underlying or not 0<(basis.expiry_at-self.observed_at).total_seconds()<=3650*86400:
                raise ValueError('Basis requires matching underlying and active future expiry')
            if any(not 0<=(self.observed_at-time).total_seconds()<=10 for time in (basis.spot_observed_at,basis.future_observed_at)):
                raise ValueError('Basis quotes must share the declared ten-second valuation window')
        if self.iv_history or self.iv_history_dates or self.realized_volatility is not None:
            if not self.surface_rows:
                raise ValueError('Volatility history requires a declared surface')
        if len(self.iv_history)!=len(self.iv_history_dates) or self.iv_history and self.iv_history_basis is None:
            raise ValueError('Dated IV history and comparable tenor declaration required')
        iv_days = [value.astimezone(ZoneInfo('Asia/Kolkata')).date() for value in self.iv_history_dates]
        if len(iv_days)!=len(set(iv_days)) or any(a>=b for a,b in zip(self.iv_history_dates,self.iv_history_dates[1:])) or self.iv_history_dates and self.iv_history_dates[-1]>self.observed_at:
            raise ValueError('Ordered daily nonfuture IV history required')
        if any(not math.isfinite(value) or not 0<value<=10 for value in self.iv_history):
            raise ValueError('Invalid historical IV fraction')
        if self.realized_volatility is not None and self.realized_volatility_basis is None:
            raise ValueError('Annualized realized-volatility basis required')
        if not self.bars and not self.cash_flow_adjusted_returns and not self.risk_positions and not self.surface_rows and not self.cash_assets and not self.closed_trades and not self.fee_transactions and self.participant_report_date is None and not self.proposal_cost_scenarios and self.cash_future_basis is None and self.ledger_csv is None:
            raise ValueError('At least one historical series required')
        if self.participant_csv is not None and self.participant_report_date is None:
            raise ValueError('Participant CSV requires report date')
        if self.participant_report_date is not None and self.participant_report_date>min(self.observed_at.date(),datetime.now(UTC).date()):
            raise ValueError('Participant date after valuation/publication day')
        if self.participant_history:
            days = [report.report_date for report in self.participant_history]
            if sum(len(report.csv.encode()) for report in self.participant_history)>1048576 or any(a>=b for a,b in zip(days,days[1:])) or days[-1]!=self.participant_report_date:
                raise ValueError('Ordered bounded participant history must end at selected report')
        if len({row.transaction_id for row in self.fee_transactions})!=len(self.fee_transactions) or any(row.trade_date>self.observed_at.astimezone(ZoneInfo('Asia/Kolkata')).date() for row in self.fee_transactions):
            raise ValueError('Unique dated historical fee transactions required')
        if len({asset.asset_id for asset in self.cash_assets})!=len(self.cash_assets) or sum(len(asset.adjusted_prices) for asset in self.cash_assets)>100000:
            raise ValueError('Unique bounded asset histories required')
        if any(len(asset.adjusted_prices)!=len(self.asset_price_dates) for asset in self.cash_assets):
            raise ValueError('Aligned asset price dates required')
        cash = [asset for asset in self.cash_assets if asset.kind in ('cash_equity','cash_etf')]
        if any(asset.beginning_values_paise and len(asset.beginning_values_paise)!=len(self.asset_price_dates)-1 for asset in self.cash_assets):
            raise ValueError('Beginning values must align one-to-one with daily return intervals')
        if self.cash_sleeve_history_complete:
            if not cash or len(self.asset_price_dates)<2 or any(len(asset.beginning_values_paise)!=len(self.asset_price_dates)-1 for asset in cash):
                raise ValueError('Complete cash sleeve requires every cash asset daily beginning value')
            if any(sum(asset.beginning_values_paise[i] for asset in cash)<=0 for i in range(len(self.asset_price_dates)-1)):
                raise ValueError('Each complete cash-sleeve interval requires positive total beginning value')
        price_days = [value.astimezone(ZoneInfo('Asia/Kolkata')).date() for value in self.asset_price_dates]
        if len(price_days)!=len(set(price_days)) or any(a>=b for a,b in zip(self.asset_price_dates,self.asset_price_dates[1:])) or self.asset_price_dates and self.asset_price_dates[-1]>self.observed_at:
            raise ValueError('Ordered daily asset history required')
        if self.cash_assets and not self.asset_price_dates:
            raise ValueError('Dated adjusted prices required for declared assets')
        if len({trade.trade_id for trade in self.closed_trades})!=len(self.closed_trades):
            raise ValueError('Unique closed trade IDs required')
        if self.closed_trades or self.trade_history_complete:
            if self.trade_period_start is None or self.trade_period_end is None or not self.trade_period_start<self.trade_period_end<=self.observed_at:
                raise ValueError('Explicit closed-trade period required')
            if any(not self.trade_period_start<=trade.closed_at<=self.trade_period_end for trade in self.closed_trades):
                raise ValueError('Trade outside declared period')
        if len({row.contract_id for row in self.surface_rows})!=len(self.surface_rows):
            raise ValueError('Unique surface contract IDs required')
        pricing = {}
        for row in self.surface_rows:
            if not 0<(row.expiry_at-self.observed_at).total_seconds()<=3650*86400:
                raise ValueError('Active bounded expiry required')
            key = row.expiry_at
            terms = (row.forward,row.rate)
            if key in pricing and pricing[key]!=terms:
                raise ValueError('Contradictory per-expiry pricing')
            pricing[key] = terms
        if self.gex_sign_assumption and (not self.surface_rows or self.surface_spot is None):
            raise ValueError('GEX requires declared surface and spot')
        identifiers = [position.contract_id for position in self.risk_positions]
        rule_ids = [rule.contract_id for rule in self.compliance_rules]
        observation_day = self.observed_at.astimezone(ZoneInfo('Asia/Kolkata')).date()
        if len(set(rule_ids))!=len(rule_ids) or not set(rule_ids)<=set(identifiers):
            raise ValueError('Unique compliance rules must reference captured positions')
        position_kinds = {position.contract_id:position.kind for position in self.risk_positions}
        if any((rule.instrument_scope=='cash')!=(position_kinds[rule.contract_id]=='equity') for rule in self.compliance_rules):
            raise ValueError('Compliance scope contradicts declared position kind')
        if any(not rule.valid_from<=observation_day<=rule.valid_until for rule in self.compliance_rules):
            raise ValueError('Rules must be effective at declared valuation')
        if len(set(identifiers))!=len(identifiers) or any(position.underlying!=self.context.underlying for position in self.risk_positions):
            raise ValueError('Unique positions matching context required')
        if any(position.expiry_at is not None and (position.expiry_at-self.observed_at).total_seconds()>3650*86400 for position in self.risk_positions):
            raise ValueError('Option expiry beyond supported horizon')
        if self.risk_history and (not set(self.risk_history)<=set(identifiers) or self.risk_history_basis is None):
            raise ValueError('History requires declared adjustment basis and known positions')
        if sum(map(len,self.risk_history.values()))>100000:
            raise ValueError('Historical scenario limit exceeded')
        for series in self.risk_history.values():
            if len(series)>5000 or any(a.date>=b.date or a.session+1!=b.session for a,b in zip(series,series[1:])):
                raise ValueError('Ordered consecutive source-declared sessions required')
            if series and series[-1].date>self.observed_at.astimezone(ZoneInfo('Asia/Kolkata')).date():
                raise ValueError('History after declared valuation')
        for times in (tuple(bar.time for bar in self.bars), self.return_dates):
            if any(a >= b for a, b in zip(times, times[1:])) or times and times[-1] > self.observed_at:
                raise ValueError('Ordered nonfuture observations required')
        if len(self.return_dates) != len(self.cash_flow_adjusted_returns):
            raise ValueError('Dated returns required')
        days = [value.astimezone(ZoneInfo('Asia/Kolkata')).date() for value in self.return_dates]
        if len(set(days)) != len(days):
            raise ValueError('Return series requires at most one observation per trading day')
        for series in (self.cash_flow_adjusted_returns, self.benchmark_returns, self.bank_returns):
            if any(not math.isfinite(value) or value <= -1 for value in series):
                raise ValueError('Invalid simple returns')
        if any(not math.isfinite(value) or value <= 0 for value in self.vix_history):
            raise ValueError('Invalid VIX observations')
        if self.vix_history and len(self.vix_history) != len(self.bars):
            raise ValueError('VIX must align to declared bars')
        if any(series and len(series) != len(self.return_dates) for series in (self.benchmark_returns, self.bank_returns)):
            raise ValueError('Benchmark alignment required')
        return self


class AnalyticsInputStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS analytics_inputs (id TEXT PRIMARY KEY, owner INTEGER NOT NULL, checksum TEXT NOT NULL, payload TEXT NOT NULL)')

    def save(self, owner, value):
        if type(owner) is not int or owner <= 0:
            raise ValueError('Authenticated owner required')
        value = HistoricalAnalyticsInput.model_validate(value)
        encoded = value.model_dump_json()
        identity = str(uuid4())
        checksum = hashlib.sha256(encoded.encode()).hexdigest()
        with self.store.connect() as db:
            db.execute('INSERT INTO analytics_inputs VALUES (?,?,?,?)', (identity, owner, checksum, encoded))
        return dict(dataset_id=identity, checksum=checksum, provenance=value.provenance, live_verification='unverified')

    def list_owned(self,owner):
        if type(owner) is not int or owner<=0: raise ValueError('Authenticated owner required')
        with self.store.connect() as db:
            rows=db.execute('SELECT id FROM analytics_inputs WHERE owner=? ORDER BY rowid DESC LIMIT 100',(owner,)).fetchall()
        return [dict(dataset_id=row[0]) for row in rows]

    def delete_owned(self,owner,identity):
        if type(owner) is not int or owner<=0: raise ValueError('Authenticated owner required')
        identity=str(UUID(str(identity)))
        with self.store.connect() as db:
            return db.execute('DELETE FROM analytics_inputs WHERE owner=? AND id=?',(owner,identity)).rowcount==1

    def load(self, owner, identity, context):
        if type(owner) is not int or owner <= 0:
            raise ValueError('Authenticated owner required')
        identity = str(UUID(str(identity)))
        with self.store.connect() as db:
            row = db.execute('SELECT checksum,payload FROM analytics_inputs WHERE owner=? AND id=?', (owner, identity)).fetchone()
        if row is None:
            raise ValueError('Input dataset unavailable')
        if hashlib.sha256(row[1].encode()).hexdigest() != row[0]:
            raise ValueError('Input dataset integrity mismatch')
        value = HistoricalAnalyticsInput.model_validate_json(row[1])
        if value.context != context:
            raise ValueError('Input dataset market context differs')
        inputs = {}
        if value.proposal_cost_scenarios:
            inputs['proposal_cost_scenarios'] = [scenario.model_dump() for scenario in value.proposal_cost_scenarios]
        if value.participant_report_date is not None:
            inputs['participant_report_request'] = dict(date=value.participant_report_date,csv=value.participant_csv)
            inputs['participant_history_request'] = dict(reports=[report.model_dump() for report in value.participant_history],
                sessions_complete=value.participant_sessions_complete,price_return=value.participant_price_return_5sessions)
        if value.fee_transactions:
            inputs['fee_transactions'] = [transaction.model_dump(mode='json') for transaction in value.fee_transactions]
        if value.cash_assets or value.closed_trades:
            inputs['declared_attribution'] = dict(assets=[asset.model_dump(mode='json') for asset in value.cash_assets],
                dates=list(value.asset_price_dates),trades=[trade.model_dump(mode='json') for trade in value.closed_trades],
                cash_sleeve_history_complete=value.cash_sleeve_history_complete,
                trade_history_complete=value.trade_history_complete,
                trade_period_start=value.trade_period_start.isoformat() if value.trade_period_start else None,
                trade_period_end=value.trade_period_end.isoformat() if value.trade_period_end else None)
        if value.surface_rows:
            inputs.update(surface_rows=[row.model_dump() for row in value.surface_rows],forward=value.surface_rows[0].forward,
                rate=value.surface_rows[0].rate,as_of=value.observed_at,
                surface_spot=value.surface_spot,
                pricing_by_expiry={row.expiry_at.isoformat():dict(forward=row.forward,rate=row.rate) for row in value.surface_rows})
            inputs.update(iv_history=list(value.iv_history),realized_volatility=value.realized_volatility)
            if value.gex_sign_assumption:
                inputs.update(gex_rows=[{**row.model_dump(),'tau':(row.expiry_at-value.observed_at).total_seconds()/(365*86400)} for row in value.surface_rows],
                    gex_spot=value.surface_spot,gex_sign_assumption=value.gex_sign_assumption)
        if value.bars:
            inputs.update(bars=[bar.model_dump(mode='json') for bar in value.bars], vix_history=list(value.vix_history))
        if value.cash_future_basis is not None:
            inputs['cash_future_basis']=value.cash_future_basis.model_dump(mode='json')
        if value.cash_flow_adjusted_returns:
            inputs['verified_returns'] = list(value.cash_flow_adjusted_returns)
            if value.benchmark_returns:
                inputs['benchmark_returns'] = list(value.benchmark_returns)
            if value.bank_returns:
                inputs['bank_returns'] = list(value.bank_returns)
        if value.risk_positions:
            inputs['risk_positions'] = []
            for position in value.risk_positions:
                risk_row = position.model_dump(mode='json',exclude_none=True)
                if position.kind=='option':
                    risk_row['tau'] = max(0,(position.expiry_at-value.observed_at).total_seconds()/(365*86400))
                inputs['risk_positions'].append(risk_row)
            if value.risk_history:
                inputs['risk_history'] = {key:[row.model_dump(mode='json') for row in series] for key,series in value.risk_history.items()}
            if value.compliance_rules:
                inputs['rules'] = {'declared_records':[rule.model_dump(mode='json') for rule in value.compliance_rules],
                    'as_of':value.observed_at.isoformat()}
        if value.ledger_csv is not None:
            from .optional_ledger import summarize_ledger
            inputs['ledger_summary']=summarize_ledger(value.ledger_csv)
        return inputs, f'user-import:{identity}:{row[0]}', value
