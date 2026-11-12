# Completion gate

The implementation is not fully complete. Previous percentage estimates were informal and should not be used as acceptance evidence. Use PLAN.md and verified behavior instead.

Implemented paths include role-scoped tools, budgets, deterministic calculation kernels, immutable evidence, declared technical/return/risk/surface input capture, typed proposal transport, explicit continuations and an opt-in chat UI. Missing input remains unavailable. Default live capture supports OI; imported scenarios retain unverified provenance.

Remaining acceptance gaps:

| Area | Required completion evidence |
| --- | --- |
| Verified proposals | Canonical option/underlying tokens, contract-specific lot/expiry metadata, timestamped bid/ask, forward/rate sources, and fixtures proving contradictory identities reject. Legacy chain/catalogue mapping explicitly does not establish these. |
| Live regulatory checks | Applicable dated SEBI/exchange rules, instrument classification, published ban/MWPL inputs and verified margin/position-limit bases; complete-account and post-proposal combination tests. Current conservative checks are incomplete. |
| Fee/payoff coverage | Verified exchange/broker schedules and aggregation policy, quote/expiry context and dated source revisions. Statutory arithmetic exists; unknown fee components are unavailable. |
| Attribution/HRP | Eligible cash-asset adjusted histories, complete trade/sector mappings, cash-flow adjustments and an authenticated source adapter. Imported return ratios work; complete attribution does not. |
| Live source proof | Explicit authenticated broker smoke checks and saved sanitized representative response fixtures. Offline fixtures do not establish production data availability. |
| Release gate | Dedicated UI visual verification, complete final branch review and deployment checks. Remote CI and Docker execution have not been established on this host. |

Relevant local evidence: backend/app/terminal/options_readiness.py get_data_capabilities and legacy_chain_to_evidence. That inventory explicitly marks contract_identity and lot_size_expiry unverified, exchange_timestamp and IV missing, and margin/account_pnl basis unverified. Do not promote client declarations or parser defaults to verification flags.

Several gaps above still require internal adapter and calculation work. The approved plan separately requires explicit authorization before live credential use. Live source validation needs read-only broker smoke authorization, plus an authoritative dated fee/rule data source or validated imports. Do not place orders, enable execution, or publish/deploy while resolving these gaps.
