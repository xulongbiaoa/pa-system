"""把某天 CSV 的前 N 根渲染成净图（带 EMA20），供执行轴盲考。"""
import csv, datetime, json, sys, os

def render(day_csv, n, out_html, day):
    rows = list(csv.DictReader(open(day_csv)))[:n]
    bars, ema, e = [], [], None
    y, m, d = (int(x) for x in day.split('-'))
    for r in rows:
        hh, mm = (int(x) for x in r['time_et'].split(':'))
        t = int(datetime.datetime(y, m, d, hh, mm, tzinfo=datetime.timezone.utc).timestamp())
        c = float(r['close'])
        bars.append({'time': t, 'open': float(r['open']), 'high': float(r['high']),
                     'low': float(r['low']), 'close': c})
        e = c if e is None else c * (2 / 21) + e * (19 / 21)
        ema.append({'time': t, 'value': round(e, 2)})
    html = '''<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="/home/hatch/workspace/goals/goal/hidden_files/chart-lab/lightweight-charts.js"></script>
<style>*{margin:0}body{background:#fff}#chart{width:1300px;height:820px}</style></head>
<body><div id="chart"></div><script>
const chart = LightweightCharts.createChart(document.getElementById('chart'), { width: 1300, height: 820,
  layout: { background: { color: '#ffffff' }, textColor: '#333' },
  grid: { vertLines: { color: '#eeeeee' }, horzLines: { color: '#eeeeee' } },
  timeScale: { timeVisible: true, secondsVisible: false }, rightPriceScale: {} });
const s = chart.addCandlestickSeries({ upColor: '#ffffff', downColor: '#111111',
  borderUpColor: '#111111', borderDownColor: '#111111', wickUpColor: '#111111', wickDownColor: '#111111' });
s.setData(%s);
const emaLine = chart.addLineSeries({ color: '#2962FF', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
emaLine.setData(%s);
chart.timeScale().fitContent();
</script></body></html>''' % (json.dumps(bars), json.dumps(ema))
    open(out_html, 'w').write(html)

if __name__ == '__main__':
    render(sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4])
