"""错误空仓考试盲判产物校验：文件存在 / JSON 可解析 / validate_judgment 空错。

用法：python3 eval/false-empty/validate_judgments.py [X01 X02 ...]
不带参数时校验 judgments/ 下全部 X*.json。
输出每份一行：<code> OK 或 <code> FAIL: <错误原文...>；退出码 0=全过。
"""
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/workspace/pa-system"))
from judge.validate import validate_judgment  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))


def check(code):
    path = os.path.join(BASE, "judgments", code + ".json")
    if not os.path.exists(path):
        return ["文件不存在: " + path]
    try:
        j = json.load(open(path))
    except Exception as e:  # noqa: BLE001
        return [f"JSON 解析失败: {e}"]
    if not isinstance(j, dict):
        return ["顶层不是 JSON 对象"]
    return validate_judgment(j)


def main():
    codes = sys.argv[1:]
    if not codes:
        d = os.path.join(BASE, "judgments")
        codes = sorted(fn[:-5] for fn in os.listdir(d)
                       if fn.startswith("X") and fn.endswith(".json"))
    bad = 0
    for code in codes:
        errs = check(code)
        if errs:
            bad += 1
            print(f"{code} FAIL: " + " | ".join(str(e) for e in errs))
        else:
            print(f"{code} OK")
    print(f"== {len(codes) - bad}/{len(codes)} 合法")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
