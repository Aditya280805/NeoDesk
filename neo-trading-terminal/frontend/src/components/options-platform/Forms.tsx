import { FormEvent, ReactNode, useState } from 'react'
import { object, rows, text } from '@/lib/optionsPlatform'

export type Fields = Record<string, string>
export type FieldSpec = { key: string; label: string; options?: { value: string; label: string }[]; optional?: boolean; multiline?: boolean; hint?: string }
export function InputFields({ specs, values, onChange }: { specs: FieldSpec[]; values: Fields; onChange: (values: Fields) => void }) {
  return <div className="op-fields">{specs.map(f => <label key={f.key}>{f.label}{f.optional && ' (optional)'}
    {f.options ? <select value={values[f.key] ?? ''} onChange={e => onChange({ ...values, [f.key]: e.target.value })} required={!f.optional}><option value="">Select…</option>{f.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
      : f.multiline ? <textarea value={values[f.key] ?? ''} onChange={e => onChange({ ...values, [f.key]: e.target.value })} required={!f.optional} rows={5} />
        : <input value={values[f.key] ?? ''} onChange={e => onChange({ ...values, [f.key]: e.target.value })} required={!f.optional} />}
    {f.hint && <small>{f.hint}</small>}</label>)}</div>
}
export function ActionForm({ title, children, onSubmit, action, disabled }: { title: string; children: ReactNode; onSubmit: () => void; action: string; disabled?: boolean }) {
  return <form className="op-panel" onSubmit={(e: FormEvent) => { e.preventDefault(); onSubmit() }}><h2>{title}</h2>{children}<button disabled={disabled} type="submit">{action}</button></form>
}
/** Recursive evidence view keeps null distinct from zero and displays all scalar provenance. */
export function Evidence({ value, name = 'Evidence' }: { value: unknown; name?: string }) {
  const [page, setPage] = useState(0)
  if (value == null || typeof value !== 'object') return <span>{text(value)}</span>
  if (Array.isArray(value)) { const offset = Math.min(page * 20, Math.max(0, Math.ceil(value.length / 20) - 1) * 20); return <div>{value.length === 0 ? <p>No records.</p> : value.slice(offset, offset + 20).map((v, i) => <details key={offset + i}><summary>{name} {offset + i + 1}</summary><Evidence value={v} /></details>)}{value.length > 20 && <nav aria-label={`${name} result pages`}><button type="button" disabled={!offset} onClick={() => setPage(Math.max(0, page - 1))}>Previous {name} results</button><span>{offset + 1}–{Math.min(offset + 20, value.length)} of {value.length}</span><button type="button" disabled={offset + 20 >= value.length} onClick={() => setPage(page + 1)}>Next {name} results</button></nav>}</div> }
  return <dl className="op-evidence">{Object.entries(object(value)).map(([key, v]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{v && typeof v === 'object' ? <details><summary>{key.replaceAll('_', ' ')} {Array.isArray(v) ? `(${rows(v).length})` : 'details'}</summary><Evidence value={v} name={key} /></details> : text(v)}</dd></div>)}</dl>
}
export const choices = (...values: string[]) => values.map(value => ({ value, label: value.replaceAll('_', ' ') }))
