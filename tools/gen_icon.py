"""生成应用图标（多尺寸 PNG / Windows .ico / macOS .icns）。

用途：重绘并输出 `resources/icon.ico` 与 `resources/icon.icns`。
依赖：Pillow（仅生成期使用，不进入运行期依赖）。

用法：
    python tools/gen_icon.py            # 输出到 resources/
    python tools/gen_icon.py --out DIR  # 输出到指定目录

设计：深色圆角底 + 左侧串口连接器（浅灰）+ 右侧递增信号柱（青绿强调色）。
所有形状按 4 倍超采样绘制后下采样，保证小尺寸边缘平滑。
"""
import argparse
import os

from PIL import Image, ImageDraw

# 与 core/theme.py 的深色主题令牌保持一致
BG_TOP = (32, 33, 36, 255)      # #202124
BG_BOTTOM = (23, 24, 26, 255)   # #17181a
PLUG = (215, 217, 221, 255)     # #d7d9dd
ACCENT = (45, 212, 191, 255)    # #2dd4bf
ACCENT_DIM = (20, 184, 166, 255)

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]
SS = 4  # 超采样倍数


def _rounded_bg(size: int) -> Image.Image:
    """圆角方形背景（自上而下微渐变）。"""
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
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
    bg.paste(grad, (0, 0), mask)
    return bg


def draw_icon(size: int) -> Image.Image:
    """按目标尺寸绘制图标（内部 4 倍超采样后下采样）。"""
    s = size * SS
    img = _rounded_bg(s)
    d = ImageDraw.Draw(img)

    def u(v: float) -> int:
        """按 64 单位设计稿换算到当前画布。"""
        return int(round(v / 64.0 * s))

    # ---- 左侧：串口连接器（圆角体 + 两根插针）----
    d.rounded_rectangle(
        [u(11), u(24), u(28), u(40)], radius=u(3), fill=PLUG
    )
    d.rounded_rectangle([u(28), u(29), u(36), u(32)], radius=u(1.2), fill=PLUG)
    d.rounded_rectangle([u(28), u(34), u(36), u(37)], radius=u(1.2), fill=PLUG)

    # ---- 连线（连接器 → 信号柱）----
    d.line([u(34), u(33), u(40), u(33)], fill=ACCENT_DIM, width=max(1, u(1.6)))

    # ---- 右侧：递增信号柱 ----
    bars = [(44, 40, 20), (49, 40, 13), (54, 40, 6)]  # (x, bottom, top)
    for x, bottom, top in bars:
        d.rounded_rectangle(
            [u(x), u(top), u(x + 4), u(bottom)], radius=u(1.6), fill=ACCENT
        )

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
        big = draw_icon(1024)
        big.save(icns_path, format="ICNS")
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
