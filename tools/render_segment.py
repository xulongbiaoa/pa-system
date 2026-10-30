"""把数据段的决策点前 K 线渲成图（A/B 实验：数字 vs 数字+图）。

用法：python3 tools/render_segment.py <segment> <out.png> [cutoff=180]
渲染口径：只画 cutoff 之前的根（决策点盲测），无任何标注，蜡烛 + EMA20。
"""
import json
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "eval"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gold_build import bars_of  # noqa: E402

CHART_LAB = os.path.expanduser(
    "~/workspace/goals/goal/hidden_files/chart-lab")

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="file://{lab}/lightweight-charts.js"></script>
<style>*{{margin:0}}#c{{width:1500px;height:800px}}</style></head>
<body><div id="c"></div><script>
const chart = LightweightCharts.createChart(document.getElementById('c'), {{
  width: 1500, height: 800,
  layout: {{ background: {{ color: '#ffffff' }}, textColor: '#333' }},
  grid: {{ vertLines: {{ color: '#eee' }}, horzLines: {{ color: '#eee' }} }},
  timeScale: {{ visible: false }},
}});
const s = chart.addCandlestickSeries({{
  upColor: '#26a69a', downColor: '#ef5350',
  borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350',
}});
const data = {data};
s.setData(data.map((b, i) => ({{ time: i + 1, open: b.o, high: b.h, low: b.l, close: b.c }})));
const ema = chart.addLineSeries({{ color: '#2962FF', lineWidth: 1 }});
let k = 2 / 21, prev = null;
ema.setData(data.map((b, i) => {{ prev = prev === null ? b.c : b.c * k + prev * (1 - k); return {{ time: i + 1, value: prev }}; }}));
chart.timeScale().fitContent();
</script></body></html>"""

SHOT_JS = """
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const crypto = require('crypto');
// 本机 Chromium 启动须带 Hatch WebGL 域策略（同 trainer smoke 口径）
fs.writeFileSync('/tmp/webgl-policy.txt', ['hatch-webgl-allowed-domains-v1', 'example.com', ''].join(String.fromCharCode(10)));
const POLICY_SHA = crypto.createHash('sha256')
  .update(fs.readFileSync('/tmp/webgl-policy.txt')).digest('hex');
(async () => {
  const browser = await puppeteer.launch({
    executablePath: '/opt/meta-chromium/chrome', headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--hide-scrollbars',
      '--hatch-webgl-allowed-domains-file=/tmp/webgl-policy.txt',
      '--hatch-webgl-allowed-domains-sha256=' + POLICY_SHA],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1520, height: 820, deviceScaleFactor: 1.5 });
  await page.goto('file://' + process.argv[2], { waitUntil: 'networkidle0', timeout: 30000 });
  await new Promise(r => setTimeout(r, 2000));
  await page.screenshot({ path: process.argv[3] });
  await browser.close();
  console.log('ok');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
"""


def render(segment, out_png, cutoff=180):
    bars = bars_of(segment)[:cutoff]
    html = HTML.format(lab=CHART_LAB, data=json.dumps(bars))
    tmp = f"/tmp/seg-{segment}.html"
    with open(tmp, "w") as f:
        f.write(html)
    js = "/tmp/shot_segment.js"
    with open(js, "w") as f:
        f.write(SHOT_JS)
    env = dict(os.environ, NODE_PATH=os.path.join(CHART_LAB, "node_modules"))
    r = subprocess.run(["node", js, tmp, out_png], capture_output=True,
                       text=True, env=env, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-500:])
    return out_png


if __name__ == "__main__":
    cut = int(sys.argv[3]) if len(sys.argv) > 3 else 180
    print(render(sys.argv[1], sys.argv[2], cut))
