# -*- coding: utf-8 -*-
"""
build_assets.py —— 从 MiniMax Code 官方图标提取主视觉资产
=========================================================
只用官方安装目录里的 icon.icns（**只读**），产出到本项目 assets/：

  mascot.png         吉祥物本体（软抠白底 + 烘焙立体光影）
  mascot_tray.png    托盘小图标（64px）
  mascot_shadow.png  预烘焙投影（下方浓、上方淡的落地阴影）
  mascot_glow.png    预烘焙外发光（品牌蓝，把主体从背景里托起来）

轮廓与配色直接来自官方图标，不手工描形；但在官方像素之上会叠一层很轻的
立体光影（顶部轮廓光 + 底部暗部），否则桌面上看是一张「贴纸」而不是一个
立体的角色。

用法：  python build_assets.py
"""
import io
import os
import struct
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
RES = r"C:\Users\23154\AppData\Local\Programs\MiniMax Code\resources\resources"
ICNS = os.path.join(RES, "icon.icns")
ICO = os.path.join(RES, "icon.ico")

ICNS_TYPES = {
    b"icp4": 16, b"icp5": 32, b"icp6": 64, b"ic07": 128, b"ic08": 256,
    b"ic09": 512, b"ic10": 1024, b"ic11": 32, b"ic12": 64, b"ic13": 256,
    b"ic14": 512, b"ic05": 32, b"ic04": 16,
}


def from_icns(path):
    with open(path, "rb") as f:
        data = f.read()
    off, found = 8, []
    while off + 8 <= len(data):
        typ, size = struct.unpack(">4sI", data[off:off + 8])
        if size < 8 or off + size > len(data):
            break
        blob = data[off + 8:off + size]
        if ICNS_TYPES.get(typ) and blob[:8] == b"\x89PNG\r\n\x1a\n":
            found.append((ICNS_TYPES[typ], blob))
        off += size
    found.sort(reverse=True)
    return found[0][1] if found else None


def from_ico(path):
    with open(path, "rb") as f:
        data = f.read()
    count = struct.unpack("<H", data[4:6])[0]
    best = None
    for i in range(count):
        w, _h, _n, _r, _p, _b, size, o = struct.unpack("<BBBBHHII",
                                                        data[6 + i * 16:22 + i * 16])
        blob = data[o:o + size]
        if blob[:8] == b"\x89PNG\r\n\x1a\n" and (best is None or w > best[0]):
            best = (w or 256, blob)
    return best[1] if best else None


# ---- 抠图参数（源图 1024px）--------------------------------------------
# 粗掩码阈值：分数低于它算「白底候选」，再从裁切框四边 flood。
#
# 注意不能用「到纯白的欧氏距离」——吉祥物底部那圈浅青 (185,251,255)
# 距白只有 70，而它直接贴着底板，按距离判会被 flood 灌进去，把脚啃掉。
# 改用「色度 + 亮度差」的组合分数：
#     score = (max-min) + (255-luma) * 1.6
# 白底 (255,255,255) = 0；边缘混色 (223,239,255) = 50；
# 吉祥物浅青 (185,251,255) = 115；主体蓝 (0,220,255) = 380。
# 阈值 70 落在 50 和 115 之间，两侧都有富余。
PLATE_TOL = 70
# 过渡带宽度（像素）：在粗掩码两侧各取这么多圈做精确解算
BAND = 2
# 带内颜色扩散迭代次数：3x3 邻域，扩散 BAND 圈足够
PROP_ITERS = 7


def _plate_score(r, g, b):
    """越小越像白底。"""
    chroma = max(r, g, b) - min(r, g, b)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return chroma + (255.0 - lum) * 1.6


def _shift(img, dx, dy):
    """平移（不循环回绕，移出去的部分填 0）。"""
    out = Image.new(img.mode, img.size, 0)
    out.paste(img, (dx, dy))
    return out


