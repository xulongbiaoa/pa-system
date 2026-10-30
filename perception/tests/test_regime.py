import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from perception.regime import regime_features, classify_regime


def _bars(n=60, drift=0.0):
    out, p = [], 100.0
    for i in range(n):
        c = p + drift
        out.append({"o": p, "h": max(p, c) + 0.4, "l": min(p, c) - 0.4, "c": c})
        p = c
    return out


def test_features_shape():
    f = regime_features(_bars())
    for k in ("overlap_mean", "efficiency", "ema", "breakouts", "gaps", "bodies"):
        assert k in f
    assert 0 <= f["overlap_mean"] <= 1 and 0 <= f["efficiency"] <= 1


def test_flat_market_classifies_range():
    r = classify_regime(_bars(120, drift=0.0))
    assert r["context"] == "震荡"
