"""模型适配器契约测试（T06）：回显校验、迟到拒绝、录制回放。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from judge.model_client import (  # noqa: E402
    BehaviorInput, CallableAdapter, ModelContractError, ModelUnavailable,
    PlanningInput, RecordedAdapter, StaleAssessment,
    behavior_request_key, scene_request_key)

PIN = PlanningInput(snapshot_id="s1", chart_hash="h1",
                    strategy_version="v1", payload={})
BIN = BehaviorInput(snapshot_id="s1", chart_hash="h1",
                    strategy_version="v1", opportunity_id="opp1",
                    revision=3, payload={})


def _scene(**over):
    out = {"snapshot_id": "s1", "chart_hash": "h1", "strategy_version": "v1",
           "points": []}
    out.update(over)
    return out


def _behavior(**over):
    out = {"snapshot_id": "s1", "chart_hash": "h1", "strategy_version": "v1",
           "opportunity_id": "opp1", "revision": 3,
           "interpretation": "unresolved"}
    out.update(over)
    return out


def test_recorded_scene_roundtrip_and_copy():
    ad = RecordedAdapter({scene_request_key(PIN): _scene()})
    out = ad.plan_scene(PIN)
    assert out["points"] == []
    out["points"].append({"id": "P1"})
    assert ad.plan_scene(PIN)["points"] == []  # 深拷贝，录制不污染


def test_recorded_missing_is_unavailable_not_no_trade():
    ad = RecordedAdapter({})
    with pytest.raises(ModelUnavailable):
        ad.assess_behavior(BIN)


def test_stale_revision_rejected():
    ad = RecordedAdapter({behavior_request_key(BIN): _behavior(revision=2)})
    with pytest.raises(StaleAssessment):
        ad.assess_behavior(BIN)


def test_echo_mismatch_is_contract_error():
    ad = RecordedAdapter({scene_request_key(PIN): _scene(chart_hash="hX")})
    with pytest.raises(ModelContractError):
        ad.plan_scene(PIN)


def test_callable_adapter_validates_too():
    ad = CallableAdapter(lambda inp: _scene(),
                         lambda inp: _behavior(opportunity_id="oppX"))
    assert ad.plan_scene(PIN)["snapshot_id"] == "s1"
    with pytest.raises(ModelContractError):
        ad.assess_behavior(BIN)
