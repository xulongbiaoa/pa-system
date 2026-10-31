"""模型适配器契约（设计 v2.2 T06 / §7 / §14.2）。

统一入口只有两个：plan_scene（画地图）与 assess_behavior（行为
复核）。输入是不可变快照引用（snapshot_id、chart_hash、策略版本、
机会 revision），输出必须回显这些字段并通过一致性校验：

- 回显不一致 / 字段缺失 → ModelContractError（MODEL_SCHEMA_INVALID）；
- revision 与当前机会不符 → StaleAssessment（STALE_ASSESSMENT，
  迟到响应不得覆盖新状态，机会层只落审计）；
- 适配器不可用 / 无录制 → ModelUnavailable（MODEL_UNAVAILABLE）。

这些都是任务层系统结果，绝不记成策略 no_trade，也不走
DecisionResult 的状态枚举（service.py）。

本模块不绑定任何供应商 SDK：RecordedAdapter 用已记录的模型输出
做回归回放（同输入同输出只约束确定性部分）；CallableAdapter 包
任意可调用对象（真实 API 或子代理桥接在接入时注入）。SDK 只许
出现在具体适配器实现里，不进 perception/gate。
"""

import copy
from dataclasses import dataclass


class ModelContractError(Exception):
    code = "MODEL_SCHEMA_INVALID"


class StaleAssessment(Exception):
    code = "STALE_ASSESSMENT"


class ModelUnavailable(Exception):
    code = "MODEL_UNAVAILABLE"


@dataclass(frozen=True)
class PlanningInput:
    snapshot_id: str
    chart_hash: str
    strategy_version: str
    payload: dict


@dataclass(frozen=True)
class BehaviorInput:
    snapshot_id: str
    chart_hash: str
    strategy_version: str
    opportunity_id: str
    revision: int
    payload: dict


def scene_request_key(inp):
    return f"scene:{inp.snapshot_id}:{inp.strategy_version}"


def behavior_request_key(inp):
    return f"behavior:{inp.opportunity_id}:{inp.revision}:{inp.snapshot_id}"


def _check_echo(out, expected, kind):
    if not isinstance(out, dict):
        raise ModelContractError(f"{kind} 输出不是对象：{type(out).__name__}")
    for k, v in expected.items():
        if out.get(k) != v:
            if k == "revision":
                raise StaleAssessment(
                    f"{kind} 回显 revision={out.get(k)!r} ≠ 当前 {v!r}")
            raise ModelContractError(
                f"{kind} 回显 {k}={out.get(k)!r} ≠ 输入 {v!r}")


def validate_scene_output(out, inp):
    _check_echo(out, {"snapshot_id": inp.snapshot_id,
                      "chart_hash": inp.chart_hash,
                      "strategy_version": inp.strategy_version}, "SceneMap")
    return out


def validate_behavior_output(out, inp):
    _check_echo(out, {"snapshot_id": inp.snapshot_id,
                      "chart_hash": inp.chart_hash,
                      "strategy_version": inp.strategy_version,
                      "opportunity_id": inp.opportunity_id,
                      "revision": inp.revision}, "BehaviorAssessment")
    return out


class RecordedAdapter:
    """录制回放：recordings = {request_key: output_dict}。

    返回深拷贝，调用方改输出不污染录制；无录制抛 ModelUnavailable
    （任务失败，不是策略空仓）。
    """

    def __init__(self, recordings):
        self.recordings = recordings or {}

    def plan_scene(self, inp):
        key = scene_request_key(inp)
        if key not in self.recordings:
            raise ModelUnavailable(f"无录制：{key}")
        return validate_scene_output(copy.deepcopy(self.recordings[key]), inp)

    def assess_behavior(self, inp):
        key = behavior_request_key(inp)
        if key not in self.recordings:
            raise ModelUnavailable(f"无录制：{key}")
        return validate_behavior_output(
            copy.deepcopy(self.recordings[key]), inp)


class CallableAdapter:
    """包两个可调用对象（真实 API / 子代理桥接在接入时注入）。"""

    def __init__(self, plan_scene_fn, assess_behavior_fn):
        self._plan = plan_scene_fn
        self._assess = assess_behavior_fn

    def plan_scene(self, inp):
        return validate_scene_output(self._plan(inp), inp)

    def assess_behavior(self, inp):
        return validate_behavior_output(self._assess(inp), inp)
