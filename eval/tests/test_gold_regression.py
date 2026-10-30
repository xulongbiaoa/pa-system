"""金标准回归：30 段冻结集的确定性护栏（纪律见 knowledge/gold/INDEX.md）。

本测试不跑 LLM，只钉死「改代码会不会把已通过的段改坏」这一件事：

1. 冻结集完整性 + 只读性（sha256 清单，重冻结须重算清单）；
2. 每段都取得到 K 线，且决策点（bar 180）后正好 300 根（生命周期口径）；
3. 特征包在 30 段上都能构建、不抛异常、关键字段齐备；
4. 两张冻结候选单在 annotation 口径下必须过裁决（hard 零命中）——
   门槛收紧后最易翻车处，掉一个就是回归；
5. 两张候选单的结局必须与冻结 outcome 一致（R / 出场原因 / 出场根号）。

口径依据：core 红线 4 定版（标注与试点以决策点为「当下」）、生命周期 300 根
到期按第 300 根收盘出场、H1 按首目标计价与回放结算同口径。
"""

import glob
import hashlib
import json
import os

from gate.risk_rules import CONTEXTS, adjudicate
from perception.features import build_feature_pack, load_config
from replay import simulate_trade

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
GOLD = os.path.join(ROOT, "knowledge", "gold")
SPLITS = ("dev", "val", "test")
DECISION = 180
LIFECYCLE = 300

# 基线：任何改动后这三项不得下降
BASELINE = {"segments": 30, "candidates_gate_pass": 2, "outcomes_reproduced": 2}


def _gold_paths():
    return sorted(glob.glob(os.path.join(GOLD, "*.json")))


def _gold():
    return [json.load(open(p)) for p in _gold_paths()]


def _bars(seg_id):
    for split in SPLITS:
        p = os.path.join(ROOT, "eval", "datasets", split, seg_id + ".json")
        if os.path.exists(p):
            return json.load(open(p))["bars"]
    return None


def _pack(bars, cfg):
    """与 pilot_run 同构：先取大级别摆动当锚点，再重建特征包。"""
    p0 = build_feature_pack(bars[:DECISION], [], cfg)
    anchors = [{"price": s["anchor"], "source": "swing-major"}
               for s in p0["swings"]["major"]]
    return build_feature_pack(bars[:DECISION], anchors, cfg)


def _candidates():
    return [g for g in _gold() if g["verdict"] == "candidate"]


def test_gold_set_complete():
    gs = _gold()
    assert len(gs) == BASELINE["segments"], f"冻结集应为 30 段，实为 {len(gs)}"
    for g in gs:
        assert g["verdict"] in ("candidate", "no_trade")
        if g["verdict"] == "candidate":
            assert g["qualified"] and g["setup"] and g["side"]
            assert g["entry"] and g["stop"] and g["targets"]
            assert g["gold"]["outcome"]["r"] is not None
        else:
            assert g["no_trade_reason"], f"{g['segment']} 空仓段缺理由"
        assert g["context"] in CONTEXTS, f"{g['segment']} 语境不在枚举内"


def test_gold_files_unmodified():
    """只读护栏：文件被静默改动则哈希不符（重新冻结时须重算清单）。"""
    man = os.path.join(GOLD, "MANIFEST.sha256")
    assert os.path.exists(man), "缺 MANIFEST.sha256：先跑 eval/tests/gold_manifest.py"
    want = {}
    for line in open(man):
        line = line.strip()
        if line:
            h, name = line.split()
            want[name] = h
    got = {os.path.basename(p): hashlib.sha256(open(p, "rb").read()).hexdigest()
           for p in _gold_paths()}
    assert got == want, "冻结集内容变动：" + ", ".join(
        sorted(k for k in got if got.get(k) != want.get(k))
    )


def test_every_gold_segment_has_300_bars_after_decision():
    for g in _gold():
        bars = _bars(g["segment"])
        assert bars is not None, f"{g['segment']} 找不到 K 线"
        assert len(bars) >= DECISION + LIFECYCLE, (
            f"{g['segment']} 决策点后仅 {len(bars) - DECISION} 根，不足 {LIFECYCLE}"
        )


def test_feature_pack_builds_on_all_gold():
    cfg = load_config()
    for g in _gold():
        pack = _pack(_bars(g["segment"]), cfg)
        for k in ("trend", "ema", "gaps", "swings", "pullback", "seg_avg_range"):
            assert k in pack, f"{g['segment']} 特征包缺 {k}"
        assert pack["trend"]["label"] in CONTEXTS + ("未定",)


def test_frozen_candidates_pass_gate():
    """冻结候选单必须过裁决：门槛改动把已定版的好单拒掉，就是回归。"""
    cfg = load_config()
    cands = _candidates()
    assert len(cands) == BASELINE["candidates_gate_pass"]
    passed = 0
    for g in cands:
        plan = {
            "side": g["side"], "entry": g["entry"], "stop": g["stop"],
            "targets": g["targets"], "risk_frac": 0.01,
            "setup": g["setup"], "context": g["context"],
        }
        r = adjudicate(plan, _pack(_bars(g["segment"]), cfg),
                       bars_left=LIFECYCLE, mode="annotation")
        assert r["verdict"] == "pass", f"{g['segment']} 被误杀：{r['hard_hits']}"
        passed += 1
    assert passed == BASELINE["candidates_gate_pass"]


def test_frozen_outcomes_reproduce():
    """结局复现：回放语义（首目标结算、同根止损优先、300 根到期）不得漂移。"""
    ok = 0
    for g in _candidates():
        bars = _bars(g["segment"])
        t = simulate_trade(bars[DECISION:DECISION + LIFECYCLE], g["side"],
                           g["entry"], g["stop"], g["targets"][0])
        out = g["gold"]["outcome"]
        assert t is not None
        assert abs(t["r"] - out["r"]) < 1e-3, (
            f"{g['segment']} R 漂移：{t['r']:.4f} vs 冻结 {out['r']}"
        )
        assert t["exit_reason"] == out["exit"]
        assert t["exit_bar"] == out["exit_bar"]
        ok += 1
    assert ok == BASELINE["outcomes_reproduced"]


def test_no_trade_segments_do_not_produce_gate_plans():
    """空仓段没有可裁决计划——防止有人给空仓段补 plan 再「过门槛」。"""
    for g in _gold():
        if g["verdict"] == "no_trade":
            assert g["entry"] is None and g["stop"] is None and not g["targets"]


def test_gold_composition_matches_index():
    """配比与 INDEX.md 记载一致：震荡 11 / 下降 10 / 上升 9，候选 2 / 空仓 28。"""
    gs = _gold()
    by_ctx = {}
    for g in gs:
        by_ctx[g["context"]] = by_ctx.get(g["context"], 0) + 1
    assert by_ctx == {"震荡": 11, "下降": 10, "上升": 9}, by_ctx
    cands = sum(1 for g in gs if g["verdict"] == "candidate")
    assert (cands, len(gs) - cands) == (2, 28)


def test_setup_coverage_is_known():
    """六张卡在冻结集里的覆盖：缺的卡不能当成「已验证」，清单写死在测试里。"""
    covered = {}
    for g in _gold():
        if g["setup"]:
            covered[g["setup"]] = covered.get(g["setup"], 0) + 1
    # 冻结集实际只覆盖 A1/A2/B1/B3；B2 与 C1 零样本 —— 断言它保持为零，
    # 哪天补进金标准，这里会提醒同步更新「已验证」口径。
    assert covered == {"A1": 5, "A2": 4, "B1": 2, "B3": 1}, covered
