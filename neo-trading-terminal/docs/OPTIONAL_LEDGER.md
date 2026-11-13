# Optional ledger import

Ledger upload is optional in Analytics chat > Optional historical inputs. Market, option and current-position analyses do not require a ledger. The file is submitted only with the next question and retained in that authenticated owner's private historical-input dataset; raw CSV is not projected into specialist evidence. Session expiry clears the browser draft. Imported amounts remain user-declared, not broker-verified.

Supported initial format: UTF-8 CSV, at most1MiB/10,000 transactions, exactly these columns in order:

```csv
date,type,amount_paise
2026-01-01,DEPOSIT,10000000
2026-01-02,WITHDRAWAL,200000
```

Dates must be YYYY-MM-DD and nondecreasing. Amounts are nonnegative integer paise. Types: DEPOSIT, WITHDRAWAL, CHARGE, SETTLEMENT_CREDIT, SETTLEMENT_DEBIT. This is a canonical template, not automatic support for arbitrary broker CSV/Excel/PDF statements. Remove personal identifier columns before import; unknown columns are rejected.

Results show cash-movement totals and net external flows. These are not investment profit or returns. Ledger alone cannot establish complete historical inventory, adjusted prices, account-equity drawdown, time-weighted performance, exchange margin or complete post-proposal risk. Those metrics remain unavailable unless their required verified inputs exist. This optional coverage does not block other agent tools.

Release scope: code supports optional owner-scoped imports and explicit missing-data behavior. Broader broker-file mapping, persisted-import management/deletion UI, authenticated ledger acquisition, adjusted-price feeds and complete-account risk acceptance remain separate unfinished features. Do not market this as complete broker reconciliation or production-verified whole-account advice.
