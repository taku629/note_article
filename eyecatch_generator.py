"""
記事タイトル・キーワードから見出し画像（1280×670px）を生成するモジュール

フォント: /usr/share/fonts/opentype/ipafont-gothic/ipag.ttf (IPA Gothic)
サイズ  : 1280×670px (note.com 推奨サイズ)
"""
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
OUTPUT_DIR = Path("/tmp")

# キーワード → カラーテーマ
_THEMES = {
    "AI":         {"bg": [(15, 23, 60), (30, 45, 100)], "accent": (80, 180, 255),  "label": "AI活用"},
    "副業":       {"bg": [(60, 25, 10), (110, 50, 15)], "accent": (255, 160, 50),  "label": "副業"},
    "お金":       {"bg": [(10, 40, 20), (20, 70, 35)],  "accent": (80, 210, 120),  "label": "お金"},
    "奨学金":     {"bg": [(10, 40, 20), (20, 70, 35)],  "accent": (80, 210, 120),  "label": "お金"},
    "節約":       {"bg": [(10, 40, 20), (20, 70, 35)],  "accent": (80, 210, 120),  "label": "お金"},
    "投資":       {"bg": [(10, 40, 20), (20, 70, 35)],  "accent": (80, 210, 120),  "label": "投資"},
    "バイト":     {"bg": [(50, 30, 5),  (90, 55, 10)],  "accent": (255, 200, 60),  "label": "バイト"},
    "就活":       {"bg": [(30, 10, 50), (55, 20, 90)],  "accent": (180, 100, 255), "label": "キャリア"},
    "インターン": {"bg": [(30, 10, 50), (55, 20, 90)],  "accent": (180, 100, 255), "label": "キャリア"},
    "フリーランス":{"bg": [(10, 40, 55),(20, 70, 95)],  "accent": (80, 210, 220),  "label": "フリーランス"},
    "SNS":        {"bg": [(50, 10, 35), (90, 20, 65)],  "accent": (255, 100, 180), "label": "SNS"},
    "YouTube":    {"bg": [(50, 10, 10), (90, 20, 20)],  "accent": (255, 80,  80),  "label": "YouTube"},
    "スキル":     {"bg": [(15, 23, 60), (30, 45, 100)], "accent": (80, 180, 255),  "label": "スキルアップ"},
}
_DEFAULT_THEME = {"bg": [(20, 20, 45), (35, 35, 75)], "accent": (150, 150, 255), "label": "大学生"}


def _pick_theme(keyword: str) -> dict:
    for key, theme in _THEMES.items():
        if key in keyword:
            return theme
    return _DEFAULT_THEME


def _gradient_bg(draw: ImageDraw.Draw, w: int, h: int, c1: tuple, c2: tuple) -> None:
    for y in range(h):
        t = y / h
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


def _wrap_title(title: str, max_chars: int = 18) -> list[str]:
    """タイトルを max_chars 文字前後で折り返す。"""
    if len(title) <= max_chars:
        return [title]
    lines = []
    while title:
        lines.append(title[:max_chars])
        title = title[max_chars:]
    return lines


def generate(title: str, keyword: str = "お金", out_path: str | None = None) -> str:
    """
    記事タイトル・キーワードから見出し画像を生成して保存する。

    引数:
        title   : 記事タイトル
        keyword : テーマキーワード（色テーマの決定に使用）
        out_path: 保存先パス（None の場合 /tmp/eyecatch_{safe_title}.png）

    戻り値:
        保存した PNG ファイルの絶対パス（str）
    """
    W, H = 1280, 670
    theme = _pick_theme(keyword)

    img  = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    # グラデーション背景
    _gradient_bg(draw, W, H, theme["bg"][0], theme["bg"][1])

    # アクセントライン（上部）
    accent = theme["accent"]
    draw.rectangle([(0, 0), (W, 6)], fill=accent)

    # フォント読み込み
    try:
        font_large  = ImageFont.truetype(FONT_PATH, 68)
        font_medium = ImageFont.truetype(FONT_PATH, 40)
        font_small  = ImageFont.truetype(FONT_PATH, 30)
    except Exception:
        font_large = font_medium = font_small = ImageFont.load_default()

    # ラベルバッジ（左上）
    label      = theme["label"]
    badge_pad  = 16
    badge_text_w = draw.textlength(label, font=font_small)
    badge_w    = int(badge_text_w) + badge_pad * 2
    badge_h    = 46
    badge_x, badge_y = 60, 50
    draw.rounded_rectangle(
        [(badge_x, badge_y), (badge_x + badge_w, badge_y + badge_h)],
        radius=12, fill=accent,
    )
    draw.text(
        (badge_x + badge_pad, badge_y + 8),
        label, font=font_small, fill=(255, 255, 255),
    )

    # "大学生 taku の記録" サブテキスト
    sub_text = "大学生 taku の記録"
    draw.text((60, 115), sub_text, font=font_small, fill=(200, 200, 200))

    # タイトル（中央～下寄り）
    lines      = _wrap_title(title, max_chars=18)
    line_h     = 80
    total_h    = len(lines) * line_h
    start_y    = (H - total_h) // 2 + 30

    for i, line in enumerate(lines):
        # テキストシャドウ
        draw.text((62, start_y + i * line_h + 2), line, font=font_large, fill=(0, 0, 0, 120))
        draw.text((60, start_y + i * line_h), line, font=font_large, fill=(255, 255, 255))

    # 下部デコレーションライン
    draw.rectangle([(60, H - 80), (60 + 120, H - 76)], fill=accent)
    draw.text((60, H - 68), "note.com/taku629", font=font_small, fill=(180, 180, 180))

    # 保存
    if out_path is None:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:40]
        out_path = str(OUTPUT_DIR / f"eyecatch_{safe}.png")

    img.save(out_path, "PNG")
    return out_path


if __name__ == "__main__":
    # テスト生成
    test_cases = [
        ("大学2年でインターンに落ちまくった話", "インターン"),
        ("奨学金230万と向き合う大学生の記録", "奨学金"),
        ("AIに勉強計画を立ててもらったら意外と良かった話", "AI"),
        ("副業に興味はあるけど何もできていない話", "副業"),
    ]
    for title, kw in test_cases:
        path = generate(title, kw)
        print(f"生成: {path}")
