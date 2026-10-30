"""阿布官网复盘图盲测：用官网标注图当标准答案，验感知层认不认得出。

用法：python3 eval/brooks_check.py <clean-data.csv> <cutoff1,cutoff2,...>
CSV 口径 = 复盘存档的 clean-data（5 分钟、日盘 09:30 ET 起、bar 1 = 首行）。
答案卡写在本文件 ANSWER 里（出自当日官网标注图与解读，见复盘存档）。
系统只看 cutoff 之前的 K 线；答案卡只用于事后对照，不进特征包。
"""
import csv
import sys

sys.path.insert(0, ".")
from perception.features import build_feature_pack, load_config  # noqa: E402

ANSWER_20261028 = {
    "day_type": "震荡",          # Trading Range Day（FOMC）
    "sell_climax_low": 7752.0,   # 开盘卖出高潮低点 / 开盘反转起点（bar 9 一带）
    "midday_spike_high": 7790.0,  # 中午尖峰顶（目标 7785 略超）
    "wedge_bottom": 7757.0,      # 楔形底/双底，两次测试（bars 58:61、69:70）
    "mm_target": 7818.0,         # MM 熊楔（图上明标），实际冲到约 7820
}


def load_bars(path):
    bars = []
    with open(path) as f:
        for r in csv.DictReader(f):
            bars.append({"o": float(r["open"]), "h": float(r["high"]),
                         "l": float(r["low"]), "c": float(r["close"])})
    return bars


def pack_at(bars, cfg):
    p0 = build_feature_pack(bars, [], cfg)
    anchors = [{"price": s["anchor"], "source": "swing-major"}
               for s in p0["swings"]["major"]]
    return build_feature_pack(bars, anchors, cfg)


def near(x, target, tol):
    return x is not None and abs(x - target) <= tol


def main():
    path, cutoffs = sys.argv[1], [int(x) for x in sys.argv[2].split(",")]
    bars_all = load_bars(path)
    cfg = load_config()
    a = ANSWER_20261028
    print(f"总根数 {len(bars_all)}，末收 {bars_all[-1]['c']}")
    for cut in cutoffs:
        bars = bars_all[:cut]
        p = pack_at(bars, cfg)
        print(f"\n=== cutoff bar {cut}（{bars[-1]['c']} 收）===")
        print("趋势标签:", p["trend"]["label"], "| 置信:", p["trend"].get("confidence"))
        bands = p["fortress"]["bands"]
        print("要塞带:", [(b["lo"], b["hi"], "测", b["tests"], "穿", b["crosses"]) for b in bands])
        print("摆动(major):", [(s["kind"], s["anchor"]) for s in p["swings"]["major"]])
        print("腿(major):", p.get("legs_major"))
        print("MM 投影: 特征包无此字段（mm_project 函数存在但未组装进 pack）")
        gaps = p.get("gaps", {})
        print("敞开缺口数:", len(gaps.get("open", [])), "| 账本置信:", gaps.get("confidence"))
        # 对照答案卡（仅全天 cutoff 有意义的项标注）
        for name, key, tol in (("楔形底 7757 带", "wedge_bottom", 3.0),
                               ("尖峰顶 7790 带", "midday_spike_high", 3.0)):
            hit = any(b["lo"] - tol <= a[key] <= b["hi"] + tol for b in bands)
            print(f"  对照 {name}: {'命中' if hit else '未命中'}")
        if cut >= 70:
            b7757 = [b for b in bands if b["lo"] - 3 <= a["wedge_bottom"] <= b["hi"] + 3]
            if b7757:
                print(f"  对照 双底测次（答案=至少 2）: 带测次 {b7757[0]['tests']}")


if __name__ == "__main__":
    main()
