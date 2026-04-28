"""
記事生成モジュール

アカウントA（taku）  : お金・バイト・就活・AI活用の試行錯誤をする大学2年生
アカウントB（engine）: AIと自動化ツールで大学生活・副業を仕組み化している大学生

【使用モデル】claude-haiku-4-5（ARTICLE_PROVIDER 環境変数で切り替え可）
【環境変数】ANTHROPIC_API_KEY / ARTICLE_PROVIDER
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ──────────────────────────────────────────
# アカウントA「taku」ペルソナ
# ──────────────────────────────────────────
_TAKU_SYSTEM = """あなたは「taku」という現役大学2年生のnoteブロガーです。

【キャラクター設定】
- 都内の私立大学に通う2年生。本選考・内定・フリーランス受注などの実績はまだない
- 一人称は必ず「ぼく」（漢字「僕」は使わない。必ず平仮名）
- 読者: 18〜24歳の大学生
- テーマ領域: お金・AI活用・キャリア準備・バイト・副業（試行錯誤中）
- 世界観: 「まだ結果は出ていないけど、試行錯誤しながら前に進んでいる」
- 文体: 友達に長文LINEを送るような、丁寧かつフラットな口調
- 体験談ベース、具体的な数字（金額・期間・回数）を入れるが、実績を誇張しない
- 成功したことより「失敗したこと・気づいたこと・まだ途中なこと」を正直に書く"""

# ──────────────────────────────────────────
# アカウントB「engine」ペルソナ
# ──────────────────────────────────────────
_ENGINE_SYSTEM = """あなたは現役大学生のnoteブロガーです。

【キャラクター設定】
- AIと自動化ツールを使って大学生活・勉強・副業を仕組み化することに興味がある大学生
- 一人称は必ず「ぼく」（漢字「僕」は使わない。必ず平仮名）
- 読者: 「AIや自動化に興味はあるけど何から始めればいいかわからない」大学生・若者
- テーマ領域: LLM活用・Pythonスクリプト・自動化ツール・効率化・副業の仕組み化
- 世界観: 「完成した仕組みを紹介するのではなく、動かしながら失敗・改善している現場」
- 文体: 技術的すぎず、でも具体的。「こんなの作ってみたよ」とLINEで送るようなトーン
- 実際に動かしたもの・試したことだけを書く。未検証の情報は書かない
- 「すごい成果」より「明日から試せる小さな仕組み」を届ける"""

# アカウントB用デフォルトトピック候補
_ENGINE_DEFAULT_TOPICS = [
    "noteの記事をAIで自動生成して毎日投稿する仕組みを作ってみた話",
    "Claudeにタスク管理を丸投げしてみたら思ったより機能した話",
    "大学の講義ノートをLLMで整理したら勉強の仕方が変わった",
    "Pythonスクリプトで毎朝のニュース収集を自動化してみた",
    "ChatGPTとClaudeを1週間使い分けて気づいた違いと使い分け方",
    "AIツールだけで副業の情報収集フローを自動化してみた実験",
    "n8nで作業を自動化しようとしたら思ったより難しかった話と解決策",
    "LLMにES添削をさせたら『ぼくっぽくない文章』になってきた話",
    "無料AIツールだけで1週間作業してみた正直な結果",
    "Notionと自動化ツールで生活費管理を仕組み化してみた",
    "プロンプトを工夫したら出力の質が上がった話と具体的なコツ",
    "AIに自己分析させてみたら想像と違う結果が出た話",
    "大学の課題にAIを使ってみて気づいた『使っていい場面・ダメな場面』",
    "Pythonを勉強してないぼくがAIにコードを書かせて自動化するまでの話",
    "毎日AIと会話して気づいた、上手に使う人と使えない人の違い",
]


# ──────────────────────────────────────────
# パブリック API
# ──────────────────────────────────────────

def generate_article(theme: str) -> tuple[str, str]:
    """後方互換: theme 文字列から topic_info を組み立てて generate_article_taku に委譲。"""
    return generate_article_taku({"topic": theme, "keyword": "お金", "picked_raw": theme})


def generate_article_for_account(topic_info: dict, account: str = "a") -> tuple[str, str]:
    """アカウントに応じた記事生成器を呼び分けるエントリポイント。"""
    if account == "b":
        return generate_article_engine(topic_info)
    return generate_article_taku(topic_info)


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


def generate_article_engine(topic_info: dict) -> tuple[str, str]:
    """アカウントB「engine」ペルソナで note 記事を生成する。"""
    provider = os.getenv("ARTICLE_PROVIDER", "claude").lower()
    if provider == "claude":
        return _generate_engine_with_claude(topic_info)
    print(f"  ⚠ 未対応のプロバイダー '{provider}'。claude にフォールバックします。")
    return _generate_engine_with_claude(topic_info)


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

## 書き手と読者の前提
- 書き手: 都内大学2年生「ぼく」（一人称は必ず平仮名「ぼく」）
- 本選考・内定・フリーランス受注などの実績はまだない。試行錯誤の途中にいる
- 読者: 18〜24歳の大学生。「同じ立場の人が試してみた話」として届ける
- テーマ範囲: AI活用・バイト・副業試行中・奨学金・節約・就活準備・インターンなど大学生が実体験できる領域
- ❌ 書かないこと: 結婚費用・住宅ローン・育児・老後資金・不動産投資・定年・内定報告・月〇万達成

## 記事構成（この順番を守る）

### 1. タイトル行
- 1行目に「# タイトル」形式で書く
- 成功報告型ではなく「試行錯誤・正直な記録・失敗」型にする:
  「〇〇してみたら〇〇だった話」「〇〇が何もなかった話」「〇〇の正直な記録」

### 2. 導入（約300字）
- 読者の不安・あるある（共感）から入る。「ぼくも同じだった」という等身大の入り方
- 「この記事で伝えること」を一文で提示する（成功報告ではなく、試してみた話として）

### 3. 本文（## 見出しを4〜6個）
各セクションに必ず含める:
- 試したこと・やったこと（具体的に。何をどう試したか）
- 正直な結果（うまくいったこと・うまくいかなかったこと。両方書く）
- 具体的な数字（金額・期間・回数など。例: 月3万円のバイト代、3ヶ月間、5回落ちた）
- ❌ 「〇〇で稼いだ」「〇〇を達成した」など断言する成功表現は使わない

### 4. まとめ
- 試してみて気づいたこと・学んだことを1〜3個に整理
- 「読者が明日から試せること」を1つだけ具体的に提案

### 5. CTA（最後）
「---」を入れてから、以下の文で締める:
「最後まで読んでくれてありがとう。ぼくのnoteでは、こういう「大学生のお金・AI活用・キャリア準備」の話を定期的に書いています。興味あれば他の記事もみてください。」

## 文体・ボリューム
- 一人称は必ず「ぼく」（漢字「僕」は使わない）
- 友達に長文LINEを送るような、丁寧かつフラットな口調
- 過剰な成功アピール・誇張・断言はしない。「〜だと思う」「〜な気がする」でOK
- 文字数目安: 本文4000〜5000字
- Markdown フォーマットで出力する"""

    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=6000,
        system=_TAKU_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_output(resp.content[0].text.strip(), topic)


