"""反思层：对一笔已完成的交易做 A–E 归因初分（reflection_schema 口径）。

归因口径：A 感知错 / B 判断错 / C 裁决错 / D 执行偏差 / E 方差内。
铁律：new_rule_proposed 恒为 false——反思只归因不立规，allowed_action
只许落到记账/补测试/补样本这类不改规则的动作。
本模块是规则化初分：blind_rejudge 字段如实标注「未做盲重判」，
matches_original 以「是否按计划出场」为代理，终判须复核。

用法：
  python3 judge/reflect.py <judgment.json> <trade.json> [out.json]
trade.json 字段：segment / setup / side / exit_reason / net_r。
"""

import json
import sys

from judge.validate import validate_reflection

ACTION = {"A": "补感知测试", "B": "补反例样本", "C": "强化裁决", "D": "记账", "E": "记账"}


def attribute(judgment, trade):
    refs = []
    for c in judgment.get("candidates", []):
        refs += c.get("feature_refs", [])
    if any("未定" in str(r) for r in refs):
        return "A", "判断引用了置信未定的特征，感知层先背锅"
    if trade.get("exit_reason") == "window_end":
        return "D", "计划未在窗内兑现出场（到期未触目标/止损）"
    return "E", "按计划出场，结果在交易者等式的方差内"


def reflect(judgment, trade):
    category, why = attribute(judgment, trade)
    out = {
        "blind_rejudge": "未做盲重判（规则化初分，待复核）",
        "matches_original": trade.get("exit_reason") in ("stop", "target"),
        "info_available_at_time": True,
        "category": category,
        "in_prior_range": None,
        "evidence": [f"exit_reason={trade.get('exit_reason')}", f"net_r={trade.get('net_r')}", why],
        "allowed_action": ACTION[category],
        "new_rule_proposed": False,
    }
    errs = validate_reflection(out)
    if errs:
        raise ValueError("reflection invalid: " + "; ".join(errs))
    return out


def main():
    judgment = json.load(open(sys.argv[1]))
    trade = json.load(open(sys.argv[2]))
    out = reflect(judgment, trade)
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if len(sys.argv) > 3:
        with open(sys.argv[3], "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
