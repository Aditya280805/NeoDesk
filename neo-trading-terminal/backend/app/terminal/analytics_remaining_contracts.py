"""Private normalized interface between source capture and pure risk evaluation."""
from datetime import date
from typing import Literal
from pydantic import BaseModel,ConfigDict,AwareDatetime,Field,model_validator,field_validator
from .analytics_inputs import DeclaredRiskPosition,DeclaredComplianceRule


class SourceStamp(BaseModel):
    model_config = ConfigDict(frozen=True,extra='forbid')
    source: str = Field(min_length=1,max_length=1000)
    revision: str = Field(min_length=1,max_length=100)
    observed_at: AwareDatetime
    effective_from: date | None = None
    effective_until: date | None = None
    checksum: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def dates(self):
        if self.effective_from and self.effective_until and self.effective_from>self.effective_until:
            raise ValueError('Inverted source effective dates')
        return self


class CapturedRiskBundle(BaseModel):
    model_config = ConfigDict(frozen=True,extra='forbid')
    owner_id: int = Field(strict=True,gt=0)
    session_generation: str = Field(min_length=1,max_length=200)
    as_of: AwareDatetime
    positions: tuple[dict,...] = Field(max_length=100)
    rules: tuple[dict,...] = Field(max_length=100)
    fee_schedule: dict | None = None
    account_coverage: Literal['complete','partial','unavailable']
    missing_inputs: tuple[str,...]
    sources: tuple[SourceStamp,...]

    @field_validator('positions')
    @classmethod
    def normalized_positions(cls,values):
        return tuple(DeclaredRiskPosition.model_validate(value).model_dump(mode='json') for value in values)

    @field_validator('rules')
    @classmethod
    def normalized_rules(cls,values):
        return tuple(DeclaredComplianceRule.model_validate(value).model_dump(mode='json') for value in values)

    @model_validator(mode='after')
    def coverage_and_identity(self):
        ids = [value['contract_id'] for value in self.positions]
        if len(ids)!=len(set(ids)) or len({value['contract_id'] for value in self.rules})!=len(self.rules):
            raise ValueError('Duplicate captured contract')
        if any(value['contract_id'] not in ids for value in self.rules):
            raise ValueError('Rule references uncaptured contract')
        if self.account_coverage=='complete' and (self.missing_inputs or not self.sources):
            raise ValueError('Complete coverage requires sources and no missing inputs')
        if any(source.observed_at>self.as_of for source in self.sources):
            raise ValueError('Source observation follows capture')
        return self
