"""把原册页面的全部文字层词框涂白，留下图与线条 → 盲考题面。
文字位置来自 pdftotext -bbox（PPT 文字框是矢量层，可枚举）；
图表截图内部的坐标轴数字是栅格，不在文字层，保留可见。"""
import re, subprocess, sys, os
from PIL import Image, ImageDraw

PPT = os.path.expanduser('~/workspace/goals/goal/hidden_files/reference/ppt')

def mask_page(pdf_path, page, out_png, dpi=100):
    xml = subprocess.run(['pdftotext', '-f', str(page), '-l', str(page),
                          '-bbox', pdf_path, '-'],
                         capture_output=True, text=True).stdout
    pm = re.search(r'<page width="([\d.]+)" height="([\d.]+)"', xml)
    pw, ph = float(pm.group(1)), float(pm.group(2))
    import glob as _g
    subprocess.run(['pdftoppm', '-png', '-r', str(dpi), '-f', str(page),
                    '-l', str(page), pdf_path, out_png + '.raw'],
                   check=True, capture_output=True)
    tmp = sorted(_g.glob(out_png + '.raw*.png'))[0]
    im = Image.open(tmp).convert('RGB')
    sx, sy = im.width / pw, im.height / ph
    dr = ImageDraw.Draw(im)
    words = re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)"', xml)
    n_masked = 0
    for x0, y0, x1, y1 in words:
        x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
        # 跳过巨型框：水印与整幅填充文本框（涂掉会吞掉图面）
        if (x1 - x0) > pw * 0.30 or (y1 - y0) > ph * 0.10:
            continue
        dr.rectangle([x0 * sx - 3, y0 * sy - 3, x1 * sx + 3, y1 * sy + 3], fill='white')
        n_masked += 1
    # 标题条与页脚条整幅涂白（标题常含结论；页脚是版权行）
    dr.rectangle([0, 0, im.width, int(im.height * 0.105)], fill='white')
    dr.rectangle([0, int(im.height * 0.955), im.width, im.height], fill='white')
    im.save(out_png)
    os.remove(tmp)
    return n_masked

if __name__ == '__main__':
    pdf, page, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    print('masked words:', mask_page(pdf, page, out))
