"""W08 scoring per SPEC.md frozen rubric. Prints a compact summary only."""
import json

GT = json.load(open('eval/w08/ground_truth.json'))
TOL = {'BTCUSDT': 0.5, 'ETHUSDT': 0.05}
DTOL = {'BTCUSDT': 0.01, 'ETHUSDT': 0.003}

def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def close(a, b, tol):
    a, b = num(a), num(b)
    return a is not None and b is not None and abs(a - b) <= tol

def score(arm, sym):
    gt = GT[sym]; tol = TOL[sym]
    ans = json.load(open(f'eval/w08/runs/{arm}_{sym}.json'))
    errs, total = [], 0
    def chk(name, ok):
        nonlocal total; total += 1
        if not ok: errs.append(name)
    chk('F1.close', close(ans.get('f1_close'), gt['last_close'], tol))
    chk('F1.time', ans.get('f1_last_open_time') == gt['last_bar_open_time'])
    chk('F2.count', ans.get('f2_open_gap_count') == gt['open_gap_count'])
    def pick(*names):
        for n in names:
            if n in ans: return ans[n]
        return None
    for q, g in (('f3_above', gt['nearest_above']), ('f4_below', gt['nearest_below'])):
        a = pick(q, 'f3' if q.startswith('f3') else 'f4',
                 'f3_nearest_gap_above' if q.startswith('f3') else 'f4_nearest_gap_below',
                 'f3_nearest_open_gap_above' if q.startswith('f3') else 'f4_nearest_open_gap_below')
        if g is None:
            chk(q + '.null', a is None)
        else:
            chk(q + '.anchor', a is not None and close(a.get('anchor'), g['anchor'], tol))
            chk(q + '.direction', a is not None and a.get('direction') == g['direction'])
            ga, aa = num(g['distance']), (a or {}).get('distance')
            chk(q + '.distance', aa is not None and ga and abs(num(aa) - ga) <= ga * DTOL[sym])
    g5 = gt['most_tested_open_gap']; a5 = pick('f5_most_tested', 'f5', 'f5_most_tested_gap', 'f5_most_tested_open_gap') or {}
    chk('F5.anchor', close(a5.get('anchor'), g5['anchor'], tol))
    chk('F5.count', a5.get('test_count') == g5['test_count'])
    if g5['tests']:
        lt = g5['tests'][-1]
        s_ms = int(lt['started_bar'].rsplit('/', 1)[-1]) if lt.get('started_bar') else None
        e_ms = int(lt['ended_bar'].rsplit('/', 1)[-1]) if lt.get('ended_bar') else None
        chk('F5.start_ms', a5.get('last_test_started_ms') == s_ms)
        chk('F5.end_ms', a5.get('last_test_ended_ms') == e_ms)
    g6 = gt['latest_closed_segment']; a6 = pick('f6_latest_segment', 'f6', 'f6_latest_closed_segment', 'f6_last_completed_segment') or {}
    chk('F6.direction', a6.get('direction') == g6['direction'])
    chk('F6.net', close(a6.get('net_progress'), g6['net_progress'], max(tol, num(g6['net_progress']) * 0.02)))
    chk('F6.giveback', close(a6.get('giveback_ratio'), g6['giveback_ratio'], 0.05))
    for q, g in (('f7_up_last', gt['side_up_last']), ('f7_down_last', gt['side_down_last'])):
        a = ans.get(q) or {}
        chk(q + '.level', a.get('level_key') == g['level_key'])
        chk(q + '.net', close(a.get('net_progress'), g['net_progress'], max(tol, num(g['net_progress']) * 0.02)))
    # J2 recall: watch level hits a key anchor (price within tol) or key level_key
    key_prices = [num(x['anchor']) for x in (gt['nearest_above'], gt['nearest_below'], gt['most_tested_open_gap']) if x]
    key_levels = [x['gap_id'].rsplit('-', 1)[0] if False else None for x in ()]
    j2 = (ans.get('j2_watch_plan') or {}).get('level')
    recall = False
    if j2 is not None:
        p = num(j2)
        if p is not None and any(abs(p - kp) <= tol for kp in key_prices): recall = True
        gid = gt['most_tested_open_gap']['gap_id']
        if isinstance(j2, str) and j2.split('@')[0] in gid: recall = True
    return {'arm': arm, 'symbol': sym, 'fact_errors': errs, 'fact_total': total,
            'fact_error_count': len(errs), 'recall': recall,
            'j3': ans.get('j3_action'), 'unknowns': ans.get('unknowns') or []}

rows = []
for arm in ('battlefield', 'direct'):
    for sym in ('BTCUSDT', 'ETHUSDT'):
        rows.append(score(arm, sym))
for r in rows:
    print(f"{r['arm']:11s} {r['symbol']:8s} fact_errors {r['fact_error_count']}/{r['fact_total']}  recall={r['recall']}  j3={r['j3']}  unknowns={r['unknowns']}")
    if r['fact_errors']: print('   ', r['fact_errors'])
json.dump(rows, open('eval/w08/scores.json', 'w'), ensure_ascii=False, indent=1)
