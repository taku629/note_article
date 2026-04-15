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

## 5. ログファイル運用

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

## 6. WSL 環境での cron 注意点

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
