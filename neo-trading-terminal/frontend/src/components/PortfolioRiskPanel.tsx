import { RiskReport, olderPolicy, reportLabel } from '@/lib/portfolioRisk'

const label = (text: string) => text.replaceAll('_', ' ')

type Props = {
  report?: RiskReport
  currentRevision?: number
  stale?: boolean
}

function RiskFindingDetails({ finding }: { finding: RiskReport['findings'][number] }) {
  const hasRatioInputs = finding.numerator !== null || finding.denominator !== null
  return (
    <article>
      <h4>{label(finding.code)} · {finding.enabled ? label(finding.outcome) : 'Disabled'}</h4>
      <p>Observed: {finding.measured ?? 'Unavailable'} {finding.unit} · Limit: {finding.limit ?? 'Unset'} {finding.unit}</p>
      {hasRatioInputs && (
        <p>Ratio inputs: {finding.numerator ?? 'Unavailable'} / {finding.denominator ?? 'Unavailable'} (displayed ratio may be rounded)</p>
      )}
      <p>{finding.reason_codes.map(label).join(' · ')}</p>
      <p>Affected rows: {finding.affected_row_ids.join(', ') || 'None reported'}</p>
    </article>
  )
}

export default function PortfolioRiskPanel({ report, currentRevision, stale = false }: Props) {
  if (!report) {
    return (
      <section className="portfolio-risk">
        <h3>Risk assessment</h3>
        <p>No risk report in this historical evidence.</p>
      </section>
    )
  }

  const usesOlderPolicy = olderPolicy(report, currentRevision)
  return (
    <section className="portfolio-risk" aria-label="Portfolio risk assessment">
      <h3>Risk assessment · {reportLabel(report)}</h3>
      {stale && <p role="status">Stale evidence · refresh failed. Previous report retained.</p>}
      <p>
        Evaluated policy revision {report.policy_revision}
        {usesOlderPolicy && (
          <strong> · Evaluated with an older policy; saved revision {currentRevision} applies to the next eligible refresh.</strong>
        )}
        <br />Evaluated {report.evaluated_at}
        <br />Report {report.report_id} · {report.calculation_version}
      </p>
      <p>Coverage: {report.coverage.passed} passed · {report.coverage.breached} breached · {report.coverage.cannot_assess} cannot assess · {report.coverage.disabled} disabled</p>
      {report.findings.map(finding => <RiskFindingDetails key={finding.code} finding={finding} />)}
      <details>
        <summary>Observation times and limitations</summary>
        {Object.entries(report.observation_times).map(([name, time]) => (
          <p key={name}>{name}: retrieval {time.retrieval_started_at ?? 'Unavailable'} → {time.retrieval_finished_at ?? 'Unavailable'} · source {time.source_timestamp ?? 'Unavailable'}</p>
        ))}
        <ul>{report.limitations.map((text, index) => <li key={index}>{text}</li>)}</ul>
      </details>
    </section>
  )
}
