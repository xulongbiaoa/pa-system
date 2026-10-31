"""W08 ground truth from the fresh frozen corpus. Prints no values."""
import json
from decimal import Decimal

DATA = '/home/hatch/workspace/pa-system/eval/w08/data'

def extract(sym):
    pkg = json.load(open(f'{DATA}/pkg_{sym}.json'))
    sc = pkg['scene']
    bars = [json.loads(l) for l in open(f'{DATA}/bars_{sym}.jsonl')]
    last = bars[-1]
    px = Decimal(str(last['close']))
    og = sc['open_gaps']
    def anch(g): return Decimal(str(g['anchor']))
    above = [g for g in og if anch(g) > px]
    below = [g for g in og if anch(g) < px]
    na = min(above, key=lambda g: anch(g) - px) if above else None
    nb = max(below, key=lambda g: anch(g)) if below else None
    mt = max(og, key=lambda g: g['test_count']) if og else None
    def fmt(g, with_tests=False):
        if g is None: return None
        d = {'gap_id': g['gap_id'], 'anchor': str(anch(g)), 'direction': g['direction'],
             'test_count': g['test_count'], 'distance': str(abs(anch(g) - px))}
        if with_tests:
            d['tests'] = [{'started_bar': t.get('started_bar'), 'ended_bar': t.get('ended_bar')} for t in g['tests']]
        return d
    def last_seg(side_key):
        segs = pkg[side_key]['segments'] if isinstance(pkg[side_key], dict) else pkg[side_key]
        closed = [s for s in segs if not s.get('open')]
        s = closed[-1] if closed else None
        if s is None: return None
        r = s['result']
        return {'segment_id': s['segment_id'], 'level_key': s['level_key'],
                'direction': r['direction'], 'net_progress': r['net_progress'],
                'giveback_ratio': r['giveback_ratio']}
    def latest_closed():
        cands = [x for x in (last_seg('side_up'), last_seg('side_down')) if x]
        return max(cands, key=lambda x: int(x['segment_id'].split('-')[1])) if cands else None
    return {
        'symbol': sym, 'token': pkg['token'],
        'last_close': str(px), 'last_bar_open_time': last['open_time'],
        'open_gap_count': len(og),
        'nearest_above': fmt(na), 'nearest_below': fmt(nb),
        'most_tested_open_gap': fmt(mt, with_tests=True),
        'latest_closed_segment': latest_closed(),
        'side_up_last': last_seg('side_up'), 'side_down_last': last_seg('side_down'),
    }

out = {s: extract(s) for s in ('BTCUSDT', 'ETHUSDT')}
json.dump(out, open('/home/hatch/workspace/pa-system/eval/w08/ground_truth.json', 'w'), ensure_ascii=False, indent=1)
print('ground_truth.json written for', list(out.keys()))
