import type { Instrument } from '@/lib/api'
import { companyInitials, companyName, shortSymbol } from '@/lib/instruments'

export default function CompanyLabel({instrument,avatar=true}:{instrument:Instrument;avatar?:boolean}){
  return <span className="company-label">{avatar&&<span className="company-avatar" aria-hidden="true">{companyInitials(instrument)}</span>}<span className="company-copy"><strong>{companyName(instrument)}</strong><small>{shortSymbol(instrument)}</small></span></span>
}
