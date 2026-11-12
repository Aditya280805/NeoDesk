"""Request-local model choices bound to immutable consumed evidence."""
import math
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from pydantic import Field,create_model

from .analytics_contracts import Contract
from .analytics_stage import EvidenceClaim,SpecialistNarrative


@dataclass(frozen=True)
class EvidenceChoices:
    schema: type
    claims: dict
    proposals: dict
    payload: dict

    def resolve(self,content):
        selected=self.schema.model_validate_json(content) if isinstance(content,str) else self.schema.model_validate(content)
        if len(set(selected.claim_refs))!=len(selected.claim_refs):
            raise ValueError('Duplicate evidence choices')
        return SpecialistNarrative(interpretation=selected.interpretation,
            claims=tuple(self.claims[ref] for ref in selected.claim_refs),
            selected_proposal_id=self.proposals[selected.selected_proposal_ref] if selected.selected_proposal_ref is not None else None)


def bind_choices(evidence):
    claims,proposals,claim_payload,proposal_payload={},{},{},{}
    for name,item in evidence.items():
        queue=deque([((),item.metrics)])
        scanned,count=0,0
        while queue and count<32 and scanned<4096:
            path,value=queue.popleft()
            scanned+=1
            if isinstance(value,(dict,list,tuple)):
                if len(path)>=8:
                    continue
                children=((key,value[key]) for key in sorted(value,key=str) if isinstance(key,str)) if isinstance(value,dict) else enumerate(value)
                for key,child in children:
                    if len(queue)>=512:
                        break
                    queue.append(((*path,key),child))
            elif path and isinstance(value,(str,int,float,bool,type(None))) and not (isinstance(value,float) and not math.isfinite(value)):
                ref=f'c{len(claims)}'
                claims[ref]=EvidenceClaim(evidence_id=item.evidence_id,path=path)
                claim_payload[ref]=dict(tool=name,path=list(path),value=value)
                count+=1
        for index,proposal in enumerate(item.candidate_proposals):
            if len(proposals)>=16:
                break
            if proposal.proposal_id in proposals.values():
                continue
            ref=f'p{len(proposals)}'
            proposals[ref]=proposal.proposal_id
            proposal_payload[ref]=dict(tool=name,candidate_index=index,template=proposal.template)
    claim_type=Literal[tuple(claims)] if claims else type(None)
    proposal_type=Literal[tuple(proposals)] if proposals else type(None)
    schema=create_model('EvidenceSelection',__base__=Contract,
        interpretation=(str,deepcopy(SpecialistNarrative.model_fields['interpretation'])),
        claim_refs=(tuple[claim_type,...],Field(default=(),max_length=min(4,len(claims)))),
        selected_proposal_ref=(proposal_type|None,None))
    return EvidenceChoices(schema,claims,proposals,dict(claim_choices=claim_payload,proposal_choices=proposal_payload))
