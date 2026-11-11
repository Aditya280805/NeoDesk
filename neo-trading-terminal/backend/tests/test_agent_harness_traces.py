import json
from app.terminal.agent_harness import RequestHarness


def test_trace_contains_only_budget_metadata():
    h = RequestHarness(auto=True)
    ticket = h.reserve('router', 900, 12)
    h.account(ticket, 4)
    h.read_tool()
    trace = h.trace()
    assert trace['attempts'] == 1 and trace['tool_reads'] == 1
    assert trace['stages']['router']['reported_output'] == 4
    assert trace['token_estimate_method'] == 'utf8-bytes-divided-by-3'
    assert not any(name in json.dumps(trace) for name in ('prompt', 'answer', 'credential', 'capability', 'account_rows'))


def test_unknown_usage_is_distinguished_from_reported_usage():
    h = RequestHarness()
    h.account(h.reserve('specialist', 900, 1), None)
    stage = h.trace()['stages']['specialist']
    assert stage['unknown_usage'] == 1
    assert stage['reported_output'] == 0
    assert stage['generation_spent'] == 900
