import pytest
from pydantic import BaseModel
from app.terminal.bound_chain_answer import bind_chain_answer

class Answer(BaseModel):
    answer:str
    snapshot_ids:list[str]

def test_generated_citations_only_accept_exact_captured_snapshot():
    schema=bind_chain_answer(Answer,{'snapshot_id':'captured'})
    assert schema(answer='Summary',snapshot_ids=['captured']).snapshot_ids==['captured']
    for ids in ([],['wrong'],['captured','captured']):
        with pytest.raises(ValueError): schema(answer='Summary',snapshot_ids=ids)
    assert Answer(answer='legacy',snapshot_ids=['legacy']).snapshot_ids==['legacy']
