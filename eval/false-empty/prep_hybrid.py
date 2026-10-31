#!/usr/bin/env python3
"""混合臂考试套件生成（2026-10-31 混合臂：视觉主判 + 数字附件）。

以 vision_prompt.md 为底本做定点改编，产出混合提示模板
vision_prompt_hybrid.md，再逐题填充数字锚并嵌入该题数字附件
（annex/X*.md，由 gen_annex.py 生成），产出 prompts-hybrid/。

混合纪律（相对视觉版的改动只有三类）：
  1. 位置认证来源变更：缺口锚、要塞带、摆动锚以附件认证为准，
     不许再以「图上指认不出锚线」挂账本/位置类缺项；
  2. 定价优先取附件锚价，附件没有的结构位才肉眼估读；
  3. 附件只认证位置与价位，不认证语境/结构/行为——定性仍看图。
图面沿用 charts-vision 的 PNG，一字节不改、不画线。

用法：python3 eval/false-empty/prep_hybrid.py
（先跑 gen_annex.py 生成附件）
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.path.join(ROOT, "eval", "false-empty")

EDITS = [
    # 1 标题
    ("# 视觉判读任务（图读主线 · 考试卷）",
     "# 混合判读任务（视觉主判 + 数字附件 · 考试卷）"),
    # 2 附图说明：识别归图、位置归附件
    ("所有语境、结构、位置、价位都由你从图上读。",
     "语境、结构、到达行为由你从图上读；位置与价位以文末数字附件"
     "认证为索引、图上复核。"),
    # 3 数字锚与附件输入
    ("- 全卷唯一的数字（相当于读图时与坐标轴互相核对的锚点，仅此一处）：",
     "- 决策根数字锚（读图时与坐标轴互相核对的锚点）："),
    ("- 你没有 OHLC 数值表、没有特征包、没有预画地图。**禁止使用任何工具读取文件**，禁止猜测标的与周期。",
     "- 数字附件（文末）：由决策根特征包按现行感知口径算出的**位置与"
     "价位事实**——开账缺口锚、要塞带、主要摆动锚。它只认证位置与"
     "价位，不含任何定性结论；用法见「附件使用纪律」。\n"
     "- 你没有 OHLC 数值表、没有预画地图。**禁止使用任何工具读取"
     "文件**，禁止猜测标的与周期。"),
    # 4 记账步骤：账本锚以附件认证
    ("1. **记账（图读版）**：图上能认出的敞开缺口（突破后未被回补的位移段/摆动缺口）在哪、套住谁、双方解套位在哪；认不出的写进 uncertainty，不许硬凑账本。",
     "1. **记账**：敞开缺口以**附件认证**为准（锚价、锚类型、被套侧、"
     "回补尝试次数都在附件里）；账本的含义——套住谁、双方解套位在"
     "哪、回补关系成不成立——仍由你看图判。附件没列的缺口不许硬凑，"
     "图上另有可见跳空而附件未列的写进 uncertainty。"),
    # 5 位置关：决胜点由附件认证
    ("位置关（价格是否在图上可明确指认的要塞级支撑/阻力边缘，即决胜点）",
     "位置关（价格是否在要塞级支撑/阻力边缘，即决胜点——位置由附件"
     "认证：附件的要塞带、缺口锚、摆动锚同址即已认证，图上指认作复核）"),
    # 6 读价纪律 → 混合版（附件锚价优先）
    ("- **读价纪律（视觉专属）**：entry / stop / stop_basis / targets / void.level 全部从价格轴读数给出，小数位与决策根 OHLC 保持一致；图上读不准的价位写进 uncertainty 说明，不许编造精度。",
     "- **读价纪律（混合版）**：计划价位落在附件已认证的结构位（缺口"
     "锚、要塞带边、摆动锚）时，一律用附件的精确数字，不许用肉眼估"
     "读替代；附件没有的结构位才从价格轴读数给出，小数位与决策根 "
     "OHLC 保持一致；读不准的写进 uncertainty，不许编造精度。\n"
     "- **附件使用纪律**：① 位置以附件认证为准——附件列出的缺口锚、"
     "要塞带、摆动锚即已认证位置，**不许以「图上指认不出锚线」为由"
     "把账本/位置类必须项（如 G1-R1、A1/A2-N4 的落点同址）挂缺项**；"
     "落点是否与锚同址，按附件锚价 ±0.25×段均幅核对。② 附件只认证"
     "位置与价位，**不认证语境、结构与行为**：不许仅凭附件的被套侧"
     "或带分布直接下定性结论；到达行为、收回认定、信号成色仍逐项看"
     "图判，图读不成立的，附件再齐也不许写候选。③ 附件未列的位置"
     "不许凭空认证：图上读到的结构位附件没有的，按小据点处理并在 "
     "uncertainty 注明「附件未认证」。"),
    # 7 依据引用：附件不是 basis 类别
    ("加分项（B/E 条目）不许列为 missing；extra 不许单独构成不写候选的理由：卡上必须项已齐、无否决时必须写候选，extra 只作复核标记。",
     "加分项（B/E 条目）不许列为 missing；extra 不许单独构成不写候选"
     "的理由：卡上必须项已齐、无否决时必须写候选，extra 只作复核标"
     "记。附件是位置认证来源、不是 basis 类别：因附件已认证而成立的"
     "位置项不许再列 missing；因行为或语境未成立而缺的项照常引 card。"),
    # 8 B2-N2：指认口径含附件
    ("N2 位置：回踩落点 = 被破要塞 / 据点的沿口线本身，或其翻面位；图上指认不出的位不算。",
     "N2 位置：回踩落点 = 被破要塞 / 据点的沿口线本身，或其翻面位；图上与附件都指认不出的位不算。"),
    # 9 G1-R1：锚线价位以附件认证
    ("R1 账本方向〔账本〕：目标缺口在决策时仍敞开（图上能指认锚线价位）",
     "R1 账本方向〔账本〕：目标缺口在决策时仍敞开（锚线价位以附件认证为准）"),
    # 10 G1-V3：决胜点含附件认证
    ("V3 不在决胜点：落点不是图上可明确指认的据点/要塞边缘（图上认不出的位置默认小据点）",
     "V3 不在决胜点：落点不是附件已认证或图上可明确指认的据点/要塞边缘（两处都认不出的位置默认小据点）"),
]


def build_template():
    src = open(os.path.join(BASE, "vision_prompt.md")).read()
    for old, new in EDITS:
        assert src.count(old) == 1, f"edit miss ({src.count(old)}): {old[:40]}"
        src = src.replace(old, new)
    out = os.path.join(BASE, "vision_prompt_hybrid.md")
    open(out, "w").write(src)
    return src


def main():
    template = build_template()
    manifest = {m["item"]: m for m in
                json.load(open(os.path.join(BASE, "vision-manifest.json")))}
    outdir = os.path.join(BASE, "prompts-hybrid")
    os.makedirs(outdir, exist_ok=True)
    for item in sorted(manifest):
        m = manifest[item]
        d = m["decision_bar"]
        text = template
        for tok, val in (("{N_BARS}", str(m["n_bars"])),
                         ("{DECISION_O}", str(d["o"])),
                         ("{DECISION_H}", str(d["h"])),
                         ("{DECISION_L}", str(d["l"])),
                         ("{DECISION_C}", str(d["c"])),
                         ("{SEG_AVG}", str(m["seg_avg_range"]))):
            assert tok in text, (item, tok)
            text = text.replace(tok, val)
        annex = open(os.path.join(BASE, "annex", item + ".md")).read()
        text = text + "\n\n---\n\n" + annex
        open(os.path.join(outdir, item + ".md"), "w").write(text)
        print(item, "prompt ok, annex lines", annex.count("\n"))
    print("hybrid prompts done:", len(manifest))


if __name__ == "__main__":
    main()
