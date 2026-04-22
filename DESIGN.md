# DESIGN.md — 設計メモと将来拡張ガイド

このドキュメントは「なぜこの設計にしたか」と「将来どう拡張するか」を記録する技術メモです。

---

## 1. ARTICLE_PROVIDER による記事生成モデルの切り替え

### 現状

`article_generator.py` の `generate_article_taku()` は内部で `ARTICLE_PROVIDER` 環境変数を参照している。

```python
provider = os.getenv("ARTICLE_PROVIDER", "claude").lower()
```

現在は `claude` のみ実装済み。デフォルト値も `claude` なので `.env` への追記は不要。

### 将来の拡張方法

新しいプロバイダーを追加するには `article_generator.py` の以下の箇所を編集する。

```python
def generate_article_taku(topic_info: dict) -> tuple[str, str]:
    provider = os.getenv("ARTICLE_PROVIDER", "claude").lower()

    if provider == "claude":
        return _generate_with_claude(topic_info)
    elif provider == "gemini":          # ← ここを追加
        return _generate_with_gemini(topic_info)
    else:
        print(f"  ⚠ 未対応プロバイダー '{provider}'。claude にフォールバック。")
        return _generate_with_claude(topic_info)
```

Gemini 実装の雛形:

```python
def _generate_with_gemini(topic_info: dict) -> tuple[str, str]:
    """Google Gemini API を使って記事を生成する（将来実装）。"""
    import google.generativeai as genai  # pip install google-generativeai
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY が設定されていません。")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-pro")

    # _generate_with_claude と同じ topic_info / prompt 構造を使う
    prompt = _build_taku_prompt(topic_info)  # 共通プロンプトビルダーに切り出す
    resp = model.generate_content(prompt)
    return _parse_output(resp.text.strip(), topic_info.get("topic", ""))
```

`.env` への追記:
```
ARTICLE_PROVIDER=gemini
GEMINI_API_KEY=AIza...
```

---

## 2. 429 エラー時のフォールバック設計

### 現状の動作

`post.py` の `_post_with_retry()` は 429 を受け取ると `RETRY_WAIT × attempt` 秒待ってリトライする（最大 `MAX_RETRY` 回）。

### フォールバック先をモデルレベルに拡張する構想

Claude API が 429 または 5xx を返した場合に Gemini にフォールバックするには、`article_generator.py` に以下のラッパーを追加する。

```python
def _generate_with_fallback(topic_info: dict) -> tuple[str, str]:
    """Claude を試みて失敗したら Gemini にフォールバックする。"""
    try:
        return _generate_with_claude(topic_info)
    except Exception as claude_err:
        print(f"  ⚠ Claude 失敗: {claude_err}")
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if gemini_key:
            print("  → Gemini にフォールバックします。")
            return _generate_with_gemini(topic_info)
        raise  # Gemini も使えない場合は上位に伝播
```

`generate_article_taku` 内の呼び出しを `_generate_with_fallback` に変更するだけで有効になる。

---

## 3. モジュール依存関係

```
automation.py
├─ trend_selector.py   # トレンド取得・スコアリング・テーマ選定
│   └─ anthropic       # テーマ選定に claude-haiku-4-5 を使用
├─ article_generator.py # 記事生成（takaキャラ）
│   └─ anthropic        # 記事生成に claude-haiku-4-5 を使用
└─ post.py             # note API 投稿・タグ生成・品質チェック
    ├─ config.py       # 環境変数管理
    └─ requests        # note.com API 呼び出し
```

各モジュールは独立して `python -m module_name` で単体テスト可能。

---

## 4. drafts.json のスキーマ

```json
[
  {
    "created_at":    "2026-04-16T08:30:00",  // ISO 8601
    "note_id":       "12345678",              // note API の id フィールド
    "key":           "n149a63c994a6",         // 公開URL末尾: note.com/taku629/n/{key}
    "title":         "大学生が...",
    "file":          "/home/.../article_20260416.md",  // 絶対パス
    "published":     false,
    "published_at":  null,                    // 公開後に ISO 8601 で更新
    "picked_topic":  "【実体験】大学生がAIで...",  // auto-trend のみ
    "trend_raw":     "AI"                     // auto-trend のみ
  }
]
```

`publish-latest` は `"published": false` のエントリのうち最後のものを1件ずつ処理する。

---

## 5. 「8:00 に note の下書きが作られる」は誤解

`auto-trend` は note.com API を**一切呼ばない**。

| 時刻 | note.com への操作 | ローカルへの操作 |
|---|---|---|
| 8:00 `auto-trend` | なし | .md 保存 / `drafts.json` 追記（`note_id: null`） |
| 21:00 `publish-latest` | create + 即時公開（2 API calls） | `drafts.json` 更新（`published: true`） |

ブラウザのダッシュボードに記事が現れるのは 21:00 以降（公開済み状態として）。

---

## 6. ブラウザ下書きと自動フローの関係

| 作成経路 | `drafts.json` | 自動公開 |
|---|---|---|
| `auto-trend` / `create-draft` 経由 | 登録される | 21:00 に自動公開 |
| ブラウザで直接作成 | 登録されない | 自動公開されない（手動公開） |

ブラウザ下書きを自動フローに乗せる唯一の確実な方法：
1. 本文を `.md` ファイルにコピーして保存
2. `python3 automation.py --mode create-draft --file xxx.md`
3. 21:00 の `publish-latest` が**新規ノートとして**作成・公開する
   （既存の下書きを更新するのではなく、新規作成になる点に注意）

「既存の note_id に対して publish するだけ」を試みた場合、note.com API は別セッションからの `draft_save(is_temp_saved=false)` を 201 で返すが実際には公開されないことが確認されている（→ 新規作成フローに統一した経緯）。

