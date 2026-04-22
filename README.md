# note 自動投稿システム (大学生 Persona 版)

このシステムは、トレンドに連動した記事生成と、既存ストック記事の定期投稿を自動化します。

---

## 重要な運用方針

> **自動で公開される記事は、すべてスクリプト経由で作成する。**

- 自動公開の対象は `auto-trend` / `create-draft` / `auto-trend-publish-now` を通じて
  生成・登録された記事のみ。
- ブラウザから直接作成した下書きは **自動公開の対象外**（手動で公開する）。
- `drafts.json` が「自動公開キュー」として機能する。
  スクリプト経由で登録された記事だけがここに積まれ、`publish-latest` によって消化される。

### 8:00〜21:00 の間、記事は note に存在しない

`auto-trend`（8:00）は **note.com API を一切呼ばない**。
記事は `.md` ファイルと `drafts.json` にのみ存在する。
`publish-latest`（21:00）が初めて note に記事を作成し、そのまま即時公開する。

この仕様のため：
- 8:00〜21:00 の間、note のブラウザダッシュボードに下書きは表示されない（正常）
- 21:00 の cron が失敗した場合、その日の記事は翌日以降に持ち越しになる
- ブラウザから下書きを作成しても、`drafts.json` に登録しない限り自動公開されない

### ブラウザで書いた記事を自動フローに乗せる方法

```bash
# 1. ブラウザの下書き本文を .md にコピーして保存
# 2. スクリプト経由で drafts.json に登録
python3 automation.py --mode create-draft --file /path/to/article.md
# 3. 21:00 の publish-latest が新規ノートとして作成・公開（既存ノートの更新ではない）
```

---

## 主な機能

1. **トレンド連動投稿**
   - Google Trends (JP) から急上昇ワードを取得。
   - 大学生向けキーワードとスコアリングし、現役大学生の視点でテーマを自動選定。
   - Claude Haiku を使って 4000〜5000 字の記事を自動生成。
   - 品質チェック（文字数・キーワード）付きリトライ（最大3回）。
   - タグ 5 個をルール（汎用・中規模・ニッチ）に従って生成。

2. **ストック記事投稿**
   - `articles/` フォルダ内の未投稿記事を 1 日 1 本自動投稿。

3. **ロギング**
   - `auto.log` : 朝の記事生成ログ（picked_topic, file_path, note_id, key）
   - `posting.log` : 公開ログ（公開 URL）

---

## セットアップ

1. `.env` ファイルに `NOTE_SESSION_COOKIE` と `ANTHROPIC_API_KEY` を設定。
2. 依存パッケージをインストール:
   ```bash
   pip3 install python-dotenv anthropic requests --break-system-packages
   ```

---

## 3つの運用パターン

### パターン1: 完全自動2段階（推奨・通常運用）

朝に記事を生成して下書き保存し、夜に自動公開する。
記事の内容を日中に目視確認できる余地を残しつつ、最終公開は自動で行う。

```
08:00 [cron]  auto-trend
              ├─ Google Trends JP からトレンドワード取得
              ├─ スコアリング → テーマ1件選定
              ├─ Claude (taku キャラ) で4000〜5000字記事生成
              ├─ 品質チェック（文字数・キーワード）付きリトライ（最大3回）
              ├─ article_YYYYMMDD.md に保存
              └─ drafts.json に {note_id:null, published:false} で登録

21:00 [cron]  publish-latest
              ├─ drafts.json から最新の未公開エントリを取得
              ├─ note に新規作成 + 即時公開（is_temp_saved=false）
              ├─ drafts.json の published:true / published_at を更新
              └─ posting.log に公開 URL を記録
```

**cron 設定:**
```cron
0 8  * * * /home/tk250127/c/.venv/bin/python /home/tk250127/note-automation/automation.py --mode auto-trend         >> /home/tk250127/note-automation/auto.log    2>&1
0 21 * * * /home/tk250127/c/.venv/bin/python /home/tk250127/note-automation/automation.py --mode publish-latest     >> /home/tk250127/note-automation/posting.log 2>&1
```

---

### パターン2: 即時自動公開モード（生成→公開を1回で完結）

生成から公開まで一気通貫で実行する。
「今すぐ1本公開したい」場合や、2段階を使わずに単一 cron で回したい場合に使う。

```
[手動 or cron]  auto-trend-publish-now
                ├─ Google Trends JP からトレンドワード取得
                ├─ スコアリング → テーマ1件選定
                ├─ Claude (taku キャラ) で記事生成（品質チェック付きリトライ）
                ├─ article_YYYYMMDD.md に保存
                ├─ タグ生成
                ├─ note に新規作成 + 即時公開
                └─ drafts.json に {note_id, key, published:true} で記録
```