def _generate_engine_with_claude(topic_info: dict) -> tuple[str, str]:
    """アカウントB用記事を Claude で生成する。"""
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY が設定されていません。")

    import random
    client  = anthropic.Anthropic(api_key=api_key)
    topic   = topic_info.get("topic", "")
    raw     = topic_info.get("picked_raw", topic)

    # トレンドが大学生×AI文脈と無関係なら無視してデフォルトトピックを使う
    ai_keywords = ["AI", "ChatGPT", "Claude", "LLM", "自動化", "プログラム",
                   "アプリ", "テクノロジー", "デジタル", "ツール", "効率"]
    use_trend = any(kw in (raw + topic) for kw in ai_keywords)

    if use_trend:
        base_topic = topic
    else:
        # デフォルトトピックからランダムに1件選ぶ（連続重複を避けるため）
        base_topic = random.choice(_ENGINE_DEFAULT_TOPICS)

    prompt = f"""以下の指示に従って note 記事を書いてください。

## 今回のテーマ
{base_topic}

## 書き手と読者の前提
- 書き手: AIと自動化ツールを試している大学生「ぼく」（一人称は必ず平仮名「ぼく」）
- 読者: AIや自動化に興味はあるが何から始めればいいかわからない大学生・若者
- 「完成した成果物の紹介」ではなく「作りながら失敗・気づいた話」として書く
- ❌ 書かないこと: 月〇万稼いだ・エンジニア転職・フリーランス独立・大手採用

## 記事構成（この順番を守る）

### 1. タイトル行
- 1行目に「# タイトル」形式で書く
- 必ず以下のどれかのキーワードをタイトルに含める:
  「AI」「自動化」「LLM」「Claude」「ChatGPT」「仕組み化」「効率化」「ツール」
- タイトル形式:「〇〇をAIで自動化してみた話」「LLMに〇〇をやらせたら〇〇だった」
  「〇〇を仕組み化したら〇〇が変わった話」「AIで〇〇した正直な結果」

### 2. 導入（約300字）
- 「自分もAI使いたいけど何から始めればいいかわからない」という読者の悩みから入る
- 「ぼくが実際に試してみたことを正直に書く」という宣言で締める

### 3. 本文（## 見出しを4〜6個）
各セクションに必ず含める:
- 使ったツール・方法を具体的に（ツール名・コマンド・手順を惜しまず書く）
- 実際にやってみた結果（うまくいったこと・ハマったこと。両方書く）
- 具体的な数字（時間・回数・コスト。例: 30分かかってた作業が3分に・週5回試した）
- 「ここが難しかった」「ここは意外と簡単だった」という正直な感想

### 4. まとめ
- 試してみて気づいたこと・学んだことを1〜3個に整理
- 「読者が明日から試せる最初の1ステップ」を具体的に1つだけ提案

### 5. CTA（最後）
「---」を入れてから、以下の文で締める:
「最後まで読んでくれてありがとう。ぼくのnoteでは、AIと自動化を使って大学生活や副業を仕組み化していく話を定期的に書いています。興味があれば他の記事もみてください。」

## 文体・ボリューム
- 一人称は必ず「ぼく」（漢字「僕」は使わない）
- 技術的すぎず、でも具体的。「こんなの作ってみたよ」とLINEで送るような口調
- 誇張・断言・実績自慢はしない。「〜だと思う」「〜な気がする」でOK
- 文字数目安: 本文4000〜5000字
- Markdown フォーマットで出力する"""

    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=6000,
        system=_ENGINE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_output(resp.content[0].text.strip(), base_topic)


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
