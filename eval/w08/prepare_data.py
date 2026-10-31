"""W08 fresh corpus: fetch 1000 closed bars per symbol, build battlefield,
save arm materials. Prints NO fact values (exam hygiene)."""
import json, sys, dataclasses
sys.path.insert(0, '/home/hatch/workspace/pa-system')
from battlefield.feed import fetch_klines
from battlefield.runner import build_battlefield, scene_package

OUT = '/home/hatch/workspace/pa-system/eval/w08/data'
import os; os.makedirs(OUT, exist_ok=True)
for sym in ('BTCUSDT', 'ETHUSDT'):
    bars = fetch_klines(sym, '15m', limit=1000)
    with open(f'{OUT}/bars_{sym}.jsonl', 'w') as f:
        for b in bars:
            d = dataclasses.asdict(b) if dataclasses.is_dataclass(b) else dict(b.__dict__)
            f.write(json.dumps(d, default=str) + '\n')
    repo = build_battlefield(sym, '15m', 900_000, bars)
    pkg = scene_package(repo, since_revision=0)
    json.dump(pkg, open(f'{OUT}/pkg_{sym}.json', 'w'), ensure_ascii=False, default=str)
    print(sym, 'bars saved:', len(bars), 'pkg bytes:', os.path.getsize(f'{OUT}/pkg_{sym}.json'))
print('done')
