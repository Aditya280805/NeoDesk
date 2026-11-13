# Optional ledger import

Ledger upload is optional in Analytics chat > Optional historical inputs. Market, option and current-position analyses do not require a ledger. The file is submitted only with the next question and retained in that authenticated owner's private historical-input dataset; raw CSV is not projected into specialist evidence. Session expiry clears the browser draft. Imported amounts remain user-declared, not broker-verified.

Use Show saved imports to list your latest100 historical-input datasets, then Delete import to remove the original saved dataset after confirmation. Another account cannot list or delete it. Previously generated reports can retain derived summaries; deleting an import is not deletion of conversation/report history. API: GET /api/options-agent/imports and DELETE /api/options-agent/imports/{dataset_id}, authenticated individual owners only. Missing and other-owner datasets both return404.

Supported initial format: UTF-8 CSV, at most1MiB/10,000 transactions, exactly these columns in order:

For another CSV layout, set column mapping before selecting the file: source date/type/amount column names, amount unit (INR or PAISE), supported date format, and explicit transaction-label mapping JSON. Extra columns are discarded before persistence. Duplicate headers, ambiguous/missing mapped columns, unknown transaction labels and fractional-paise amounts are rejected. Supported dates: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY. Separate debit/credit columns, statement preambles, Excel and PDF require conversion and are not automatically interpreted.

```csv
date,type,amount_paise
2026-01-01,DEPOSIT,10000000
2026-01-02,WITHDRAWAL,200000
```

Dates must be YYYY-MM-DD and nondecreasing. Amounts are nonnegative integer paise. Types: DEPOSIT, WITHDRAWAL, CHARGE, SETTLEMENT_CREDIT, SETTLEMENT_DEBIT. This is a canonical template, not automatic support for arbitrary broker CSV/Excel/PDF statements. Remove personal identifier columns before import; unknown columns are rejected.

Results show cash-movement totals and net external flows. These are not investment profit or returns. Ledger alone cannot establish complete historical inventory, adjusted prices, account-equity drawdown, time-weighted performance, exchange margin or complete post-proposal risk. Those metrics remain unavailable unless their required verified inputs exist. This optional coverage does not block other agent tools.

Release scope: code supports optional owner-scoped imports and explicit missing-data behavior. Broader broker-file mapping, persisted-import management/deletion UI, authenticated ledger acquisition, adjusted-price feeds and complete-account risk acceptance remain separate unfinished features. Do not market this as complete broker reconciliation or production-verified whole-account advice.
