"""生成应用图标（多尺寸 PNG / Windows .ico / macOS .icns）。

用途：重绘并输出 `resources/icon.ico` 与 `resources/icon.icns`。
依赖：Pillow（仅生成期使用，不进入运行期依赖）。

用法：
    python tools/gen_icon.py                 # 输出到 resources/
    python tools/gen_icon.py --out DIR       # 输出到指定目录
    python tools/gen_icon.py --preview       # 额外输出 icon_*.png 便于核对

Logo 设计（A 双向数据流）：
- 深色圆角底（与深色主题一致，自上而下微渐变）；
- 上方青绿箭头右向、下方浅灰箭头左向，构成"双向收发"语义；
- 两条箭头上下对称、左右对齐，小尺寸（16px）下仍可一眼辨认。

所有形状按 4 倍超采样绘制后下采样；小尺寸会略微加粗笔画以保证可读性。
"""
import argparse
import os

from PIL import Image, ImageDraw

# 与 core/theme.py 的深色主题令牌保持一致
BG_TOP = (34, 36, 40, 255)      # #222428
BG_BOTTOM = (22, 23, 26, 255)   # #16171a
ACCENT = (45, 212, 191, 255)    # #2dd4bf 主箭头（青绿）
LIGHT = (222, 226, 230, 255)    # #dee2e6 次箭头（浅灰）

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
SS = 4  # 超采样倍数

# 图形几何（64 单位设计稿）
_GRID = 64.0
_ARROW_X0, _ARROW_X1 = 13.0, 51.0   # 箭头水平范围（左右对齐）
_ARROW_Y_TOP, _ARROW_Y_BOTTOM = 23.0, 41.0
_HEAD_LEN = 9.0                      # 箭头头部长度
_HEAD_HALF = 7.0                     # 箭头头部半高
_SHAFT_W = 6.5                       # 箭杆宽度


def _rounded_bg(size: int) -> Image.Image:
    """圆角方形背景（自上而下微渐变）。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        grad.putpixel((0, y), tuple(
            int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(4)
        ))
    grad = grad.resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255
    )
    img.paste(grad, (0, 0), mask)
    return img


def draw_icon(size: int) -> Image.Image:
    """按目标尺寸绘制图标（内部超采样后下采样）。"""
    s = size * SS

    def u(v: float) -> int:
        """按 64 单位设计稿换算到当前画布。"""
        return int(round(v / _GRID * s))

    img = _rounded_bg(s)
    d = ImageDraw.Draw(img)

    # 小尺寸略微加粗，抵消下采样带来的笔画变细
    boost = 1.12 if size <= 20 else 1.0
    shaft = max(1, int(round(u(_SHAFT_W) * boost)))
    half = u(_HEAD_HALF) * (boost if size <= 20 else 1.0)
    head = u(_HEAD_LEN)

    def arrow(y: float, to_right: bool, color):
        y = u(y)
        if to_right:
            x_tail, x_head = u(_ARROW_X0), u(_ARROW_X1) - head
            tip = u(_ARROW_X1)
        else:
            x_tail, x_head = u(_ARROW_X1), u(_ARROW_X0) + head
            tip = u(_ARROW_X0)
        d.line([x_tail, y, x_head, y], fill=color, width=shaft)
        # 圆头尾端
        r = shaft / 2.0
        d.ellipse([x_tail - r, y - r, x_tail + r, y + r], fill=color)
        # 三角形箭头
        d.polygon([(tip, y), (x_head, y - half), (x_head, y + half)], fill=color)

    arrow(_ARROW_Y_TOP, True, ACCENT)     # 上：发送（右向）
    arrow(_ARROW_Y_BOTTOM, False, LIGHT)  # 下：接收（左向）

    return img.resize((size, size), Image.LANCZOS)


def main():
    parser = argparse.ArgumentParser(description="生成应用图标")
    default_out = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources"
    )
    parser.add_argument("--out", default=default_out, help="输出目录（默认 resources/）")
    parser.add_argument(
        "--preview", action="store_true", help="额外输出 icon_*.png 预览（默认不输出）"
    )
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    # Windows .ico：逐尺寸提供精确位图
    frames = [draw_icon(s) for s in ICO_SIZES]
    ico_path = os.path.join(args.out, "icon.ico")
    frames[-1].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=frames[:-1],
    )
    print(f"  {ico_path}  sizes={ICO_SIZES}")

    # macOS .icns
    icns_path = os.path.join(args.out, "icon.icns")
    try:
        draw_icon(1024).save(icns_path, format="ICNS")
        print(f"  {icns_path}  (from 1024px)")
    except Exception as e:  # icns 写入失败不影响 Windows 构建
        print(f"  skip icns: {e}")

    # 可选：预览 PNG（便于人工核对，默认不输出以免污染 resources/）
    if args.preview:
        for s in (16, 32, 64, 256):
            draw_icon(s).save(os.path.join(args.out, f"icon_{s}.png"))
        print(f"  预览 PNG 已输出到 {args.out}")


if __name__ == "__main__":
    main()

