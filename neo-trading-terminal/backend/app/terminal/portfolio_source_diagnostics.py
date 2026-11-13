"""Allowlisted structural diagnostics; never return source values or arbitrary keys."""
FIELDS = frozenset(('exchangeSegment','exchangeIdentifier','displaySymbol','exSeg','tok','trdSym','symbol','token','exchange'))

def kind(value):
    if value is None: return 'none'
    if isinstance(value,dict): return 'object'
    if isinstance(value,list): return 'array'
    return 'scalar'

def source_shape(raw):
    data = raw.get('data') if isinstance(raw,dict) else None
    fields = set()
    if isinstance(data,list):
        for row in data[:10]:
            if isinstance(row,dict): fields.update(FIELDS.intersection(row))
    errors = []
    if isinstance(raw,dict):
        errors = [key for key in ('error','Error','Error Message','fault') if raw.get(key)]
    return dict(envelope_type=kind(raw),data_type=kind(data),
                rows=min(len(data),1001) if isinstance(data,list) else None,
                known_identity_fields=sorted(fields),error_fields=errors)
