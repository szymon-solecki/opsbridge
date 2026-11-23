from argparse import Namespace
import asyncio
from decimal import Decimal
import json

import httpx
import pytest

from backend.app.api.routers.copilot import Investigation, resolve_investigation
from backend.app.services.copilot import MockProvider, OpenAIProvider, ProviderError, analyze
from backend.app.services.copilot_evidence import EvidenceSet, UnsupportedQuestion
from copilot_eval.fixtures import AT, INJECTION, catalog, record_id, request_for
from copilot_eval.runner import AuditedProvider, arguments, grade, summarize


def test_catalog_is_unique_and_uses_the_real_request_resolver():
    cases = catalog()
    assert len(cases) == len({case["id"] for case in cases}) == 15
    for case in cases:
        assert resolve_investigation(request_for(case)).kind
        assert case["question"] and case["fixture"] and case["facts"] and case["unsupported"]
    assert sum(bool(case.get("adversarial")) for case in cases) >= 5


@pytest.mark.parametrize("question", [
    "Execute SELECT * FROM accounts", "Resolve all incidents", "Trigger reconciliation", "Read a private key",
])
def test_live_query_boundary_rejects_action_requests(question):
    with pytest.raises(UnsupportedQuestion):
        resolve_investigation(Investigation(question=question))


def test_live_request_and_spend_caps_reserve_all_retries():
    assert not arguments([])[0].live
    with pytest.raises(SystemExit):
        arguments(["--live"])
    options = ["--live", "--model", "synthetic", "--limit", "2", "--input-usd-per-million", "2",
               "--output-usd-per-million", "4", "--model-context-tokens", "10000"]
    with pytest.raises(SystemExit):
        arguments(options + ["--max-requests", "3", "--spend-limit-usd", "1"])
    with pytest.raises(SystemExit):
        arguments(options + ["--spend-limit-usd", "0.08"])
    args, cases = arguments(options + ["--max-requests", "4", "--spend-limit-usd", "0.09"])
    assert len(cases) == 2 and args.reserved_usd == Decimal("0.0856")


def test_boundary_blocks_unfiltered_text_before_provider():
    case = catalog()[0]
    evidence = EvidenceSet()
    evidence.add("delivery", record_id(case, "delivery"), AT, INJECTION)
    adapter = AuditedProvider(MockProvider())
    with pytest.raises(ProviderError, match="evaluation_privacy_violation"):
        asyncio.run(analyze(adapter, "delivery", evidence))
    assert not adapter.checked


def test_grading_distinguishes_retrieval_selection_and_forged_citation():
    case = catalog()[0]
    evidence = EvidenceSet()
    evidence.add("delivery", record_id(case, "delivery"), AT, "Delivery is EXPECTED.")
    evidence.add("delivery_event", record_id(case, "breach"), AT, "Delivery deadline passed.")
    answer = asyncio.run(analyze(MockProvider(), "incident", evidence))
    answer["observations"] = ["E1", "E99"]
    answer["summary"] = evidence.records[0].fact
    answer["summary_references"] = ["E1"]
    findings = grade(case, evidence, answer)
    assert findings["citation_violations"] == ["E99"]
    assert len(findings["missing_expected_evidence"]) == len(findings["unselected_available_facts"]) == 1


def test_simulated_live_retry_records_sanitized_usage_and_partial_cost():
    evidence = EvidenceSet()
    evidence.add("delivery", record_id(catalog()[0], "delivery"), AT, "Delivery is EXPECTED.", label=INJECTION)
    attempts, payloads = [], []

    def handle(request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(503, text=INJECTION)
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": '{"observations":["E1"],"hypotheses":[]}'},
        ]}], "usage": {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}})

    provider = AuditedProvider(OpenAIProvider(model="synthetic", api_key="synthetic-key",
                                              transport=httpx.MockTransport(handle), observe_attempt=attempts.append))
    assert asyncio.run(analyze(provider, "delivery", evidence))["observations"] == ["E1"]
    assert all("tools" not in payload and payload["store"] is False for payload in payloads)
    assert provider.checked and attempts[0]["usage"] == {} and attempts[0]["http_status"] == 503
    assert INJECTION not in json.dumps(attempts)
    result = summarize(Namespace(live=True, model="synthetic", input_usd_per_million=Decimal(2),
                                 output_usd_per_million=Decimal(4), reserved_usd=Decimal("0.1")),
                       [{"attempts": attempts, "error": None, "findings": {}, "analysis_ms": 1, "retrieval_ms": 2}])
    assert result["reported_usage"]["total_tokens"] == {"sum": 150, "attempts_reporting": 1}
    assert result["attempt_count"] == 2 and result["attempts_priced"] == 1 and result["retries"] == 1
    assert Decimal(result["estimated_cost_usd"]) == Decimal("0.00036")