---

## 8. ログファイル運用

| ファイル | 書き込みモード | ローテーション |
|---|---|---|
| `auto.log` | 追記（`>>`） | 手動（月次 `mv` など） |
| `posting.log` | 追記（`>>`） | 手動 |

ログが肥大化した場合は `logrotate` を設定するか、以下のコマンドで月ごとにアーカイブする。

```bash
# 例: 今月のログをアーカイブ
mv auto.log auto_$(date +%Y%m).log
```

---

## 9. WSL 環境での cron 注意点

WSL は PC 再起動時に cron デーモンが自動起動しない。
以下を `~/.bashrc` または `/etc/wsl.conf` に設定しておくと手動起動が不要になる。

```bash
# ~/.bashrc に追加
sudo service cron start > /dev/null 2>&1
```

または `/etc/wsl.conf`:

```ini
[boot]
command = service cron start
```

（`/etc/wsl.conf` の `[boot]` セクションは WSL2 のみ有効）

---

## 10. デフォルトトピック多様化の設計

### 背景・問題

Google Trends JP スコアが 0（大学生テーマと無関係なトレンドのみ）の日が続くと、
`_DEFAULT_TOPICS`（5件）だけから Claude が毎日選び続け、同系統テーマが連続する。
例：2026-04-17〜19 の3日間、「大学生が投資を始めて6ヶ月で学んだこと」が毎日選ばれた。

### 現状のフォールバックロジック（`trend_selector.py`）

```
1. Google Trends RSS から最大30件取得
2. PRIORITY_KEYWORDS（23語）との一致数でスコアを計算
3. score >= 1 のトレンドだけを候補にする
4. score >= 1 が1件もない場合 → _DEFAULT_TOPICS[:5] の5件を候補として使用
5. 候補リストを Claude haiku に渡してタイトル1件を選ばせる
6. API 失敗時 → candidates[0]（リスト先頭）を返す
```

問題点：
- `_DEFAULT_TOPICS` が5件しかなく多様性が低い
- Claude が同じ候補から繰り返し選ぶと同系統テーマが連続する
- 「最近使ったテーマを避ける」仕組みがない

---

### 拡張デフォルトトピック案（6カテゴリ × 3件 = 18件）

```python
_DEFAULT_TOPICS_BY_CATEGORY = {
    "money": [
        "大学生の節約術5選【実際にやった】",
        "奨学金を借りながら月3万貯金した方法",
        "【実体験】大学生が投資を始めて6ヶ月で学んだこと",
    ],
    "side_job": [
        "大学生がバイトと副業を両立してみた話",
        "大学生がクラウドソーシングで月2万稼いだ実録",
        "バイト代を増やすために大学3年でやったこと3選",
    ],
    "sns": [
        "【実体験】SNSフォロワー1000人になるまでにやったこと",
        "大学生がnoteを3ヶ月続けた結果【正直レポート】",
        "TikTok運用を半年やって気づいた大学生が伸びるコツ",
    ],
    "career": [
        "就活と副業を両立した大学生の1日ルーティン",
        "大学2年でインターンを始めて変わったこと",
        "就活で後悔しないために大学1年からやっておくべきこと",
    ],
    "study": [
        "大学生が独学でプログラミングを学んだ3ヶ月の記録",
        "一人暮らし大学生が食費月1.5万に抑えた自炊術",
        "大学の授業を最大限活かして奨学金を増やした話",
    ],
    "mindset": [
        "大学生のうちにやっておけばよかった自己投資5選",
        "サークルとバイトと就活を両立できた理由",
        "大学4年間で1番役に立ったお金の使い方",
    ],
}
```

---

### 重複回避ロジック設計案

**アプローチ：「直近 N 日のカテゴリを除外して候補を絞る」**

1. `drafts.json` から直近 N 日（推奨: 7日）の `title` を取得
2. 各タイトルに含まれるキーワードから「最近使ったカテゴリ」を特定
3. `_DEFAULT_TOPICS_BY_CATEGORY` から最近のカテゴリを除外した候補を LLM に渡す
4. すべてのカテゴリが使用済みの場合（7日以上連続でデフォルト利用）は全カテゴリにリセット

**カテゴリ判定キーワード**

```python
_CATEGORY_HINTS = {
    "money":    ["節約", "貯金", "投資", "奨学金", "お金"],
    "side_job": ["バイト", "副業", "稼ぐ", "クラウド", "フリーランス"],
    "sns":      ["SNS", "フォロワー", "note", "TikTok", "YouTube", "Instagram"],
    "career":   ["就活", "インターン", "キャリア", "転職"],
    "study":    ["プログラミング", "勉強", "食費", "一人暮らし", "授業"],
    "mindset":  ["自己投資", "サークル", "やっておけばよかった"],
}
```

**処理フロー（疑似コード）**

```
recent_titles    = drafts.json から直近7日の title を取得
recent_categories = recent_titles を _CATEGORY_HINTS で判定した category の set

available = 全カテゴリ - recent_categories
if not available:
    available = 全カテゴリ  # 7日でリセット

candidates = available の各カテゴリからランダムに2件ずつ選ぶ（最大12件）
topic = _llm_select_topic(candidates, use_trends=False)
```

**実装時の変更ファイル：`trend_selector.py`のみ**

- `_DEFAULT_TOPICS`（5件フラットリスト）を `_DEFAULT_TOPICS_BY_CATEGORY`（辞書）に置き換え
- `_CATEGORY_HINTS` を追加
- `select_today_theme()` に `_get_fallback_candidates(drafts_path)` の呼び出しを追加
- `_get_fallback_candidates()` を新規追加（上記疑似コードの実装）

外部インターフェース（戻り値の dict 構造）は変更しないため、`automation.py` の修正は不要。
