"""The research guardrails: pre-registration and the gate checklist."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import hypothesis_registry as reg
from core.research_gates import GateReport


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "REGISTRY", str(tmp_path / "hypothesis_registry.jsonl"))
    return reg


def test_every_registration_raises_the_trial_count(registry):
    """The count feeds the multiple-testing correction: a study that is not
    registered is a trial nobody corrected for."""
    assert registry.trial_count() == 0
    a = registry.register("thesis A", "plan A")
    registry.register("thesis B", "plan B")
    assert registry.trial_count() == 2
    registry.close(a, "REJECTED", "failed its holdout")
    assert registry.trial_count() == 2          # closing never un-counts a trial


def test_a_vague_registration_is_refused(registry):
    with pytest.raises(ValueError):
        registry.register("", "plan")
    with pytest.raises(ValueError):
        registry.register("thesis", "   ")


def test_closing_an_unknown_hypothesis_is_refused(registry):
    with pytest.raises(ValueError):
        registry.close("H-999", "PASS", "made up")


def test_the_ledger_is_append_only(registry):
    hid = registry.register("t", "p")
    registry.close(hid, "REJECTED", "first verdict")
    lines = open(registry.REGISTRY, encoding="utf-8").read().splitlines()
    assert len(lines) == 2 and '"register"' in lines[0] and '"close"' in lines[1]


def test_an_unrun_gate_is_not_a_pass():
    r = GateReport("illustrative thesis")
    r.baseline(strategy_ret=0.004, baseline_ret=0.002)
    assert not r.passed()
    assert "INCOMPLETE" in r.verdict()


def test_a_result_that_flips_sign_inside_the_cost_range_has_no_verdict():
    r = GateReport("illustrative thesis")
    r.cost_sweep({0.06: 0.010, 0.20: 0.002, 0.30: -0.004})
    assert r.failures() and r.failures()[0].name == "5 COST_SWEEP"


def test_beating_zero_is_not_beating_the_baseline():
    r = GateReport("illustrative thesis")
    r.baseline(strategy_ret=0.001, baseline_ret=0.002)
    assert r.failures()[0].name == "1 BASELINE"
