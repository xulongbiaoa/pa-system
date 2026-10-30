"""接线审计：防「规则写了、测了、没接上数据」复发。

两条不变量：
1. adjudicate 消费的每个 flags 键，要么有生产者（gate/flags.build_flags
   能产出），要么登记在 PENDING 里写明未接原因——不许静默缺席。
2. 每个生产调用点（pa_cli / gold_run / pilot_run）源码里必须真的调用
   build_flags 传给 adjudicate——不许再出现「参数在、调用点不传」。
"""
import re
from pathlib import Path

from gate.flags import build_flags

ROOT = Path(__file__).resolve().parents[2]

# 未接线但已登记的键：键 → 原因。判据定版后必须从这里移除并补生产者。
PENDING = {
    "parabolic": "S1 判据（连续根数/实体/总幅倍数）需新常数，无样本与原册依据前不设",
}

CALLERS = ["judge/pa_cli.py", "eval/gold_run.py", "eval/pilot_run.py"]


def _adjudicate_flag_keys():
    src = (ROOT / "gate" / "risk_rules.py").read_text(encoding="utf-8")
    return set(re.findall(r'flags\.get\("(\w+)"\)', src))


def _producible_keys():
    plan = {"entry": 100.0, "stop": 89.0, "second_bar_confirmed": True}
    pack = {"fortress": {"bands": [
        {"lo": 99.0, "hi": 101.0, "trampled": True, "decaying": False},
        {"lo": 90.0, "hi": 92.0, "trampled": False, "decaying": True},
    ]}}
    return set(build_flags(plan, pack).keys())


def test_every_flag_key_produced_or_pending():
    consumed = _adjudicate_flag_keys()
    assert consumed, "审计失效：没从 risk_rules 里解析到 flags 键"
    missing = consumed - _producible_keys() - set(PENDING)
    assert not missing, f"flags 键无生产者且未登记 PENDING: {missing}"
    stale = set(PENDING) - consumed
    assert not stale, f"PENDING 里有 adjudicate 已不消费的键: {stale}"


def test_all_production_callers_wire_build_flags():
    for rel in CALLERS:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "build_flags" in src, f"{rel} 未接 build_flags（flags 又没生产者了）"
        assert "flags=build_flags(plan, pack)" in src, \
            f"{rel} 导入了 build_flags 但没传给 adjudicate"


def test_cli_gate_passes_context_and_ledger():
    """CLI 的 gate 分支必须把 context 与台账一起交给 adjudicate。

    2026-10-30 复核：pa_cli 只 update 了 side/setup，context 缺省 → H6 的
    (setup, 语境) 键永远查不中；台账也没传，H6 在 CLI 路径上从未生效。
    """
    src = (ROOT / "judge" / "pa_cli.py").read_text(encoding="utf-8")
    assert '"context": pack["trend"]["label"]' in src, "pa_cli 没传 context"
    assert "ledger=load_ledger()" in src, "pa_cli 没传台账"


def test_gold_run_passes_ledger():
    src = (ROOT / "eval" / "gold_run.py").read_text(encoding="utf-8")
    assert "ledger=ledger" in src, "gold_run 没传台账"


# ---- 特征包字段接线审计（2026-10-30 扩：MM 未进 pack 是第三例同病）----

REQUIRED_PACK_FIELDS = [
    "last_close", "swings", "legs_major", "trend", "ema", "last_bar",
    "seg_avg_range", "pullback", "gaps", "fortress", "trend_age", "mm",
]

# pack 内已知未产出的子字段：登记原因，产出后必须移除登记。
PENDING_PACK = {}


def _synthetic_pack():
    from perception.features import build_feature_pack, load_config
    bars, price = [], 100.0
    # 锯齿行情：保证 major 摆动与腿都出现
    for leg_dir, n in ((1, 12), (-1, 8), (1, 12), (-1, 8), (1, 10)):
        for _ in range(n):
            o = price
            price += leg_dir * 0.8
            bars.append({"o": o, "h": max(o, price) + 0.2,
                         "l": min(o, price) - 0.2, "c": price})
    return build_feature_pack(bars, [], load_config())


def test_pack_required_fields_present():
    pack = _synthetic_pack()
    missing = [f for f in REQUIRED_PACK_FIELDS if f not in pack]
    assert not missing, f"特征包缺字段（没接线）: {missing}"


def test_pack_mm_candidates_produced():
    pack = _synthetic_pack()
    assert pack["mm"]["candidates"], "有腿却没有 MM 候选投影 = mm_project 又掉线了"
    for c in pack["mm"]["candidates"]:
        assert c["kind"] in ("leg_end_continuation", "pullback_base")
        assert isinstance(c["target"], (int, float))


def test_pack_trend_recent_produced():
    pack = _synthetic_pack()
    recent = pack["trend"].get("recent")
    assert recent is not None and "label" in recent and "window" in recent