def key_out(im):
    """软抠掉白色圆角底板，还原抗锯齿边缘。

    原来的做法是硬判：(b - r) > 10 就整像素保留、否则 alpha 直接置 0。
    两个后果：

      1. 吉祥物压在白底上，边缘那一两像素是「主体和底板混出来」的浅蓝
         （如 (223,239,255)，b-r=32 > 10），于是整片被判成主体、**以不透明
         近白色留在图里**——放到浅色桌面上就是一圈白噪点；
      2. 输出里半透明像素数为 0，边缘是硬的，缩放后必然锯齿。

    现在是「粗掩码 + 局部 matting」：

      1. 用色度/亮度分数找出白底候选，从裁切框四边 flood 出一块底板。
         flood 只看连通性，所以主体内部那些浅色高光不会被误当成底板；
      2. 取粗掩码两侧各 BAND 像素做过渡带，在带内把纯主体色向边缘扩散；
      3. 逐像素解 obs = a·m + (1-a)·255 得到真实覆盖度 a，再反解出主体
         颜色 m。边缘于是既连续又还原成了主体本来的颜色，而不是一层
         被白底染过的浅蓝。

    只有第 1 步是近似的；第 3 步是逐像素精确解，所以过渡带落在哪里都
    不影响边缘质量。
    """
    rgba = im.convert("RGBA")
    box = rgba.getchannel("A").getbbox()
    if box:
        rgba = rgba.crop(box)
    w, h = rgba.size

    # 官方图标是「白底板 + 吉祥物」压在一起（不透明像素里一半以上近白），
    # 不能直接用自带 alpha。先把透明区压到白底色上再处理。
    flat = Image.new("RGB", (w, h), (255, 255, 255))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    fp = flat.load()

    # ---- 1) 粗掩码 + flood ----
    cand = Image.new("L", (w, h), 0)
    cp = cand.load()
    for y in range(h):
        for x in range(w):
            r, g, b = fp[x, y]
            if _plate_score(r, g, b) < PLATE_TOL:
                cp[x, y] = 255
    for x in range(w):
        for y in (0, h - 1):
            if cp[x, y] == 255:
                ImageDraw.floodfill(cand, (x, y), 128)
    for y in range(h):
        for x in (0, w - 1):
            if cp[x, y] == 255:
                ImageDraw.floodfill(cand, (x, y), 128)
    plate = cand.point(lambda v: 255 if v == 128 else 0)

    k = 2 * BAND + 1
    rough = ImageChops.invert(plate)                       # 粗略的主体
    known = rough.filter(ImageFilter.MinFilter(k))         # 腐蚀：纯主体
    grown = rough.filter(ImageFilter.MaxFilter(k))         # 膨胀：含带
    bandm = ImageChops.subtract(grown, known)
    kp, bp = known.load(), bandm.load()

    # ---- 2) 带内扩散纯主体色 ----
    nbrs = ((-1, -1), (0, -1), (1, -1), (-1, 0),
            (1, 0), (-1, 1), (0, 1), (1, 1))
    cur = {}
    pts = []
    for y in range(h):
        for x in range(w):
            if bp[x, y]:
                pts.append((x, y))
                if kp[x, y]:
                    cur[(x, y)] = fp[x, y][:3]
    for _ in range(PROP_ITERS):
        nxt = dict(cur)
        for (x, y) in pts:
            if (x, y) in cur:
                continue
            r = g = b = n = 0
            for dx, dy in nbrs:
                c = cur.get((x + dx, y + dy))
                if c is not None:
                    r += c[0]
                    g += c[1]
                    b += c[2]
                    n += 1
            if n:
                nxt[(x, y)] = (r // n, g // n, b // n)
        cur = nxt

    # ---- 3) 逐像素解覆盖度并反解主体色 ----
    out = Image.new("RGBA", (w, h))
    op = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b = fp[x, y]
            if bp[x, y]:
                mc = cur.get((x, y))
                if not mc:
                    continue                       # 没扩散到，按全透明处理
                num = den = 0.0
                for oc, mcv in ((r, mc[0]), (g, mc[1]), (b, mc[2])):
                    d = 255.0 - mcv
                    if d > 12.0:                 # 该通道区分度够才参与
                        num += (255.0 - oc) / d
                        den += 1.0
                a = (num / den) if den else 1.0
                a = 0.0 if a < 0.0 else (1.0 if a > 1.0 else a)
                if a <= 0.004:
                    continue
                kk = 1.0 - a
                op[x, y] = (
                    max(0, min(255, int(round((r - 255.0 * kk) / a)))),
                    max(0, min(255, int(round((g - 255.0 * kk) / a)))),
                    max(0, min(255, int(round((b - 255.0 * kk) / a)))),
                    max(0, min(255, int(round(a * 255)))))
            elif kp[x, y]:
                op[x, y] = (r, g, b, 255)
            # 其余留在 (0,0,0,0)

    box = out.getbbox()
    return out.crop(box) if box else out


def add_depth(m, bot=6, bot_alpha=82):
    """烘焙立体暗部：沿下边界压暗，让身体有体积而不是一张平贴纸。

    这里**故意不加顶部轮廓光**。试过：沿上边界打亮确实有「受光」的错觉，
    但在 596px 的图上是一条 2~3px 的浅色带，缩到桌宠实际显示的 101px 时
    仍然看得见，落在浅色桌面上就是一圈白边——正好是这次要消灭的东西。
    立体感改由「落地阴影 + 底部暗部 + 极弱外发光」三层来撑。
    """
    a = m.getchannel("A")
    # 下边界窄带 = alpha 减去「自己上移 bot 像素后」的 alpha
    band = ImageChops.subtract(a, _shift(a, 0, -bot))
    band = band.filter(ImageFilter.GaussianBlur(2.0)).point(
        lambda v: int(v * bot_alpha / 255))
    lo = Image.new("RGBA", m.size, (5, 58, 116, 0))
    lo.putalpha(band)
    return Image.alpha_composite(m, lo)


def build_shadow(m, spread=38, blur=18, opacity=128):
    """柔和投影，**越靠下越浓**。

    原来那一版是把主体 alpha 对称地模糊一下，等于沿整个轮廓加一圈均匀的
    光晕，看着像描边而不是影子。加上垂直密度梯度之后才有「压在桌面上」
    的落地感（向下偏移由绘制端完成，见 minimax_pet.MascotFace.paintEvent）。
    """
    a = m.getchannel("A")
    pad = spread
    c = Image.new("L", (m.width + pad * 2, m.height + pad * 2), 0)
    c.paste(a, (pad, pad))
    c = c.filter(ImageFilter.GaussianBlur(blur))
    grad = Image.linear_gradient("L").resize(c.size)
    c = ImageChops.multiply(c, grad.point(lambda v: 92 + (v * 163) // 255))
    c = c.point(lambda v: int(v * opacity / 255))
    sh = Image.new("RGBA", c.size, (8, 40, 74, 0))
    sh.putalpha(c)
    return sh


def build_glow(m, spread=30, opacity=26):
    """品牌蓝外发光：把主体从背景里托起来。

    强度压得很低（26/255）。再亮一点，深色背景下好看、浅色桌面上就会糊成
    一圈灰印子，反而比不做还脏。
    """
    a = m.getchannel("A")
    pad = spread
    c = Image.new("L", (m.width + pad * 2, m.height + pad * 2), 0)
    c.paste(a, (pad, pad))
    c = c.filter(ImageFilter.GaussianBlur(spread * 0.55))
    c = c.point(lambda v: int((v / 255.0) ** 1.7 * opacity))
    g = Image.new("RGBA", c.size, (0, 145, 255, 0))
    g.putalpha(c)
    return g


def main():
    os.makedirs(ASSETS, exist_ok=True)
    blob = from_icns(ICNS) if os.path.exists(ICNS) else None
    src_desc = "icon.icns"
    if not blob:
        blob, src_desc = from_ico(ICO), "icon.ico"
    if not blob:
        print("找不到官方图标，无法生成主视觉资产")
        return 1
    src = Image.open(io.BytesIO(blob))
    print("源：%s  %s" % (src_desc, src.size))

    cut = key_out(src)
    print("  抠图      %s  半透明像素 %d" % (
        cut.size, sum(1 for v in cut.getchannel("A").histogram()[1:255])))

    mascot = add_depth(cut)
    mascot.save(os.path.join(ASSETS, "mascot.png"))
    print("  assets/mascot.png        %s (+底部暗部)" % (mascot.size,))

    # 残留在图里的近白不透明像素 = 白噪点，必须为 0
    px = mascot.load()
    w, h = mascot.size
    noise = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 255 and r > 200 and g > 200 and b > 200:
                noise += 1
    print("  白噪点自检：不透明近白像素 %d %s" % (noise, "OK" if noise == 0 else "!! 仍有残留"))

    tray = mascot.copy()
    tray.thumbnail((64, 64), Image.LANCZOS)
    tray.save(os.path.join(ASSETS, "mascot_tray.png"))
    print("  assets/mascot_tray.png   %s" % (tray.size,))

    build_shadow(mascot).save(os.path.join(ASSETS, "mascot_shadow.png"))
    print("  assets/mascot_shadow.png (预烘焙投影，下浓上淡)")

    build_glow(mascot).save(os.path.join(ASSETS, "mascot_glow.png"))
    print("  assets/mascot_glow.png   (预烘焙外发光)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
