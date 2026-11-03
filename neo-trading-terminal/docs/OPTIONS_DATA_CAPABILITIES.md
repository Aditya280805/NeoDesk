# Options market evidence inventory

Reviewed 2026-11-01. This is adapter evidence, not a live connectivity certification.
Installed `kotakneoapi 3.0.7` source exposes `option_chain(exchange, underlying,
expiry=None, instrument_type=None, count=None)` and `quotes(instrument_tokens,
quote_type=None)`. The SDK quote service returns provider JSON directly. No SDK
migration was performed. Current official documentation and installed behavior
are separate evidence; version compatibility does not prove account access.

## Sources checked

- [Official current SDK](https://github.com/Kotak-Neo/kotak-neo-python).
- [Official organization README](https://github.com/Kotak-Neo/Kotak-Neo): current toolkit direction; legacy references must not trigger automatic migration.
- [Quote schema](https://github.com/Kotak-Neo/kotak-neo-python/blob/main/docs/functions/market_data/quotes.md): segment/token identity, depth buy/sell price and quantity, ltp, last_volume and open_int; 50 instrument limit.
- [Chain schema](https://github.com/Kotak-Neo/kotak-neo-python/blob/main/docs/functions/market_data/option_chain.md): existing LTP/OI chain route stays compatible.
- [NSE individual stock derivatives](https://www.nseindia.com/static/products-services/equity-derivatives-individual-securities).
- [SEBI physical settlement circular 2019/28](https://www.sebi.gov.in/legal/circulars/feb-2019/physical-settlement-of-stock-derivatives_42021.html).
- [NSE physical settlement FAQ](https://nsearchives.nseindia.com/content/circulars/INSP38433.pdf).

Settlement sources describe physical delivery but do not establish a versioned
rule for each catalogue contract. Generic cash settlement descriptions must not
override stock-specific circulars. Settlement remains unverified; no synthetic
rule metadata is published as live authority.

## Actual application capability

| Area | Current adapter | Downstream restriction |
| --- | --- | --- |
| Holdings, positions, orders | Existing portfolio read adapters | Non-atomic observations; preserve section availability |
| Fills | SDK trade_report exists; no canonical adapter | Missing canonical fills |
| Option identity | Exact symbol/expiry/strike/side catalogue match resolves option token only | Underlying ID remains null; no verified identity from symbol |
| Lots and expiry | Chain expiry parsed; raw master lot provenance retained on new imports | Positive integer raw lLotSize may populate lot; old catalogue defaults remain null |
| LTP, volume, OI | Chain adapter; exact-token quote enrichment | Indicative observation, no execution guarantee |
| Bid/ask quantities and prices | Optional documented quotes depth mapping | Legacy chain alone has none; crossed quotes rejected |
| Exchange time, IV | No established semantic mapping | Null; retrieval time is separate |
| Margin/account P&L | Limits/MTM exist in provider | Unverified account basis and reporting period |
| Historical options | SDK candle method exists | Contract history coverage unverified |
| Settlement | No per-contract rule resolver | Unverified; no expiry delivery calculation authority |

`fetch_strategy_market_evidence` is explicit synchronous worker-thread acquisition:
one bounded 20-strike chain request, local catalogue search, then at most one
50-token quote request. It propagates explicit user ID and deadline to Market.call.
It is not wired into any execution or public endpoint. Absent provider fields
stay null, including when a quote response omits previously observed chain data.
No live account call was made in validation.

The additive catalogue `source_metadata` records original `lLotSize` and
`pInstType` with source `kotak-scrip-master`. It does not establish an underlying
token or settlement eligibility. Integer raw lot is accepted only within contract
bounds; absent, fractional or malformed source lots remain unavailable.

Frozen Pydantic objects use tuples, reject unknown fields and duplicate identities,
bound numeric magnitudes/counts, and serialize decimals as strings. Optional lot
and underlying fields deliberately represent unavailable evidence. Consumers must
require identity_verified and settlement_verified before applying contract rules.
Completeness is coverage metadata, not freshness or suitability approval.

Local CLI: `python -m app.terminal.options_readiness` imports no SDK/config and
makes no network call. Explicit `--mode live-broker` delegates broker smoke;
`--mode live-model` delegates existing model evaluation/configuration. Returned
status is sanitized; provider exceptions and credentials are suppressed. No
billing or quota configuration is changed.
