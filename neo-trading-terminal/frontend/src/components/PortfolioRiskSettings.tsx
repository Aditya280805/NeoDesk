import { FormEvent, useEffect, useRef, useState } from 'react'
import { apiBase, failure } from '@/lib/api'
import { PolicyResponse, RiskPolicySettings, optionalDecimal, policyConflict } from '@/lib/portfolioRisk'

class PolicyError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function requestPolicy(isCurrent: () => boolean, method = 'GET', body?: unknown): Promise<PolicyResponse> {
  const response = await fetch(`${apiBase()}/api/options-agent/portfolio/risk-policy`, {
    method,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-NeoDesk': '1' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(120000),
  })
  const data = await response.json()
  if (!response.ok) {
    if (response.status === 401 && isCurrent()) {
      window.dispatchEvent(new Event('neodesk:session-expired'))
    }
    const message = typeof data.detail === 'string'
      ? data.detail
      : `Policy request failed (${response.status}). Please retry.`
    throw new PolicyError(response.status, message)
  }
  return data
}

function settingsForSave(draft: RiskPolicySettings): RiskPolicySettings {
  const { revision: ignored, ...settings } = draft as RiskPolicySettings & { revision?: number }
  void ignored
  for (const key of ['concentration_max_percent', 'margin_max_percent', 'loss_max_amount'] as const) {
    settings[key] = optionalDecimal(settings[key] ?? '')
  }
  return settings
}

export default function PortfolioRiskSettings({ onRevision }: { onRevision: (revision: number) => void }) {
  const [saved, setSaved] = useState<PolicyResponse | null>(null)
  const [draft, setDraft] = useState<RiskPolicySettings | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(false)
  const [notice, setNotice] = useState('')
  const generation = useRef(0)

  useEffect(() => {
    const current = ++generation.current
    const invalidate = () => { generation.current++ }
    requestPolicy(() => current === generation.current)
      .then(result => {
        if (current === generation.current) {
          setSaved(result)
          setDraft(result.policy)
          onRevision(result.policy.revision)
        }
      })
      .catch(e => {
        if (current === generation.current) setError(failure(e))
      })
    const expired = () => {
      invalidate()
      setSaved(null)
      setDraft(null)
    }
    window.addEventListener('neodesk:session-expired', expired)
    return () => {
      invalidate()
      window.removeEventListener('neodesk:session-expired', expired)
    }
  }, [onRevision])

  async function reload() {
    const current = generation.current
    setBusy(true)
    try {
      const result = await requestPolicy(() => current === generation.current)
      if (current !== generation.current) return
      setSaved(result)
      setDraft(result.policy)
      setConflict(false)
      setError('')
      setNotice('Latest policy loaded. Review before saving.')
      onRevision(result.policy.revision)
    } catch (e) {
      if (current === generation.current) setError(failure(e))
    } finally {
      if (current === generation.current) setBusy(false)
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault()
    if (!draft || !saved || conflict) return
    const current = generation.current
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await requestPolicy(() => current === generation.current, 'PUT', {
        expected_revision: saved.policy.revision,
        policy: settingsForSave(draft),
      })
      if (current !== generation.current) return
      setSaved(result)
      setDraft(result.policy)
      setNotice(`Saved revision ${result.policy.revision}. Applies to the next eligible refresh.`)
      onRevision(result.policy.revision)
    } catch (e) {
      if (current !== generation.current) return
      if (e instanceof PolicyError && e.status === 409) {
        setConflict(policyConflict({}).conflict)
        setError('Policy changed elsewhere. Your unsaved edits are retained. Explicitly reload the latest policy to review before saving.')
      } else {
        setError(failure(e))
      }
    } finally {
      if (current === generation.current) setBusy(false)
    }
  }

  function decimal(key: 'concentration_max_percent' | 'margin_max_percent' | 'loss_max_amount', value: string) {
    setNotice('')
    setDraft(current => current ? {
      ...current,
      [key]: value === '' ? null : value,
      ...(key === 'loss_max_amount' ? {
        loss_basis: value === '' ? null : 'broker_account_net_pnl',
        loss_period: value === '' ? null : 'broker_trading_day',
      } : {}),
    } : current)
    try {
      optionalDecimal(value)
      setError('')
    } catch (e) {
      setError(failure(e))
    }
  }
  if (!draft || !saved) {
    return (
      <section className="panel portfolio-risk-settings" aria-label="Portfolio risk policy">
        <h2>Portfolio risk policy</h2>
        <p>Choose your own limits. Blank means unset; zero is an explicit limit. No recommended limits.</p>
        <p role="status">{error || 'Loading policy…'}</p>
        <button onClick={() => void reload()}>Retry policy load</button>
      </section>
    )
  }

  return (
    <section className="panel portfolio-risk-settings" aria-label="Portfolio risk policy">
      <h2>Portfolio risk policy</h2>
      <p>Choose your own limits. Blank means unset; zero is an explicit limit. No recommended limits.</p>
      <form onSubmit={save}>
        <p>Saved revision {saved.policy.revision}</p>
        {(['concentration', 'expiry', 'margin', 'loss'] as const).map(check => {
          const decimalKey = check === 'concentration' ? 'concentration_max_percent'
            : check === 'margin' ? 'margin_max_percent' : 'loss_max_amount'
          const unsupported = (check === 'margin' || check === 'loss') && !saved.supported_inputs[check]
          return (
            <fieldset key={check} disabled={busy}>
              <legend>{check}</legend>
              <label>
                <input type="checkbox" checked={draft[`${check}_enabled`]}
                  onChange={e => setDraft({ ...draft, [`${check}_enabled`]: e.target.checked })} />
                Enable {check} check
              </label>
              {check === 'expiry' ? (
                <label>Expiry window (calendar days)
                  <input type="number" min="0" max="365" step="1" value={draft.expiry_window_days ?? ''}
                    onChange={e => setDraft({ ...draft, expiry_window_days: e.target.value === '' ? null : Number(e.target.value) })} />
                </label>
              ) : (
                <label>{check === 'loss' ? 'Maximum loss (INR · broker trading day)' : `${check} maximum (%)`}
                  <input inputMode="decimal" type="text" value={draft[decimalKey] ?? ''}
                    onChange={e => decimal(decimalKey, e.target.value)} />
                </label>
              )}
              {unsupported && (
                <p>Unavailable from this provider: documented {check === 'margin' ? 'account margin' : 'account net P&L basis and period'} inputs are unsupported. Settings do not make this check assessable.</p>
              )}
            </fieldset>
          )
        })}
        <label>Maximum observation age (seconds)
          <input type="number" min="1" max="86400" step="1" disabled={busy}
            value={draft.max_observation_age_seconds ?? ''}
            onChange={e => setDraft({ ...draft, max_observation_age_seconds: e.target.value === '' ? null : Number(e.target.value) })} />
        </label>
        {error && <p role="alert" className="error">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        <div className="toolbar">
          <button type="submit" disabled={busy || conflict}>{busy ? 'Saving…' : 'Save policy'}</button>
          <button type="button" disabled={busy} onClick={() => {
            setDraft(saved.policy)
            setError('')
            setNotice('Edits cancelled.')
          }}>Cancel edits</button>
          {conflict && (
            <button type="button" disabled={busy} onClick={() => void reload()}>Reload latest policy for review</button>
          )}
        </div>
      </form>
    </section>
  )
}
