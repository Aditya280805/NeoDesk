import { formatDecimal, PortfolioIssue, PortfolioSnapshot, ValueProvenance } from '@/lib/portfolioEvidence'
const label = (key: string) => key.replaceAll('_', ' ')
const time = (value: string | null) => value ? new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) + ' IST' : 'Unavailable'
function Issues({issues}: {issues: PortfolioIssue[]}) {
  return issues.length ? <ul className="portfolio-evidence-issues">{issues.map((issue, i) => <li key={i}>{label(issue.code)}{issue.field && ` · ${label(issue.field)}`}{issue.row_id && ` · row ${issue.row_id}`}</li>)}</ul> : null
}
function Values({values, provenance}: {values: Record<string, string | null>; provenance: Record<string, ValueProvenance>}) {
  return <dl className="portfolio-evidence-values">{Object.entries(values).map(([key, value]) => <div key={key}><dt>{label(key)} <small>{provenance[key]?.source ?? 'Basis unavailable'}{provenance[key]?.basis && ` · ${provenance[key].basis}`}</small></dt><dd>{formatDecimal(value)}</dd></div>)}</dl>
}
export default function PortfolioEvidence({snapshot}: {snapshot: PortfolioSnapshot}) {
  return <div className="portfolio-evidence">
    <p><b>{snapshot.source} · {snapshot.completeness}</b><br/>Evidence {snapshot.evidence_id}</p>
    <p>Source observed {time(snapshot.source_observed_at)}<br/>Cache age {formatDecimal(snapshot.cache_age_seconds)} seconds<br/>Retrieved {time(snapshot.retrieval_finished_at)}<br/>Exchange freshness: {snapshot.exchange_freshness}{snapshot.exchange_timestamp && ` · ${time(snapshot.exchange_timestamp)}`}<br/>Sections are not an atomic account snapshot.</p>
    {Object.keys(snapshot.summary).length > 0 && <section><h3>Portfolio summaries</h3><Values values={snapshot.summary} provenance={Object.fromEntries(Object.keys(snapshot.summary).map(key => [key, {source: ['invested', 'holdings_value', 'holdings_pnl', 'positions_calculated_pnl'].includes(key) ? 'calculated' : 'provider', input_paths: [], formula_version: null, basis: null}]))}/></section>}
    {(['holdings', 'positions', 'orders', 'funds'] as const).map(name => {
      const section = snapshot.sections[name]
      return <section key={name}><h3>{label(name)} · {section?.state ?? 'unavailable'}</h3>
        {!section ? <p>Section missing. Values unavailable.</p> : <>
          <small>Observed retrieval {time(section.retrieval_finished_at)} · provider time {time(section.provider_timestamp)}</small>
          <Issues issues={section.issues}/>
          {section.state === 'invalid' || section.state === 'unavailable' ? <p>Values unavailable. This section cannot support numerical claims.</p> : <>
            <Values values={section.values} provenance={section.provenance}/>
            {!section.rows.length && name !== 'funds' && <p>Empty section: no rows returned.</p>}
            {section.rows.map(row => <details key={row.row_id}><summary>{row.symbol ?? 'Unidentified row'} · {row.side ?? 'UNKNOWN'} · {row.status ?? row.identity_status ?? 'Identity unavailable'}</summary><Issues issues={row.issues}/>
              <Values values={{quantity: row.quantity, average_price: row.average_price, last_price: row.last_price, market_value: row.market_value, provider_pnl: row.provider_pnl, calculated_pnl: row.calculated_pnl, order_price: row.order_price}} provenance={row.provenance}/>
            </details>)}
          </>}
        </>}
      </section>
    })}
    <details><summary>Data coverage and limitations</summary><ul>{snapshot.limitations.map((text, i) => <li key={i}>{text}</li>)}</ul></details>
  </div>
}
