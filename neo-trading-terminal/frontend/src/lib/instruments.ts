type NamedInstrument={symbol:string;name?:string;display_name?:string;exchange?:string;kind?:string}
const abbreviations=new Set('HDFC ICICI ITC TCS NTPC SBI LIC ONGC BSE NSE ETF IDFC MRF TVS PNB RBL PFC IRFC HUDCO IRCTC IEX JSW NBCC NHPC SAIL HAL BEL BHEL ABB SKF SJVN CDSL MCX NMDC NCD SR IX'.split(' '))
const starterNames:Record<string,string>={HDFCBANK:'HDFC Bank',RELIANCE:'Reliance Industries',INFY:'Infosys',TCS:'Tata Consultancy Services',SBIN:'State Bank of India',NIFTY:'Nifty 50',BANKNIFTY:'Nifty Bank'}

export function shortSymbol(item:NamedInstrument){return item.symbol.replace(/-(EQ|BE|BZ|SM|ST)$/,'')}
export function companyName(item:NamedInstrument){
  const raw=(item.display_name||item.name||'').trim()
  const symbolName=starterNames[shortSymbol(item).toUpperCase()]
  if(!raw||raw===item.symbol)return symbolName||shortSymbol(item)
  // Prefer the catalogue's name, while removing legal suffixes that make lists noisy.
  const cleaned=raw.replace(/[.,]+$/,'').replace(/\s+(?:LTD|LIMITED|PVT|PRIVATE|PLC|INC|CORP|CORPORATION|COMPANY)$/i,'').trim()
  if(raw!==raw.toUpperCase())return symbolName||cleaned
  const titled=cleaned.split(/\s+/).map(word=>abbreviations.has(word)||word.includes('&')?word:word.charAt(0)+word.slice(1).toLowerCase()).join(' ')
  return symbolName||titled
}
export function exchangeName(value:string){return ({nse_cm:'NSE',bse_cm:'BSE',nse_fo:'NSE F&O',bse_fo:'BSE F&O'} as Record<string,string>)[value]||value.toUpperCase()}
export function kindName(value:string){return ({EQUITY:'Share',ETF:'ETF',INDEX:'Index',OPTION:'Option',FUTURE:'Future',OTHER:'Other'} as Record<string,string>)[value]||value}
export function companyInitials(item:NamedInstrument){return companyName(item).split(/\s+/).slice(0,2).map(s=>s[0]).join('').toUpperCase()}