**手動実行:**
```bash
python3 automation.py --mode auto-trend-publish-now
```

**cron 例（8:00 に生成＆即時公開）:**
```cron
0 8 * * * /home/tk250127/c/.venv/bin/python /home/tk250127/note-automation/automation.py --mode auto-trend-publish-now >> /home/tk250127/note-automation/auto.log 2>&1
```

> このモードを使う場合、21:00 の `publish-latest` cron は不要（または削除する）。

---

### パターン3: 手動確認してから公開

内容を目視確認してから公開したい場合のフロー。

```
08:00 [cron]  auto-trend
              └─ 記事生成 → drafts.json に登録（note にはまだ投稿しない）

[日中]        note のダッシュボードではなく、
              /home/tk250127/note-articles/output/ の .md ファイルを直接確認

[問題なければ] python3 automation.py --mode publish-latest
              └─ または 21:00 cron に任せる
```

**手動で特定ファイルを下書き登録する場合:**
```bash
python3 automation.py --mode create-draft --file /path/to/article.md
```

---

## モード一覧

| モード | 説明 | drafts.json |
|---|---|---|
| `auto-trend` | トレンド取得 → 記事生成 → .md 保存 → 下書き登録 | published:false で追記 |
| `auto-trend-publish-now` | トレンド取得 → 記事生成 → 公開まで一気通貫 | published:true で追記 |
| `publish-latest` | 最新の未公開エントリを公開 | published:true に更新 |
| `create-draft` | 指定 .md を下書き登録（note には投稿しない） | published:false で追記 |
| `test-post-once` | 1件だけテスト投稿（drafts.json は更新しない） | 更新なし |
| `dry-post-once` | テスト投稿のドライラン | 更新なし |

---

## drafts.json のスキーマ

```json
[
  {
    "created_at":    "2026-04-17T08:00:00",
    "note_id":       "156053571",
    "key":           "nb2d9aa695cde",
    "title":         "【実体験】大学生が...",
    "file":          "/home/.../article_20260417.md",
    "published":     true,
    "published_at":  "2026-04-17T21:00:05",
    "picked_topic":  "【実体験】大学生が...",
    "trend_raw":     "AI"
  }
]
```

- `auto-trend` で登録直後: `note_id: null, key: null, published: false`
- `publish-latest` または `auto-trend-publish-now` 実行後: `note_id`, `key`, `published: true`, `published_at` が埋まる

---

## 下書き/公開の仕組み（技術メモ）

note.com の非公式 API は「作成」と「保存/公開」が2ステップに分かれている。

| ステップ | API | 役割 |
|---|---|---|
| 1. 作成 | `POST /api/v1/text_notes` | `note_id` と `key` を払い出す |
| 2'. 公開 | `POST /api/v1/text_notes/draft_save?id={note_id}&is_temp_saved=false` | 公開 |

`publish-latest` / `auto-trend-publish-now` はステップ1→2'を同一セッションで連続実行する。
ブラウザで作成した下書き（別セッション）への `is_temp_saved=false` は確実に公開されない場合があるため、
スクリプト経由の新規作成フローに統一している。

---

## cron 注意点（WSL 環境）

WSL は PC 再起動時に cron デーモンが自動起動しない。
`/etc/wsl.conf` に以下を設定しておくと手動起動が不要になる。

```ini
[boot]
command = service cron start
```

---

## 大学生 taku キャラクター設定

| 項目 | 内容 |
|---|---|
| 一人称 | 「ぼく」（平仮名固定） |
| 想定読者 | 18〜22歳の大学生 |
| テーマ領域 | お金・SNS・キャリア |
| 文体 | 友達への長文 LINE のような、丁寧かつフラットな口調 |
| ボリューム目安 | 本文 4000〜5000字 |
| 品質チェック | 3000字未満または主要キーワードなし → 最大3回リトライ |

記事構成: 導入（共感 + 結論一文） → 本文見出し4〜6個 → まとめ → CTA

---

## ファイル構成

```
note-automation/
├── automation.py        # 全体の実行管理（モード切替）
├── trend_selector.py    # トレンド取得・テーマ選定
├── article_generator.py # 記事本文・タグ生成（taku キャラ）
├── post.py              # note.com API 投稿・品質チェック
├── config.py            # 設定管理（環境変数）
├── drafts.json          # 自動公開キュー（スクリプト経由の記事のみ）
├── articles/            # ストック記事（Markdown）
├── auto.log             # 朝8時の実行ログ
└── posting.log          # 公開ログ（公開 URL）
```
