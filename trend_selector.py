"""
トレンド取得・スコアリング・テーマ選定モジュール

【取得元】
  Google Trends JP の RSS フィード
  URL: https://trends.google.co.jp/trending/rss?geo=JP
  形式: RSS 2.0 XML → <item><title> をリストとして取得（約20件）

【スコアリング】
  PRIORITY_KEYWORDS（お金・SNS・キャリア領域）との一致数でスコアを計算。
  スコアが高いトレンドワードを優先的に Claude に渡してテーマを選定する。

【テーマ選定】
  上位トレンドを claude-haiku-4-5 に渡し、大学生向けタイトル案を1件生成する。
  API が使えない場合はルールベースのフォールバックを使う。

【環境変数】
  ANTHROPIC_API_KEY: Claude API キー（.env から読み込む）
"""
import os
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ──────────────────────────────────────────
# 優先キーワード（大学生×お金・SNS・キャリア）
# ──────────────────────────────────────────
PRIORITY_KEYWORDS = [
    "お金", "バイト", "副業", "就活", "インターン", "SNS",
    "フォロワー", "投資", "FX", "仮想通貨", "節約", "奨学金",
    "フリーランス", "スキル", "転職", "起業", "稼ぐ", "貯金",
    "資産", "YouTube", "TikTok", "Instagram", "X",
]

# フォールバック用デフォルトトピック候補
_DEFAULT_TOPICS = [
    "大学生の節約術5選【実際にやった】",
    "大学生がバイトと副業を両立してみた話",
    "就活と副業を両立した大学生の1日ルーティン",
    "大学生が投資を始めて6ヶ月で学んだこと",
    "【実体験】SNSフォロワー1000人になるまでにやったこと",
]


# ──────────────────────────────────────────
# パブリック API
# ──────────────────────────────────────────

def get_google_trends(geo: str = "JP", n: int = 30) -> list[str]:
    """
    Google Trends JP の RSS からトレンドワードを最大 n 件返す。
    失敗時は空リストを返す（呼び出し元でフォールバック）。
    """
    url = f"https://trends.google.co.jp/trending/rss?geo={geo}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        return [item.find("title").text for item in root.findall(".//item")][:n]
    except Exception as e:
        print(f"  ⚠ Google Trends 取得失敗: {e}")
        return []


def score_trend(trend: str) -> int:
    """トレンドワードに PRIORITY_KEYWORDS が何個含まれるかでスコアを返す。"""
    return sum(1 for kw in PRIORITY_KEYWORDS if kw in trend)


def rank_trends(trends: list[str]) -> list[tuple[str, int]]:
    """
    トレンドリストをスコア降順でソートして (word, score) のリストを返す。
    スコア 0 のものも含めて返す（使用側で足切りを判断する）。
    """
    return sorted(((t, score_trend(t)) for t in trends), key=lambda x: x[1], reverse=True)


def select_theme(trends: list[str]) -> str:
    """後方互換: automation.py の既存呼び出しに対応する旧インターフェース。"""
    return select_today_theme(trends)["topic"]


def select_today_theme(trends: list[str] | None = None) -> dict:
    """
    今日のテーマを1件選定して辞書で返す。

    引数:
        trends: 事前に取得済みのトレンドリスト。None の場合は内部で取得する。

    戻り値:
        {
            "topic":      str,        # 選定されたテーマ（タイトル案）
            "keyword":    str,        # テーマに含まれる最初の PRIORITY_KEYWORD
            "picked_raw": str,        # スコアが最も高かったトレンドワード（なければ空）
            "score":      int,        # そのスコア
            "raw_trends": list[str],  # 取得した全トレンドワード
        }
    """
    if trends is None:
        trends = get_google_trends()

    ranked     = rank_trends(trends) if trends else []
    picked_raw = ranked[0][0] if ranked else ""
    score      = ranked[0][1] if ranked else 0

    # スコアが1以上のトレンドだけを候補にする。
    # スコア0（大学生テーマと無関係）しかない場合はトレンドを無視してデフォルト候補を使う。
    relevant = [w for w, s in ranked if s >= 1]
    candidates = relevant[:10] if relevant else _DEFAULT_TOPICS[:5]

    topic   = _llm_select_topic(candidates, use_trends=bool(relevant))
    keyword = _extract_keyword(topic)

    return {
        "topic":      topic,
        "keyword":    keyword,
        "picked_raw": picked_raw,
        "score":      score,
        "raw_trends": trends,
    }


# ──────────────────────────────────────────
# 内部ヘルパー
# ──────────────────────────────────────────

def _llm_select_topic(candidates: list[str], use_trends: bool = True) -> str:
    """Claude にテーマを1件選ばせる。失敗時はルールベースフォールバック。"""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return candidates[0] if candidates else _DEFAULT_TOPICS[0]

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    if use_trends:
        source_label = "今日のトレンドワード（大学生テーマと関連があるものを絞り込み済み）"
        source_note  = (
            "トレンドワードを「大学生が実際に体験できる切り口」に変換してタイトルを作ること。\n"
            "変換できない場合は無視して、下記の「大学生テーマの定番候補」から選ぶこと。"
        )
    else:
        source_label = "大学生テーマの定番候補"
        source_note  = "トレンドは関係ないので無視し、下記の候補から最も旬な1件を選ぶこと。"

    prompt = (
        "あなたは現役大学生ブロガー「taku」のテーマ選定担当です。\n\n"
        f"【{source_label}】\n"
        + "\n".join(f"- {t}" for t in candidates) + "\n\n"
        "【選定ルール】\n"
        f"1. {source_note}\n"
        "2. テーマは「18〜22歳の大学生が実際に体験できること」に限定する。\n"
        "   ✅ OK例: バイト、副業、就活、節約、投資入門、SNS運用、奨学金、インターン\n"
        "   ❌ NG例: 結婚式費用、住宅ローン、育児、老後資金、不動産投資、介護、定年退職\n"
        "3. 大学生の実体験ベースで書けるが、読んだ社会人にも「あのころ知りたかった」と\n"
        "   思わせる普遍的な学びを含むテーマにすること。\n"
        "4. タイトル形式は以下のどれか:\n"
        "   「【実体験】〇〇した結果」「大学生が〇〇してみた」「〇〇選【実際にやった】」\n"
        "5. 出力はタイトルのみ1行（説明文・コメント不要）"
    )
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"  ⚠ テーマ選定失敗: {e}")
        return candidates[0] if candidates else _DEFAULT_TOPICS[0]


def _extract_keyword(topic: str) -> str:
    """テーマ文字列から最初にマッチした PRIORITY_KEYWORD を返す。なければ「お金」。"""
    for kw in PRIORITY_KEYWORDS:
        if kw in topic:
            return kw
    return "お金"


# ──────────────────────────────────────────
# 単体テスト用
# ──────────────────────────────────────────
if __name__ == "__main__":
    trends = get_google_trends()
    print(f"取得トレンド数: {len(trends)}")
    ranked = rank_trends(trends)
    print("スコア上位5件:")
    for word, score in ranked[:5]:
        print(f"  {score}点: {word}")

    info = select_today_theme(trends)
    print(f"\n選定テーマ  : {info['topic']}")
    print(f"キーワード  : {info['keyword']}")
    print(f"トレンドraw : {info['picked_raw']} (score={info['score']})")
