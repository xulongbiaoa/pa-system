"""模式台账 v1：按 setup 建格累计，语境与下单方式只做审计分层。

## 为什么必须有 b

`gate.sizing.suggest` 要 `b`（已实现盈亏比）才能算触顶胜率 `p*`、精度成本
`n_for_precision` 与阶段 `stage`。没有 b，凯利只能退回「拿计划首目标 RR 当
b」，那是**承诺**不是**实现**——两者在实测里能差 3 倍以上（见 changelog
「H1 改为现价口径」一节）。所以台账格子必须存 R 的一二阶量，b 由实现值算。

## 为什么按 setup 建格，不按 setup×语境×下单方式

按段计（每段最多一次决策），金标准 30 段里只有 2 段有完整计划（6.7%）：

| 分格粒度 | 填满一格 n=30 需要 |
|---|---|
| setup × 语境 × 下单方式 = 36 格 | 16,200 段 |
| setup × 语境 = 9 格（H6 口径） | 4,050 段 |
| setup = 6 格 | 2,700 段 |
| 全池 = 1 格 | 450 段 |

分格粒度是**样本预算决策**，不是审美决策。每多一个维度，样本成本乘上该
维度的取值数。所以：

- **凯利的 p 与 b 取该 setup 的全池合计**（`all`）——最粗、最先填得满；
- **H6 停牌取 setup×语境**（`by_context`）——它是「这个 setup 在这个语境里
  已经连败」的否决判断，可以稀疏，不需要 n≥30；
- **下单方式**（`by_order_type`）只记录、不进任何参数估计。理由：限价单
  「等回踩再进」会系统性抬高实现 b（ds23 实测抬价 2% 让承诺 RR 从 2.59
  到 7.98），但成交条件也随之变严，市价单与限价单是两个不同 (p, b) 总体。
  一旦某 setup 的 limit 占比 >30% 且全池 n≥30，就该把它拆成参数维度——
  届时**另案提案**，不在这里提前拆。

## 文件形状

    {
      "A1": {
        "all":           {"n": 0, "wins": 0, "r_sum": 0.0, "r_win_sum": 0.0, "r_loss_sum": 0.0},
        "by_context":    {"上升": {...}, "下降": {...}, "震荡": {...}},
        "by_order_type": {"market": {...}, "limit": {...}}
      }
    }

`b = (r_win_sum/wins) / (|r_loss_sum|/(n−wins))`，任一侧无样本则 None（不给
凯利瞎猜的机会）。
"""

import json
import os

EMPTY = {"n": 0, "wins": 0, "r_sum": 0.0, "r_win_sum": 0.0, "r_loss_sum": 0.0}
DEFAULT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "knowledge", "ledger", "mode_stats.json"
)


def empty_cell():
    return dict(EMPTY)


def cell_b(cell):
    """已实现盈亏比 b = 平均盈利 R / 平均亏损 |R|；任一侧无样本返回 None。"""
    if not cell:
        return None
    n, wins = cell.get("n", 0), cell.get("wins", 0)
    losses = n - wins
    if wins <= 0 or losses <= 0:
        return None
    avg_win = cell.get("r_win_sum", 0.0) / wins
    avg_loss = abs(cell.get("r_loss_sum", 0.0)) / losses
    if avg_loss <= 0:
        return None
    return round(avg_win / avg_loss, 4)


def _bump(cell, r):
    cell["n"] += 1
    cell["r_sum"] = round(cell["r_sum"] + r, 6)
    if r > 0:
        cell["wins"] += 1
        cell["r_win_sum"] = round(cell["r_win_sum"] + r, 6)
    else:
        cell["r_loss_sum"] = round(cell["r_loss_sum"] + r, 6)
    return cell


def accumulate(store, setup, context, order_type, r, win=None):
    """把一笔已结算交易记进台账（三处同时累加：all / by_context / by_order_type）。

    win 不传则按 r>0 判；r 的单位是 R（已扣费），与 replay 输出一致。
    注意：**不要用正在评估的那批样本喂台账**再拿它去调仓位——那是自证。
    台账应由独立的历史回放（trainer 池 / 更早的实盘）填充。
    """
    if r is None:
        return store
    if win is None:
        win = r > 0
    ot = order_type or "market"
    seg = store.setdefault(setup, {
        "all": empty_cell(),
        "by_context": {},
        "by_order_type": {},
    })
    _bump(seg["all"], r)
    _bump(seg["by_context"].setdefault(context or "未定", empty_cell()), r)
    _bump(seg["by_order_type"].setdefault(ot, empty_cell()), r)
    return store


def ingest_trades(store, trades):
    """从回放结果列表批量累加；每笔须带 setup / context / order_type / r。"""
    for t in trades:
        accumulate(store, t.get("setup"), t.get("context"),
                   t.get("order_type"), t.get("r"), t.get("win"))
    return store


def load(path=DEFAULT_PATH):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save(store, path=DEFAULT_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(store, f, ensure_ascii=False, indent=1, sort_keys=True)
    return path


def gate_view(store):
    """转成裁决层的台账视图：{(setup, 语境): {n, wins, b, b_n, b_wins}}。

    - `n` / `wins`：该 setup×语境的样本 → H6 停牌用（语境特异，可以稀疏）
    - `b` / `b_n` / `b_wins`：该 setup 全池的样本与盈亏比 → 凯利用（最粗，
      最先填得满；与 p 同总体，不许拿 A 总体的 b 配 B 总体的 p）

    某 setup 没有对应语境格子时也照样给（n=0），让 H6 判「无样本」而不是
    「查不中」——静默失效是这一层最容易犯的错。
    """
    out = {}
    for setup, seg in (store or {}).items():
        all_cell = seg.get("all") or empty_cell()
        b = cell_b(all_cell)
        ctxs = seg.get("by_context") or {}
        if not ctxs:
            ctxs = {"未定": empty_cell()}
        for ctx, cell in ctxs.items():
            out[(setup, ctx)] = {
                "n": cell.get("n", 0),
                "wins": cell.get("wins", 0),
                "b": b,
                "b_n": all_cell.get("n", 0),
                "b_wins": all_cell.get("wins", 0),
            }
    return out


def summary(store):
    """人读摘要：每 setup 一行，带全池 n / 胜率 / b 与各语境、下单方式拆分。"""
    rows = []
    for setup in sorted(store):
        seg = store[setup]
        all_cell = seg.get("all") or empty_cell()
        n, wins = all_cell.get("n", 0), all_cell.get("wins", 0)
        rows.append({
            "setup": setup,
            "n": n,
            "win_rate": round(wins / n, 4) if n else None,
            "b": cell_b(all_cell),
            "by_context": {k: v.get("n", 0) for k, v in (seg.get("by_context") or {}).items()},
            "by_order_type": {k: v.get("n", 0) for k, v in (seg.get("by_order_type") or {}).items()},
        })
    return rows
