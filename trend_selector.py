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

# フォールバック用デフォルトトピック候補（大学2年・等身大方針）
_DEFAULT_TOPICS = [
    # AI活用（ツール・自動化・実験）
    "Claudeに勉強計画を立ててもらったら意外とちゃんと機能した話",
    "AIツールを使いこなすだけで「バイト以外の選択肢」が増えた気がする話",
    "大学生がnoteを自動投稿する仕組みを1ヶ月回してみた正直な結果",
    "ChatGPTで大学のレポートを書いたらバレそうになった話と反省",
    "AIにバイトのシフト管理と収支記録をやらせてみた話",
    # お金（奨学金・生活費・失敗）
    "大学2年生の1ヶ月の生活費を全部公開する（奨学金＋バイトのリアル）",
    "奨学金230万を借りている大学2年が、お金の勉強を早く始めればよかったと思う3つのこと",
    "月収3万のバイト生活から固定費を削って貯金を作るまでの記録",
    "大学生がサブスク全部解約したら月4,000円浮いた話と見直し手順",
    # 副業・発信（試行錯誤中）
    "「副業に興味はあるけど何から手をつければいいかわからない」という状態のまま3ヶ月経ったレポート",
    # キャリア準備（インターン・不安・実験）
    "大学2年でインターンに応募してみたら面接でボコボコにされた話",
    "ESをClaudeに5回書いてもらったら、だんだん「ぼくっぽくない文章」になってきた話",
    "「就活、何もしてないけど大丈夫？」大学2年の正直な不安を書く",
    "自己PRを書こうとしたら「ガクチカ」が何もなかった話",
    "AIに自己分析させてみたら「そんなやつだったの？」という結果になった",
    "インターン選考で落ちまくって気づいた、ぼくに足りなかったもの",
    "就活の軸を決めようとしたら「やりたいこと」が何もなかった話",
    "大学2年でOB訪問してみたら価値観が変わった3つのこと",
    "AIで企業研究したらESの質が上がった気がしたので方法をまとめる",
    "就活まで2年ある大学2年生が「今のうちにやっておいて正解だった」と思うこと",
]

# 大学2年の立場で「盛りすぎ」になりやすいNGワード
_OVERCONFIDENT_WORDS = [
    "内定", "年収", "達成", "フリーランス案件", "受注",
    "大手を蹴って", "副業に全振り", "末路", "稼いだ結果",
    "月◯万", "月○万",
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


def _get_recent_topics(days: int = 14) -> set[str]:
    """drafts.json から直近 N 日以内に使用したトピックを返す。"""
    import json
    from datetime import datetime, timedelta
    drafts_path = Path(__file__).parent / "drafts.json"
    if not drafts_path.exists():
        return set()
    try:
        drafts = json.loads(drafts_path.read_text(encoding="utf-8"))
        cutoff = datetime.now() - timedelta(days=days)
        recent = set()
        for d in drafts:
            created = d.get("created_at", "")
            topic = d.get("picked_topic") or d.get("title", "")
            if not created or not topic:
                continue
            try:
                dt = datetime.fromisoformat(created)
                if dt >= cutoff:
                    # キーワードレベルで比較（「投資」が含まれるタイトルを全部まとめる）
                    recent.add(topic)
                    for kw in PRIORITY_KEYWORDS:
                        if kw in topic:
                            recent.add(kw)
            except ValueError:
                pass
        return recent
    except Exception:
        return set()


def _topic_is_fresh(topic: str, recent: set[str]) -> bool:
    """トピックが直近に使われていなければ True。"""
    if topic in recent:
        return False
    for kw in PRIORITY_KEYWORDS:
        if kw in topic and kw in recent:
            return False
    return True


def _topic_is_safe(topic: str) -> bool:
    """大学2年の立場で盛りすぎにならないか確認する。NGワードを含む場合 False。"""
    return not any(ng in topic for ng in _OVERCONFIDENT_WORDS)


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

    # 直近14日間に使ったキーワードを取得
    recent_topics = _get_recent_topics(days=14)

    # スコアが1以上のトレンドだけを候補にする。
    relevant = [w for w, s in ranked if s >= 1]

    if relevant:
        # トレンドあり: 使用済み・NGワードを除外してから候補にする
        fresh = [w for w in relevant if _topic_is_fresh(w, recent_topics) and _topic_is_safe(w)]
        candidates = (fresh or relevant)[:10]
        use_trends = True
    else:
        # トレンドなし: デフォルト候補から使用済み・NGワードを除外してローテーション
        safe_defaults = [t for t in _DEFAULT_TOPICS if _topic_is_fresh(t, recent_topics) and _topic_is_safe(t)]
        # 全部使い切ったらリセット（安全なものだけ再利用）
        candidates = safe_defaults[:5] if safe_defaults else [t for t in _DEFAULT_TOPICS if _topic_is_safe(t)][:5]
        use_trends = False

    topic   = _llm_select_topic(candidates, use_trends=use_trends)
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
        "あなたはnoteでバズる記事タイトルを作るSNSマーケターです。\n\n"
        f"【{source_label}】\n"
        + "\n".join(f"- {t}" for t in candidates) + "\n\n"
        "【書き手の前提】\n"
        "- 都内私立大学2年生「ぼく」。一人称は平仮名「ぼく」\n"
        "- 本選考・内定・フリーランス受注・月〇万達成などの実績はまだない\n"
        "- 「試行錯誤の途中にいる大学生」として書く\n\n"
        "【タイトルの鉄則】\n"
        f"1. {source_note}\n"
        "2. 感情トリガーを1つ以上入れる:\n"
        "   - 共感・不安: 「〇〇だけどこれでいいの？」「正直に話す」「〇〇が何もなかった」\n"
        "   - 好奇心ギャップ: 「やってみたら意外と〇〇だった」「〇〇してみた結果」\n"
        "   - 数字の具体性: 奨学金230万・月3万のバイト・3ヶ月で・5回落ちた など\n"
        "3. テーマは「18〜24歳の大学生が実際に体験できること」に限定する\n"
        "   ✅ インターン選考・AI活用・奨学金・バイト・就活準備・副業試行中\n"
        "   ❌ 内定・年収・フリーランス受注・大手蹴り・副業全振り・結婚・住宅ローン\n"
        "4. 避けるべきタイトル:\n"
        "   ❌「〇〇のコツ5選」「〇〇の方法」「〇〇で稼いだ結果」（実績断言）\n"
        "   ✅「〇〇してみたら〇〇だった話」「〇〇が何もなかった話」「〇〇の正直な記録」\n"
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
