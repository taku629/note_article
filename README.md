# note 自動投稿システム (大学生 Persona 版)

このシステムは、トレンドに連動した記事生成と、既存ストック記事の定期投稿を自動化します。

## 主な機能

1.  **トレンド連動投稿 (毎日 8:00)**
    -   Google Trends (JP) から急上昇ワードを取得。
    -   「副業」「お金」「キャリア」などのキーワードと掛け合わせ、現役大学生の視点で記事テーマを自動選定。
    -   Claude-4.5-Haiku を使用して 1500〜2500 字の記事を自動生成。
    -   タグ 5 個をルール（汎用・中規模・ニッチ）に従って生成。
    -   品質チェック（文字数、キーワード、タグ数）をパスした場合のみ自動投稿。

2.  **ストック記事投稿 (毎日 14:00)**
    -   `articles/` フォルダ内の未投稿記事を 1 日 1 本自動投稿。
    -   同様の品質チェックをパスした場合のみ投稿。

3.  **ロギング**
    -   実行ログを `posting.log` に記録。
    -   エラー発生時はターミナルに詳細を出力。

## セットアップ

1.  `.env` ファイルに `NOTE_SESSION_COOKIE` と `ANTHROPIC_API_KEY` を設定してください。
2.  依存パッケージをインストールします:
    ```bash
    pip3 install python-dotenv anthropic requests --break-system-packages
    ```

## 実行方法

### スケジューラーの起動 (推奨)
```bash
python3 automation.py --mode scheduler
```
※ バックグラウンドで実行し続ける場合は `nohup` や `screen` / `tmux` を使用してください。

### 手動実行 (テスト)
- トレンド投稿のテスト: `python3 automation.py --mode trend --dry-run`
- ストック投稿のテスト: `python3 automation.py --mode stock --dry-run`

---

## モード一覧と想定ユースケース

### --mode create-draft（朝：下書き投稿）

```bash
python3 automation.py --mode create-draft --file /path/to/article_x.md
```

**何をするか**
Markdown ファイルを読み込み、note に下書きとして保存する。この時点では公開されない（`is_temp_saved=true`）。保存後、以下の情報を `drafts.json` に追記する。

```json
{
  "created_at": "2026-04-16T08:30:00",
  "note_id": "12345678",
  "key": "n149a63c994a6",
  "title": "大学生が...",
  "file": "/home/.../article_x.md",
  "published": false
}
```

**想定ユースケース**  
記事を用意した朝や日中に実行。投稿内容を確認してから夜に公開したい場合の「準備ステップ」として使う。

---

### --mode publish-latest（夜：最新下書きを公開）

```bash
python3 automation.py --mode publish-latest
```

**何をするか**
`drafts.json` の中から `"published": false` の最新エントリを取得し、同じ `note_id` に対して `draft_save?is_temp_saved=false` を呼び出して公開状態に切り替える。完了後、`drafts.json` の当該エントリを `"published": true` に更新し、`published_at` を記録する。

実行ログに公開 URL を出力する。

```
✓ 公開完了: https://note.com/taku629/n/n149a63c994a6
```

**想定ユースケース**  
cron で毎日 21:00 に自動実行。朝に保存した下書きが夜に自動公開される。

---

### --mode test-post-once（テスト・即時確認用）

```bash
# 下書きとして保存（確認用）
python3 automation.py --mode test-post-once --file articles/article_4.md

# 即時公開（動作確認・本番テスト）
python3 automation.py --mode test-post-once --file articles/article_4.md --publish
```

**何をするか**
`--publish` なし → 下書き保存のみ（`is_temp_saved=true`）  
`--publish` あり → 即時公開（`is_temp_saved=false`）  
どちらも `drafts.json` への記録は行わない。テスト・動作確認専用。

**想定ユースケース**  
初回セットアップ時や API の疎通確認、記事レイアウト確認など。本番運用では `create-draft` → `publish-latest` の2ステップを使う。

---

## 1日の想定フロー

```
08:00〜  記事ファイルを用意（手動 or トレンド生成スクリプト）
          ↓
          python3 automation.py --mode create-draft --file xxx
          → note に下書き保存、drafts.json に記録
          → note のダッシュボードで見た目を確認（任意）
          ↓
21:00    cron が自動実行
          → python3 automation.py --mode publish-latest
          → drafts.json の最新未公開エントリを取得して公開
          → posting.log に公開 URL を記録
```

**複数日分をまとめて準備する場合**  
`create-draft` を複数回実行すると `drafts.json` に複数の未公開エントリが積まれる。`publish-latest` は毎回「最後に追加された未公開エントリ」を1件ずつ公開するため、追加した順番に消化される。

---

## 下書き/公開の仕組み（技術メモ）

note.com の非公式 API は「作成」と「保存/公開」が2ステップに分かれている。

| ステップ | API | 役割 |
|---|---|---|
| 1. 作成 | `POST /api/v1/text_notes` | `note_id` と `key` を払い出す |
| 2. 保存 | `POST /api/v1/text_notes/draft_save?id={note_id}&is_temp_saved=true` | 下書き保存 |
| 2'. 公開 | `POST /api/v1/text_notes/draft_save?id={note_id}&is_temp_saved=false` | 公開 |

