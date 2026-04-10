"""
大学生「taku」キャラクター記事生成モジュール

【使用モデル】
  デフォルト: claude-haiku-4-5
  切り替え  : 環境変数 ARTICLE_PROVIDER=claude（現在 claude のみ対応）
              将来的に ARTICLE_PROVIDER=gemini 等を追加予定（DESIGN.md 参照）

【環境変数】
  ANTHROPIC_API_KEY : Claude API キー（必須）
  ARTICLE_PROVIDER  : 記事生成プロバイダー（デフォルト: claude）
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ──────────────────────────────────────────
# 「taku」キャラクター設定（system プロンプト）
# ──────────────────────────────────────────
_TAKU_SYSTEM = """あなたは「taku」という現役大学生のnoteブロガーです。

【キャラクター設定】
- 都内の私立大学に通う2〜3年生
- 一人称は必ず「ぼく」（漢字「僕」は使わない。必ず平仮名）
- 読者: 18〜22歳の大学生
- テーマ領域: お金・SNS・キャリア
- 世界観: 「大学生のうちにやっておけばよかった」を1つでも減らしたい
- 文体: 友達に長文LINEを送るような、丁寧かつフラットな口調
- 体験談ベース、具体的な数字（金額・期間・回数）を積極的に盛り込む"""


# ──────────────────────────────────────────
# パブリック API
# ──────────────────────────────────────────

def generate_article(theme: str) -> tuple[str, str]:
    """
    後方互換: automation.py の既存呼び出しに対応する旧インターフェース。
    theme 文字列から topic_info を組み立てて generate_article_taku に委譲する。
    """
    return generate_article_taku({"topic": theme, "keyword": "お金", "picked_raw": theme})


def generate_article_taku(topic_info: dict) -> tuple[str, str]:
    """
    「taku」キャラクターで note 記事を生成する。

    引数:
        topic_info: trend_selector.select_today_theme() の戻り値
            {
                "topic":      str,  # テーマ（タイトル案）
                "keyword":    str,  # 主要キーワード
                "picked_raw": str,  # トレンドワード（具体例のヒント）
            }

    戻り値:
        (title, body_md)
        - title  : 記事タイトル（# なし）
        - body_md: Markdown 形式の本文（タイトル行を除く）
    """
    provider = os.getenv("ARTICLE_PROVIDER", "claude").lower()

    if provider == "claude":
        return _generate_with_claude(topic_info)
    else:
        print(f"  ⚠ 未対応のプロバイダー '{provider}'。claude にフォールバックします。")
        return _generate_with_claude(topic_info)


def generate_tags(title: str, body: str) -> list[str]:
    """後方互換: automation.py の既存呼び出しに対応する旧インターフェース。"""
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=api_key)
    prompt = (
        f"以下のnote記事に最適なハッシュタグを5個生成してください。\n"
        f"タイトル: {title}\n本文冒頭: {body[:500]}\n\n"
        "【タグ生成ルール】\n"
        "- 1個: 超汎用タグ（「大学生」「副業」「お金」のどれか）\n"
        "- 2個: テーマ関連の中規模タグ\n"
        "- 2個: 記事特有のニッチタグ\n"
        "カンマ区切りで出力（#なし）"
    )
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
    )
    return [t.strip() for t in resp.content[0].text.strip().split(",")][:5]


def quality_check(title: str, body: str, tags: list[str]) -> list[str]:
    """後方互換: automation.py の既存呼び出しに対応する旧インターフェース。"""
    errors = []
    if len(body) < 1500:
        errors.append(f"文字数不足 ({len(body)}字)。1500字以上必要。")
    keywords = ["大学生", "副業", "バイト", "奨学金", "就活", "インターン",
                "資産形成", "節約", "フリーランス", "スキルアップ", "お金"]
    if not any(kw in title for kw in keywords):
        errors.append("タイトルに主要キーワードがありません。")
    if len(tags) < 5:
        errors.append(f"タグ不足 ({len(tags)}個)。5個必要。")
    return errors


# ──────────────────────────────────────────
# 内部実装
# ──────────────────────────────────────────

def _generate_with_claude(topic_info: dict) -> tuple[str, str]:
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY が設定されていません。")

    client  = anthropic.Anthropic(api_key=api_key)
    topic   = topic_info.get("topic", "")
    keyword = topic_info.get("keyword", "お金")
    raw     = topic_info.get("picked_raw", topic)

    # トレンドワードが学生と無関係なら言及しない
    trend_line = (
        f"- トレンドワード（具体例のヒントとして使う）: {raw}\n"
        f"  ※ このワードが大学生の日常と無関係な場合（芸能人名・スポーツ選手・事件など）は\n"
        f"    言及せず、メインテーマとキーワードだけで書くこと。"
    ) if raw and raw != topic else ""

    prompt = f"""以下の指示に従って note 記事を書いてください。

