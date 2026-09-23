"""Unit tests for the synthetic traffic generator (scripts/traffic_lib.py)."""

from __future__ import annotations

import random

from scripts.traffic_lib import (
    _PROFILE_WEIGHTS,
    generate_batch,
    random_submit_body,
    run_traffic,
)

_REQUIRED_KEYS = {"process", "case_id", "request"}


def test_random_submit_body_shape() -> None:
    rng = random.Random(1)
    body = random_submit_body(rng, seq=0)
    assert _REQUIRED_KEYS <= body.keys()
    assert body["process"] in {"procurement_review", "onboarding_kyc"}
    assert body["case_id"].startswith("sim-00000-")
    assert "vendor_id" in body["request"]
    assert "amount" in body["request"]


def test_generate_batch_is_deterministic_for_a_seed() -> None:
    a = generate_batch(20, seed=99)
    b = generate_batch(20, seed=99)
    assert [x["case_id"] for x in a] == [x["case_id"] for x in b]


def test_generate_batch_case_ids_are_unique() -> None:
    batch = generate_batch(50, seed=5)
    ids = [b["case_id"] for b in batch]
    assert len(ids) == len(set(ids))


def test_generate_batch_covers_every_profile_at_reasonable_size() -> None:
    batch = generate_batch(200, seed=3)
    seen = {b["case_id"].split("-", 2)[2].rsplit("-", 1)[0] for b in batch}
    # Every profile the generator can pick should show up over 200 draws.
    assert set(_PROFILE_WEIGHTS) <= seen


def test_injection_profile_forces_the_planted_chunk() -> None:
    rng = random.Random(0)
    bodies = [random_submit_body(rng, seq=i) for i in range(300)]
    injected = [b for b in bodies if "injection_attempt" in b["case_id"]]
    assert injected, "expected at least one injection_attempt draw over 300 samples"
    for body in injected:
        assert body.get("force_chunk_ids") == ["chunk:injected:quote"]


def test_unauthorized_profile_uses_a_disallowed_tool() -> None:
    rng = random.Random(2)
    bodies = [random_submit_body(rng, seq=i) for i in range(300)]
    unauthorized = [b for b in bodies if "unauthorized_tool" in b["case_id"]]
    assert unauthorized
    for body in unauthorized:
        tool = body["mock_agent_plan"]["tool_name"]
        assert tool in {"send_payment", "modify_vendor_banking_details"}


def test_run_traffic_calls_submit_fn_and_reports_results() -> None:
    calls: list[dict] = []

    def fake_submit(body: dict) -> dict:
        calls.append(body)
        return {"ok": True, "case_id": body["case_id"]}

    results = run_traffic(
        rate_per_sec=0,  # no sleep between calls — keep the test fast
        duration_sec=0.05,
        submit_fn=fake_submit,
        seed=1,
    )
    assert len(calls) == len(results)
    assert len(results) >= 1
    assert all(r.get("ok") for r in results)


def test_run_traffic_keeps_going_after_a_submit_error() -> None:
    def flaky_submit(body: dict) -> dict:
        if "clean" in body["case_id"]:
            raise RuntimeError("boom")
        return {"ok": True}

    results = run_traffic(
        rate_per_sec=0,
        duration_sec=0.05,
        submit_fn=flaky_submit,
        seed=1,
    )
    assert any(isinstance(r, Exception) for r in results)
    assert any(isinstance(r, dict) and r.get("ok") for r in results)