`publish-latest` モードはステップ2'のみを実行する（ステップ1はスキップ。既に `note_id` がある）。  
実装箇所: `post.py` の `draft_save()` 関数（`is_temp = "false" if publish else "true"`）。

---

## cron 設定（毎日 21:00 に自動公開）

```cron
0 21 * * * /home/tk250127/c/.venv/bin/python /home/tk250127/note-automation/automation.py --mode publish-latest >> /home/tk250127/note-automation/posting.log 2>&1
```

---

## 完全自動フロー

cron 2本で「1日中コマンドを叩かずに毎日1本公開」を実現する構成。

```
08:00 [cron]  auto-trend
              ├─ Google Trends JP からトレンドワード取得
              ├─ スコアリング（PRIORITY_KEYWORDS との一致数）
              ├─ Claude でテーマ1件選定
              ├─ Claude (taku キャラ) で4000〜5000字記事生成
              ├─ /home/tk250127/note-articles/output/article_YYYYMMDD.md に保存
              ├─ note に下書き投稿（is_temp_saved=true）
              └─ drafts.json に { note_id, key, title, file, published:false } を追記

21:00 [cron]  publish-latest
              ├─ drafts.json から最新の未公開エントリを取得
              ├─ note に公開リクエスト（is_temp_saved=false）
              ├─ drafts.json の published:true に更新
              └─ posting.log に公開 URL を記録
```

### cron 登録行

```cron
# 毎朝8時: トレンド取得 → 記事生成 → 下書き保存
0 8 * * * /home/tk250127/c/.venv/bin/python /home/tk250127/note-automation/automation.py --mode auto-trend >> /home/tk250127/note-automation/auto.log 2>&1

# 毎晩21時: 最新下書きを公開
0 21 * * * /home/tk250127/c/.venv/bin/python /home/tk250127/note-automation/automation.py --mode publish-latest >> /home/tk250127/note-automation/posting.log 2>&1
```

### ログファイル

| ファイル | 記録内容 |
|---|---|
| `auto.log` | 朝8時の auto-trend 実行ログ（picked_topic, file_path, note_id, key） |
| `posting.log` | 夜21時の publish-latest 実行ログ（公開 URL） |

---

## トレンド取得の技術メモ

| 項目 | 内容 |
|---|---|
| 取得元 | Google Trends JP（RSS フィード） |
| URL | `https://trends.google.co.jp/trending/rss?geo=JP` |
| データ形式 | RSS 2.0 XML → `<item><title>` を文字列リストとして取得（約20件） |
| スコアリング | `PRIORITY_KEYWORDS`（お金・SNS・キャリア関連23語）との一致数をスコアとして計算 |
| テーマ選定 | 上位10件を claude-haiku-4-5 に渡し、大学生向けタイトル案を1件生成 |
| フォールバック | Trends 取得失敗時はデフォルトトピック候補から Claude が選定 |

`PRIORITY_KEYWORDS` の一覧（`trend_selector.py` で定義）:
```
お金, バイト, 副業, 就活, インターン, SNS, フォロワー, 投資, FX,
仮想通貨, 節約, 奨学金, フリーランス, スキル, 転職, 起業,
稼ぐ, 貯金, 資産, YouTube, TikTok, Instagram, X
```

---

## 大学生 taku キャラクター設定

| 項目 | 内容 |
|---|---|
| 一人称 | 「ぼく」（平仮名固定） |
| 想定読者 | 18〜22歳の大学生 |
| テーマ領域 | お金・SNS・キャリア |
| 世界観 | 「大学生のうちにやっておけばよかった」を減らす |
| 文体 | 友達への長文 LINE のような、丁寧かつフラットな口調 |
| ボリューム目安 | 本文 4000〜5000字 |

記事構成: 導入（共感 + 結論一文） → 本文見出し4〜6個（やっていたこと/失敗理由/学び + 数字） → まとめ → CTA

### 使用モデルと環境変数

| 環境変数 | 説明 | 例 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API キー（必須） | `sk-ant-...` |
| `ARTICLE_PROVIDER` | 記事生成プロバイダー（省略可） | `claude`（デフォルト） |
| `NOTE_SESSION_COOKIE` | note.com セッションクッキー | `64f82b...` |

将来的な `ARTICLE_PROVIDER=gemini` 対応については `DESIGN.md` を参照。

## ファイル構成
- `automation.py`: 全体の実行管理とスケジューラー
- `trend_selector.py`: トレンド取得・テーマ選定ロジック
- `article_generator.py`: 記事本文・タグ生成ロジック
- `post.py`: note.com への API 投稿・品質チェックロジック
- `config.py`: 設定管理
- `articles/`: ストック記事（Markdown）を格納するディレクトリ
- `posted.txt`: 投稿済みストック記事の管理ファイル
- `posting.log`: 実行ログ
