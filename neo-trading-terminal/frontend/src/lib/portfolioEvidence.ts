export type PortfolioIssue = { code: string; row_id: string | null; field: string | null }
export type ValueProvenance = { source: 'provider' | 'calculated'; input_paths: string[]; formula_version: string | null; basis: string | null }
type DecimalField = 'strike' | 'lot_size' | 'quantity' | 'available_quantity' | 'buy_quantity' | 'sell_quantity' | 'filled_quantity' | 'pending_quantity' | 'average_price' | 'last_price' | 'order_price' | 'trigger_price' | 'buy_price' | 'sell_price' | 'multiplier' | 'invested_value' | 'market_value' | 'provider_pnl' | 'calculated_pnl' | 'realized_pnl' | 'unrealized_pnl' | 'pnl_percent'
export type PortfolioRow = Record<DecimalField, string | null> & {
  row_id: string; exchange: string | null; token: string | null; symbol: string | null; contract_type: string | null; expiry: string | null
  currency: 'INR' | null; identity_verified: boolean | null; identity_status: 'verified' | 'unresolved' | 'ambiguous' | 'invalid' | null; identity_basis: string | null
  side: 'BUY' | 'SELL' | 'UNKNOWN' | null; status: string | null; order_id: string | null; product: string | null
  provenance: Record<string, ValueProvenance>; issues: PortfolioIssue[]
}
export type PortfolioSection = {
  state: 'available' | 'partial' | 'unavailable' | 'invalid'; rows: PortfolioRow[]; values: Record<string, string | null>
  provenance: Record<string, ValueProvenance>; issues: PortfolioIssue[]; retrieval_started_at: string | null; retrieval_finished_at: string | null
  provider_timestamp: string | null; source_count: number | null
}
export type PortfolioSnapshot = {
  schema_version: 'portfolio.v1'; evidence_id: string; source: string; retrieval_started_at: string; retrieval_finished_at: string; source_observed_at: string
  cache_age_seconds: string | null; atomic: false; exchange_freshness: 'unknown' | 'verified'; exchange_timestamp: string | null
  completeness: 'complete' | 'partial' | 'unavailable' | 'invalid'; sections: Partial<Record<'holdings' | 'positions' | 'orders' | 'funds', PortfolioSection>>
  summary: Record<string, string | null>; limitations: string[]
}
/** Exact decimal display; rounding never passes through binary floating point. */
export function formatDecimal(value: string | null, places?: number): string {
  if (value === null) return 'Unavailable'
  const match = /^([+-]?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/.exec(value)
  if (!match) return 'Unavailable'
  const negative = match[1] === '-'
  let whole = match[2], fraction = match[3] ?? ''
  if (match[4] !== undefined) {
    // The exponent moves a string boundary; evidence digits never become a Number.
    const exponent = Number(match[4])
    const coefficient = whole + fraction
    const boundary = whole.length + exponent
    // Keep valid scientific evidence exact when expanding it would be unsafe or
    // excessively large. Requested precision must not force that expansion.
    const displayLength = boundary <= 0 ? 2 - boundary + coefficient.length : Math.max(boundary, coefficient.length) + 1
    if (!Number.isSafeInteger(exponent) || !Number.isSafeInteger(boundary) || displayLength > 4096) return value
    if (boundary <= 0) { whole = '0'; fraction = '0'.repeat(-boundary) + coefficient }
    else if (boundary >= coefficient.length) { whole = coefficient + '0'.repeat(boundary - coefficient.length); fraction = '' }
    else { whole = coefficient.slice(0, boundary); fraction = coefficient.slice(boundary) }
    whole = whole.replace(/^0+(?=\d)/, '')
  }
  if (places === undefined) return (negative ? '-' : '') + whole + (fraction ? `.${fraction}` : '')
  if (!Number.isInteger(places) || places < 0 || places > 100) return 'Unavailable'
  let digits = whole + fraction.padEnd(places, '0').slice(0, places)
  if (fraction.length > places && fraction[places] >= '5') digits = (BigInt(digits) + BigInt(1)).toString()
  digits = digits.padStart(places + 1, '0')
  return (negative ? '-' : '') + (places ? `${digits.slice(0, -places)}.${digits.slice(-places)}` : digits)
}
