#!/usr/bin/env python3
"""分支 A/B 到达判读校验器（协调者用）。

用法：python3 validate_arrivals.py <eid> [<eid> ...]
     python3 validate_arrivals.py --all   # 按 population.json 全量校验
逐份检查：eval/branch-ab/judgments2/<eid>.json 存在、JSON 可解析、
judge.validate.validate_judgment 返回空列表。
输出每份一行状态，末尾汇总；退出码 0 = 全部合法。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "..", ".."))

from judge.validate import validate_judgment  # noqa: E402

JDIR = os.path.join(BASE, "judgments2")


def check(eid):
    path = os.path.join(JDIR, eid + ".json")
    if not os.path.exists(path):
        return ("MISSING", "文件不存在")
    try:
        with open(path) as f:
            obj = json.load(f)
    except Exception as e:
        return ("BADJSON", f"JSON 解析失败：{e}")
    if not isinstance(obj, dict):
        return ("BADJSON", "顶层不是 JSON 对象")
    try:
        errs = validate_judgment(obj)
    except Exception as e:
        return ("VALERR", f"validate_judgment 抛错：{e}")
    if errs:
        return ("INVALID", "; ".join(str(e) for e in errs))
    return ("OK", "")


def main():
    args = sys.argv[1:]
    if not args or args == ["--all"]:
        pop = json.load(open(os.path.join(BASE, "population.json")))
        ids = [e["eid"] for e in pop]
    else:
        ids = args
    ok = 0
    for eid in ids:
        status, detail = check(eid)
        if status == "OK":
            ok += 1
        print(f"{eid}\t{status}\t{detail}")
    print(f"TOTAL {ok}/{len(ids)} OK")
    sys.exit(0 if ok == len(ids) else 1)


if __name__ == "__main__":
    main()
