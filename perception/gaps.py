"""缺口账本（定义 v0.2 定版口径）。

缺口 = 有人被套、没出来的地方。一条缺口 = 一条锚线，只记单线。
- 锚的来源：地图线（波段高低点 / 要塞沿口，由调用方给入）+ 强突破 K 的
  起点线（起点 K 背向突破方向的极值，本模块自动立）。
- 立账：一根 K 整体越过锚外侧（整根在锚的一侧）且此前价格在另一侧；
  立账前先碰回锚 = 胎死，不入账。
- 生死只看锚线：盘中碰回锚 = 解套销账；没碰到就是没解套（差一点也算
  没补，只记一次「回补未遂」：逼近到缓冲带内、未碰到、下一根收盘转身
  离去）。
- 每条记：锚价与来源 / 套住谁（上破套空、下破套多）/ 破于第几根 /
  套深（立账后最大不利距离）/ 套时（根数）/ 未遂次数 / 状态。
"""


def trimmed_avg_range(bars, lookback=20):
    rs = [b["h"] - b["l"] for b in bars[-lookback:]]
    if not rs:
        return 0.0
    tail = sorted(r for r in [b["h"] - b["l"] for b in bars[-5:]])
    med5 = tail[len(tail) // 2] if tail else 0.0
    kept = [r for r in rs if med5 <= 0 or r <= 2 * med5]
    use = kept if kept else rs
    return sum(use) / len(use)


def _run_anchor(bars, price, source, birth_hint=None):
    """对单条锚线跑状态机，返回入账记录或 None（从未立账）。"""
    n = len(bars)
    start = 0
    if birth_hint is not None:
        # 起点锚：出生根即立账（突破 K 本身已整体离开），从出生根起算。
        i0 = birth_hint
        up = bars[i0]["c"] > price
        rec = {
            "price": price,
            "source": source,
            "trapped": "short" if up else "long",
            "opened_at": i0,
            "closed_at": None,
            "status": "open",
            "depth": 0.0,
            "attempts": 0,
        }
        _run_open(bars, rec, i0 + 1, up)
        rec["duration"] = (rec["closed_at"] if rec["closed_at"] is not None else n - 1) - i0
        return rec
    # 地图锚：找立账点。先有收盘穿越（pending），整根越过才立账；
    # 立账前碰回锚则 pending 清零。
    side = None  # 'up' / 'down' pending 方向
    for i in range(n):
        b = bars[i]
        touched = b["l"] <= price <= b["h"]
        if side is None:
            if i == 0:
                continue
            pc = bars[i - 1]["c"]
            if pc <= price and b["c"] > price:
                side = "up"
            elif pc >= price and b["c"] < price:
                side = "down"
            else:
                continue
            if touched:
                # 穿越根自身碰到锚：若整根已越过（不可能同时 touched），
                # 否则继续等整根越过；本根 touched 不算立账。
                if (side == "up" and b["l"] > price) or (side == "down" and b["h"] < price):
                    pass
                else:
                    continue
            else:
                # 整根已在外侧（穿越根不碰锚即整根越过）
                pass
            # 检查本根是否整根越过
            if (side == "up" and b["l"] > price) or (side == "down" and b["h"] < price):
                rec = {
                    "price": price,
                    "source": source,
                    "trapped": "short" if side == "up" else "long",
                    "opened_at": i,
                    "closed_at": None,
                    "status": "open",
                    "depth": 0.0,
                    "attempts": 0,
                }
                _run_open(bars, rec, i + 1, side == "up")
                rec["duration"] = (
                    rec["closed_at"] if rec["closed_at"] is not None else n - 1
                ) - i
                return rec
            continue
        else:
            if touched:
                side = None  # 立账前碰回，胎死
                continue
            if (side == "up" and b["l"] > price) or (side == "down" and b["h"] < price):
                rec = {
                    "price": price,
                    "source": source,
                    "trapped": "short" if side == "up" else "long",
                    "opened_at": i,
                    "closed_at": None,
                    "status": "open",
                    "depth": 0.0,
                    "attempts": 0,
                }
                _run_open(bars, rec, i + 1, side == "up")
                rec["duration"] = (
                    rec["closed_at"] if rec["closed_at"] is not None else n - 1
                ) - i
                return rec
    return None


def _run_open(bars, rec, from_i, up):
    price = rec["price"]
    n = len(bars)
    buf = trimmed_avg_range(bars) * 0.25
    for j in range(from_i, n):
        b = bars[j]
        if b["l"] <= price <= b["h"]:
            rec["status"] = "closed"
            rec["closed_at"] = j
            return
        if up:
            rec["depth"] = max(rec["depth"], b["h"] - price)
            dist = b["l"] - price
        else:
            rec["depth"] = max(rec["depth"], price - b["l"])
            dist = price - b["h"]
        # 回补未遂：逼近缓冲带内、未碰到、下一根收盘转身离去
        if 0 < dist <= buf and j + 1 < n:
            nb = bars[j + 1]
            if nb["l"] <= price <= nb["h"]:
                continue  # 下一根直接碰到 = 销账，不算未遂
            away = nb["c"] > b["c"] if up else nb["c"] < b["c"]
            if away:
                rec["attempts"] += 1


def build_ledger(bars, map_anchors, cfg):
    """map_anchors: [{'price': float, 'source': str}]。返回入账记录列表。"""
    out = []
    for a in map_anchors:
        rec = _run_anchor(bars, float(a["price"]), a.get("source", "map"))
        if rec:
            rec["depth"] = round(rec["depth"], 6)
            out.append(rec)
    # 起点锚：强突破 K（振幅与实体达标）收盘越过任一地图锚时，在其背向
    # 极值立一条起点缺口。
    mult = cfg.get("strong_break_range_mult", 1.3)
    body_min = cfg.get("strong_break_body_min", 0.6)
    seen_origin = set()
    for i, b in enumerate(bars):
        rng = b["h"] - b["l"]
        if rng <= 0:
            continue
        base = trimmed_avg_range(bars[: i + 1])
        if base <= 0 or rng < mult * base:
            continue
        body = abs(b["c"] - b["o"]) / rng
        if body < body_min:
            continue
        up = b["c"] > b["o"]
        crossed = any(
            (bars[i - 1]["c"] <= a["price"] < b["c"]) if up else (bars[i - 1]["c"] >= a["price"] > b["c"])
            for a in map_anchors
        ) if i > 0 else False
        if not crossed:
            continue
        origin_price = b["l"] if up else b["h"]
        if origin_price in seen_origin:
            continue
        seen_origin.add(origin_price)
        rec = _run_anchor(bars, origin_price, "origin", birth_hint=i)
        if rec:
            rec["depth"] = round(rec["depth"], 6)
            out.append(rec)
    out.sort(key=lambda r: r["opened_at"])
    return out
