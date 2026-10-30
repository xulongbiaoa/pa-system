"""原册图考场索引：把示例册（2#）页面按「同一张底图」聚类，
组内最干净的一页当考题、最标注的一页文本当答案卡。

干净度 = 图区（去掉标题/页脚条）内高饱和彩色像素占比（他的彩色批注多，
K 线黑白、EMA 灰，饱和度低）。同图判定 = 图区灰度 aHash 汉明距离。
"""
import glob, json, os, sys
from PIL import Image

ROOT = os.path.expanduser('~/workspace/.tmp/bookpages')

def page_stats(path):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    band = im.crop((0, int(h * 0.12), w, int(h * 0.95)))
    # aHash
    g = band.convert('L').resize((48, 24))
    px = list(g.getdata())
    mean = sum(px) / len(px)
    bits = ''.join('1' if p > mean else '0' for p in px)
    # 彩色密度
    small = band.resize((band.width // 3, band.height // 3))
    hsv = small.convert('HSV')
    sp = list(hsv.getdata())
    colored = sum(1 for _, s, v in sp if s > 90 and v > 50)
    return bits, colored / len(sp)

def hamming(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)

VERDICT_WORDS = ('wedge', 'double top', 'double bottom', 'climax', 'flag',
                 'triangle', 'head and shoulders', ' h2', ' l2', ' h1', ' l1',
                 'breakout', 'reversal', 'channel', 'trading range', 'trend',
                 'scalp', 'swing', 'buy', 'sell', 'bull', 'bear', 'gap',
                 'measured move', 'always in', 'trap', 'spike')

def slide_texts():
    import glob as g
    out = {}
    for f in g.glob('knowledge/brooks-cases/raw/*.jsonl'):
        for line in open(f):
            d = json.loads(line)
            out[(d['book'], d['slide'])] = d.get('text', '')
    return out

def leak_score(text):
    low = ' ' + text.lower().replace('\n', ' ') + ' '
    return sum(1 for w in VERDICT_WORDS if w in low)

def main(out_path):
    texts = slide_texts()
    pages = []
    for f in sorted(glob.glob(f'{ROOT}/b*/p-*.png')):
        book = os.path.basename(os.path.dirname(f))
        try:
            slide = int(os.path.basename(f).split('-')[-1].split('.')[0])
        except ValueError:
            continue
        bits, dens = page_stats(f)
        pages.append({'book': book, 'slide': slide, 'path': f,
                      'hash': bits, 'density': round(dens, 5),
                      'leak': leak_score(texts.get((book.replace('b', 'v', 1), slide), ''))})
    pages.sort(key=lambda p: (p['book'], p['slide']))
    groups, used = [], set()
    for i, p in enumerate(pages):
        if i in used:
            continue
        grp = [p]
        used.add(i)
        for j in range(i + 1, len(pages)):
            if j not in used and hamming(p['hash'], pages[j]['hash']) <= 90:
                grp.append(pages[j])
                used.add(j)
        groups.append(grp)
    exams = []
    for grp in groups:
        if len(grp) < 2:
            continue
        grp = [g for g in grp if g['book'] == grp[0]['book']]
        if len(grp) < 2:
            continue
        slides = [g['slide'] for g in grp]
        if max(slides) - min(slides) > 8:
            grp = [g for g in grp if g['slide'] - min(slides) <= 8]
        if len(grp) < 2:
            continue
        grp.sort(key=lambda p: p['density'])
        clean, annotated = grp[0], grp[-1]
        if clean['leak'] <= 2 and annotated['leak'] >= 6 and \
                annotated['density'] >= max(0.006, clean['density'] * 1.8):
            exams.append({'clean': clean, 'annotated': annotated,
                          'group_size': len(grp),
                          'members': [(g['book'], g['slide'], g['density']) for g in grp]})
    json.dump({'pages': len(pages), 'groups': len(groups), 'exams': exams},
              open(out_path, 'w'), ensure_ascii=False, indent=1)
    print(f'pages {len(pages)} groups {len(groups)} exam-candidates {len(exams)}')

if __name__ == '__main__':
    main(sys.argv[1])