## 今回のテーマ
- メインテーマ: {topic}
- キーワード: {keyword}
{trend_line}

## キャラクターと読者像
- 書き手: 都内大学2〜3年生「ぼく」（一人称は必ず平仮名「ぼく」）
- 読者: 18〜22歳の大学生がメイン。社会人が読んでも「学生のうちに知りたかった」と思える普遍的な学びを入れる。
- テーマ範囲: バイト・副業・節約・就活・SNS・投資入門・奨学金・インターンなど大学生が実体験できる領域に限定する。
- ❌ 書かないこと: 結婚式費用・住宅ローン・育児・老後資金・不動産投資・介護・定年など大学生の日常にないテーマ

## 記事構成（この順番を守る）

### 1. タイトル行
- 1行目に「# タイトル」形式で書く
- 形式は以下のどれか:
  「【実体験】〇〇した結果」「大学生が〇〇してみた」「〇〇選【実際にやった】」

### 2. 導入（約300字）
- 読者の不安やあるある（共感）から入る
- 記事の結論を一文で提示する
- 「最近こんな話題が増えている」という旬な空気感に軽く触れる

### 3. 本文（## 見出しを4〜6個）
各セクションに必ず含める:
- やっていたこと（具体的に）
- なぜうまくいかなかったか / 学んだこと
- 具体的な数字（金額・期間・回数など。例: 月3万円、3ヶ月間、5回試した）

### 4. まとめ
- 共通する本質的な学びを1〜3個に整理
- 「今日から何をすればいいか」を1つだけ具体的に提案

### 5. CTA（最後）
「---」を入れてから、以下の文で締める:
「この記事が役に立ったら、フォローとスキをお願いします！ぼくのnoteでは大学生向けのお金・SNS・キャリアの話を毎日更新しています。」

## 文体・ボリューム
- 一人称は必ず「ぼく」（漢字「僕」は使わない）
- 友達に長文LINEを送るような、丁寧かつフラットな口調
- 文字数目安: 本文4000〜5000字
- Markdown フォーマットで出力する"""

    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=6000,
        system=_TAKU_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_output(resp.content[0].text.strip(), topic)


def _parse_output(full_text: str, fallback_title: str) -> tuple[str, str]:
    """生成テキストから (title, body_md) を抽出する。"""
    lines = full_text.splitlines()
    title = ""
    body_start = 0

    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            body_start = i + 1
            while body_start < len(lines) and lines[body_start].strip() == "":
                body_start += 1
            break

    if not title:
        title = fallback_title
        body_start = 0

    return title, "\n".join(lines[body_start:]).strip()


# ──────────────────────────────────────────
# 単体テスト用
# ──────────────────────────────────────────
if __name__ == "__main__":
    test_info = {
        "topic": "【実体験】大学生がAI副業で月3万稼いだ結果",
        "keyword": "副業",
        "picked_raw": "AI",
    }
    title, body = generate_article_taku(test_info)
    tags = generate_tags(title, body)
    errors = quality_check(title, body, tags)

    print(f"タイトル: {title}")
    print(f"文字数  : {len(body)}字")
    print(f"タグ    : {tags}")
    print(f"エラー  : {errors if errors else 'なし（品質チェック通過）'}")
