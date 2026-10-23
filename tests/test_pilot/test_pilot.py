"""Tests for the I0 spike (pilot/). Run with: uv run pytest tests/test_pilot -q

They use the deterministic `stub` quarantined LLM, so they need no model or network.
"""

import pytest

import pilot  # noqa: F401  (must come first: fixes an AgentDojo circular import)
from camel.interpreter.interpreter import MetadataEvalMode
from camel.pipeline_elements.security_policies.banking import banking_no_side_effect_tools
from camel.security_policy import NoSecurityPolicyEngine
from pilot.oracle import _cell, build_run, control_change_rate, evaluate_plan, interpret, run_plan, summarise_slots
from pilot.plans import P2_RENT_FLIP, P3_ADDRESS_THEN_RENT, PLANS

READ_ONLY = set(banking_no_side_effect_tools)
MODES = (MetadataEvalMode.NORMAL, MetadataEvalMode.STRICT)


def _slots(plan, mode):
    cells, _ = evaluate_plan(plan, mode, "stub", repeats=2, read_only=READ_ONLY)
    return {(s.tool, s.target): s for s in summarise_slots(cells)}


def test_cell_rule():
    assert _cell(untrusted=True, changed=True) == "TP"
    assert _cell(untrusted=True, changed=False) == "FP"
    assert _cell(untrusted=False, changed=True) == "FN"
    assert _cell(untrusted=False, changed=False) == "TN"


@pytest.mark.parametrize("plan", PLANS, ids=lambda p: p.id)
@pytest.mark.parametrize("mode", MODES, ids=str)
def test_observe_mode_does_not_change_behaviour(plan, mode):
    """Differential test: the logger in observe mode must leave the environment exactly as
    a run with no policy at all would. Otherwise the oracle would be measuring the logger."""
    logged = run_plan(plan, mode, "stub")
    env, namespace, _ = build_run(None, "stub")
    plain_error = interpret(plan, namespace, NoSecurityPolicyEngine(), mode)
    assert logged.error == plain_error
    assert logged.env == env


@pytest.mark.parametrize("plan", PLANS, ids=lambda p: p.id)
def test_every_edit_changes_the_environment(plan):
    base, _, _ = build_run(None, "stub")
    for edit in plan.edits:
        edited, _, _ = build_run(edit, "stub")
        assert edited.filesystem != base.filesystem, edit.name
        assert edited.bank_account == base.bank_account, edit.name  # edits touch untrusted files only


@pytest.mark.parametrize("plan", PLANS, ids=lambda p: p.id)
@pytest.mark.parametrize("mode", MODES, ids=str)
def test_unedited_replays_agree(plan, mode):
    runs = [run_plan(plan, mode, "stub") for _ in range(3)]
    assert control_change_rate(runs, READ_ONLY) == 0.0


def test_enforce_mode_returns_the_real_decision():
    """With observe=False the wrapped Banking policy blocks the untrusted address update."""
    run = run_plan(P3_ADDRESS_THEN_RENT, MetadataEvalMode.NORMAL, "stub", observe=False)
    assert run.error is not None and "SecurityPolicyDeniedError" in run.error
    fresh, _, _ = build_run(None, "stub")
    assert run.env.user_account == fresh.user_account  # the address was not changed


def test_branch_flip_is_missed_in_normal_and_caught_in_strict():
    """The slide 5 case: the rent amount is set inside an if-branch on untrusted data."""
    normal = _slots(P2_RENT_FLIP, MetadataEvalMode.NORMAL)
    strict = _slots(P2_RENT_FLIP, MetadataEvalMode.STRICT)
    assert normal[("update_scheduled_transaction", "amount")].cell == "FN"
    assert strict[("update_scheduled_transaction", "amount")].cell == "TP"


def test_strict_over_labels_an_unrelated_constant():
    normal = _slots(P3_ADDRESS_THEN_RENT, MetadataEvalMode.NORMAL)
    strict = _slots(P3_ADDRESS_THEN_RENT, MetadataEvalMode.STRICT)
    assert normal[("update_scheduled_transaction", "amount")].cell == "TN"
    assert strict[("update_scheduled_transaction", "amount")].cell == "FP"
    for mode_slots in (normal, strict):
        assert mode_slots[("update_user_info", "street")].cell == "TP"
        assert mode_slots[("update_user_info", "city")].cell == "TP"


def test_real_quarantined_llm_path_runs_offline():
    """The non-stub back end goes through CaMeL's own query_quarantined_llm. pydantic-ai's
    offline `test` model checks that wiring without a server; it answers with dummy data,
    so the plan may stop with CaMeL's NotEnoughInformationError, but must not crash."""
    run = run_plan(P2_RENT_FLIP, MetadataEvalMode.NORMAL, "test")
    assert run.error is None or run.error.startswith("NotEnoughInformationError")
    assert run.records[0].tool == "read_file"
