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

---

## 7. 収益化運用設計

> このセクションは「投稿が安定した」次のフェーズ——**分析 → 改善 → 収益化**——の設計メモ。

---

### 7-1. 現在のbotの役割

```
08:00  auto-trend  → トレンド取得 → Claude で記事生成 → .md 保存 → drafts.json 記録
21:00  publish-latest → Firefox Playwright でエディタ操作 → note に投稿
```

botが「自動化できていること」と「まだ人がやること」を明確に分ける。

| 自動（bot） | 手動（運用者） |
|---|---|
| 記事生成・テーマ選定 | PV・いいね数の記録（records.csv への追記） |
| note への投稿 | 週次振り返り（伸びたテーマの分析） |
| CTA の差し込み | 月次の有料note企画 |
| drafts.json への記録 | SNSでの拡散・コメント返し |

---

### 7-2. 収益化までの運用フロー

```
【毎日】
  08:00  bot: 記事生成・.md 保存
  21:00  bot: note に投稿
  翌朝    人: 前日記事の URL を records.csv に記入
          人: いいね数・PV を確認して記入（note の管理画面から）

【週1（日曜夜など）】
  - records.csv を見て「いいね上位3件」のカテゴリを確認
  - 翌週は上位カテゴリを意識したテーマを _DEFAULT_TOPICS の先頭に置く
  - CTA の A/B 比率を見てクリック数が低いパターンを入れ替え検討

【月1（月末）】
  - その月の「いいね TOP5 記事」を並べる
  - 共通テーマ・キーワードを抽出 → 有料note の章立て案を作る
  - 有料note を 1 本執筆・公開（目標: 500〜1,000円 × 読者数）
  - 翌月の無料記事は有料noteの各章を「お試し版」として切り出すイメージで書く
```

---

### 7-3. 計測すべき指標と優先順位

| 優先度 | 指標 | なぜ見るか | 取得方法 |
|---|---|---|---|
| ★★★ | likes | バズ・拡散の直接指標 | note 管理画面 → 手動記入 |
| ★★★ | cta_type | どの導線が効くか | drafts.json の cta_type を転記 |
| ★★☆ | pv | 露出量。likes との比率でエンゲージメント率がわかる | note 管理画面 |
| ★★☆ | followers_gained | ファン化の指標 | 投稿前後のフォロワー差分 |
| ★☆☆ | comments | 深い共感の指標 | 目視 |
| ★☆☆ | paid_clicks | 有料note への実際の誘導数 | note のリンク付きメモ or Bitly |
| ★☆☆ | revenue | 最終KPI | note の売上管理画面 |

> **最初の1ヶ月は likes と cta_type だけ追えば十分。**
> PV や paid_clicks は note Pro 機能が必要な場合があるので後回し。

---

### 7-4. テーマ選定の精度向上（設計案）

現状の課題:
- 全トレンドがスコア0のとき _DEFAULT_TOPICS に頼るが、LLM が毎回同じカテゴリを選びがち
- カテゴリの偏りを防ぐ仕組みがない
- 「伸びたカテゴリ」が次の選定に反映されない

#### (a) 直近7日で同カテゴリが続きすぎない制御

`topic_categories.yaml` でカテゴリを定義し、`trend_selector.py` が
drafts.json の直近7日エントリを読んで「同カテゴリが3回以上 → そのカテゴリの候補を除外」する。
→ 実装コスト: 小。`_get_recent_topics()` の拡張で対応可能。

#### (b) 直近14日で似たタイトルを避ける

現行の `_topic_is_fresh()` が対応済み（キーワードレベルで重複除外）。
追加で「タイトルの先頭10文字一致」も除外条件に加えると精度が上がる。
→ 実装コスト: 小。

#### (c) 伸びたカテゴリの優遇

`records.csv` のいいね数平均が高いカテゴリを、`_DEFAULT_TOPICS` の候補リスト先頭に動的に置く。
週1の手動振り返りで `topic_categories.yaml` の priority フラグを更新するだけでも効果あり。
→ 実装コスト: 中。まずは手動 priority 更新で運用、後に自動化。

---

---

## 8. note 2アカウント運用案

> A = taku629（競プロ・大学生活・実験場）  
> B = AI×自動化専用（新規アカウント）  
> 同一人物がテーマ別に分けて運用する前提。

---

### 8-1. 単一アカウント前提になっている箇所の全リスト

#### config.py
| 箇所 | 問題 |
|---|---|
| `NOTE_SESSION_COOKIE = os.getenv("NOTE_SESSION_COOKIE", "")` | 1つしか持てない |
| `NOTE_URLNAME = "taku629"` | アカウントAに固定 |
| `get_session()` | 上記1つのCookieでSessionを作るため単一アカウント前提 |

#### post.py
| 行 | 箇所 | 問題 |
|---|---|---|
| 37 | `NOTE_URLNAME = "taku629"` | config.py とは別に重複定義。こちらが公開URL生成に使われる |
| 130–143 | `quality_check()` のキーワードリスト | 「大学生」「副業」「バイト」「奨学金」「就活」等がA向け。Bのテーマ（AI・自動化）では不合格になる |
| 237 | `if not NOTE_SESSION_COOKIE:` | Bのセッションを確認する手段がない |
| 241 | `session = get_session()` | 常にAのセッションでしか投稿できない |
| 250 | `https://note.com/{NOTE_URLNAME}/n/{key}` | 公開URLがA固定 |

#### automation.py
| 行 | 箇所 | 問題 |
|---|---|---|
| 13 | `from config import NOTE_URLNAME` | A固定のURLNAMEをインポート |
| 15 | `load_dotenv(".env")` | .envが1ファイル前提 |
| 17 | `DRAFTS_FILE = "drafts.json"` | AとBが混在する。accountフィールドがない |
| 110 | `_publish_via_playwright()` 内で `NOTE_SESSION_COOKIE, NOTE_URLNAME` を再インポート | 切り替え不可 |
| 228 | `https://note.com/{NOTE_URLNAME}/n/{note_key}` | 公開URLがA固定 |
| 374 | `generate_article_taku(topic_info)` | takaキャラ（A向けペルソナ）固定の記事生成 |
| 379–385 | output_dir = `/home/tk250127/note-articles/output/` | AとBの生成記事が混在する |

#### post_all.py
| 行 | 箇所 | 問題 |
|---|---|---|
| 15 | `from config import NOTE_SESSION_COOKIE` | 単一Cookie |
| 19 | `POSTED_FILE = "posted.txt"` | AとBの投稿済みが混在 |
| 22 | `ARTICLES_DIR = "articles/"` | AとBの記事フォルダが混在 |

#### 共有状態ファイル
| ファイル | 問題 |
|---|---|
| `drafts.json` | `account` フィールドなし。A/B混在で publish-latest が誤爆する |
| `records.csv` | accountカラムなし |
| `posted.txt` | アカウント区別なし |
| `posting.log` | A/B混在ログ |

---

### 8-2. アカウントA/Bの役割分担

| 項目 | アカウントA（taku629） | アカウントB（AI×自動化） |
|---|---|---|
| テーマ | 競プロ・大学生活・実験・雑記 | AI×自動化・副業・仕組み化 |
| 記事生成ペルソナ | taku（競プロ大学生） | taku_automate（AI活用大学生） |
| 品質チェックキーワード | 大学生/副業/バイト/奨学金/就活 | AI/自動化/LLM/効率化/仕組み |
| 記事出力先 | `note-articles/output/a/` | `note-articles/output/b/` |
| セッションCookie | `NOTE_SESSION_A` | `NOTE_SESSION_B` |
| drafts.json | `drafts_a.json` | `drafts_b.json` |
| posted.txt | `posted_a.txt` | `posted_b.txt` |

---

### 8-3. config / .env の分け方

**.env（変更後）**
```dotenv
# ── アカウントA（taku629） ──────────────
NOTE_SESSION_A=（AのCookie）
NOTE_URLNAME_A=taku629

# ── アカウントB（AI×自動化） ──────────────
NOTE_SESSION_B=（BのCookie）
NOTE_URLNAME_B=（Bのユーザー名）

# ── 共通 ──────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
```

**config.py（変更後イメージ）**
```python
ACCOUNTS = {
    "a": {
        "session_cookie": os.getenv("NOTE_SESSION_A", ""),
        "urlname":        os.getenv("NOTE_URLNAME_A", "taku629"),
        "drafts_file":    "drafts_a.json",
        "posted_file":    "posted_a.txt",
        "articles_dir":   "/home/tk250127/note-articles/output/a",
        "quality_keywords": ["大学生", "副業", "バイト", "奨学金", "就活"],
    },
    "b": {
        "session_cookie": os.getenv("NOTE_SESSION_B", ""),
        "urlname":        os.getenv("NOTE_URLNAME_B", ""),
        "drafts_file":    "drafts_b.json",
        "posted_file":    "posted_b.txt",
        "articles_dir":   "/home/tk250127/note-articles/output/b",
        "quality_keywords": ["AI", "自動化", "LLM", "効率化", "仕組み"],
    },
}

def get_account(name: str) -> dict:
    return ACCOUNTS[name]
```

---

### 8-4. --account a / --account b による切り替え案

全スクリプトに `--account` 引数を追加し、省略時は `"a"`（既存動作を維持）とする。

```bash
# 既存の動作はそのまま（--account a がデフォルト）
python automation.py --mode auto-trend

# Bアカウントで自動投稿
python automation.py --mode auto-trend --account b

# Bアカウントで公開
python automation.py --mode publish-latest --account b
```

各スクリプト内での受け取り方:
```python
parser.add_argument("--account", choices=["a", "b"], default="a")
args = parser.parse_args()
acct = get_account(args.account)
# 以降は acct["session_cookie"] / acct["urlname"] 等を使う
```

---

### 8-5. drafts.json / records.csv をA/Bで分けるか共通にするか

**結論: ファイルは分ける**

| ファイル | 方針 | 理由 |
|---|---|---|
| `drafts_a.json` / `drafts_b.json` | 分ける | `publish-latest` はfaileした場合最新1件を処理するため、混在すると誤爆する |
| `posted_a.txt` / `posted_b.txt` | 分ける | 同名ファイルをA/B両方に投稿済みとしてマークしてしまうリスク |
| `records_a.csv` / `records_b.csv` | 分ける | 分析時にアカウント別PV・いいねを比較したい |
| `posting.log` | 共通でよい（prefixで区別）| `[A]` / `[B]` をログに付ければ十分 |

---

### 8-6. 既存フローを壊さないための移行手順

**Step 1 — .env に変数追加（既存動作に影響なし）**
```dotenv
# 既存の変数を NOTE_SESSION_A にリネーム
NOTE_SESSION_A=（既存の NOTE_SESSION_COOKIE の値をここにコピー）
NOTE_URLNAME_A=taku629
```
この時点では `NOTE_SESSION_COOKIE` もそのまま残しておく。まだコードは変えない。

**Step 2 — config.py に ACCOUNTS 辞書を追加（既存変数も残す）**
- `ACCOUNTS["a"]` を追加しつつ、既存の `NOTE_SESSION_COOKIE` / `NOTE_URLNAME` も残す
- 既存コードは既存変数を引き続き参照するので動作は変わらない

**Step 3 — post.py に --account 引数を追加**
- デフォルトを `"a"` にすることで既存の呼び出し（引数なし）はAのまま動く
- `quality_check()` のキーワードリストをアカウント設定から取るよう変更

**Step 4 — automation.py に --account 引数を追加**
- `DRAFTS_FILE` / `NOTE_URLNAME` / `get_session()` をアカウント設定から取るよう変更
- `_publish_via_playwright()` に acct を引数として渡す
- 出力ディレクトリを `acct["articles_dir"]` から取る

**Step 5 — post_all.py に --account 引数を追加**
- `ARTICLES_DIR` / `POSTED_FILE` をアカウント設定から取るよう変更

**Step 6 — 既存の NOTE_SESSION_COOKIE を .env から削除**
- Step 1〜5 が完了し動作確認できてから削除する

---

### 8-7. 最小改修案（いちばん速く2アカ対応する方法）

完全リファクタリングをしなくても、以下の5箇所だけ変えれば最低限動く。

1. **.env** に `NOTE_SESSION_B` と `NOTE_URLNAME_B` を追加
2. **config.py** に `get_account(name)` を追加（既存変数はそのまま残す）
3. **post.py** の `post_article()` に `account="a"` 引数を追加し、Cookie/URLNAMEをそこから取る
4. **automation.py** の `_publish_via_playwright()` に `account="a"` 引数を追加
5. **automation.py** の `mode_auto_trend()` の `DRAFTS_FILE` / `output_dir` をアカウント別に切り替え

`post_all.py` は当面Aのみ使う前提なら変更不要。

---

### 8-8. 実装の安全な順序

```
① .env に変数追加（ゼロリスク）
   └─ 既存動作に影響なし

② config.py に get_account() 追加（ゼロリスク）
   └─ 既存コードは既存変数を使い続けるので影響なし

③ post.py の post_article() を account 引数対応（低リスク）
   └─ default="a" にすれば既存の呼び出しは全部そのまま動く
   └─ dry-run で確認してからマージ

④ automation.py を account 引数対応（中リスク）
   └─ Playwright 部分は慎重にテスト（ブラウザ操作のため失敗時に下書きが残ることがある）
   └─ mode=create-draft で Bアカウント下書きを1件テスト投稿して確認

⑤ 本運用移行
   └─ 旧 NOTE_SESSION_COOKIE を .env から削除
   └─ cron の呼び出しに --account a を明示的に追記
```

---

### 7-5. A/B テスト設計（CTA）

#### 識別子の持たせ方

`automation.py` の `mode_publish_latest()` 内で CTA を選ぶ:

```python
import itertools
CTA_CYCLE = itertools.cycle(["A", "B", "C"])   # ローテーション

# drafts.json エントリに追記
entry["cta_type"] = next(CTA_CYCLE)
```

#### records.csv との連携

`records.csv` の `cta_type` 列に A/B/C を転記するだけ。
将来的に `paid_clicks` が記録できたら:

```python
# 比較例（pandas）
df.groupby("cta_type")[["likes", "paid_clicks"]].mean()
```

#### 判断基準（目安）

- 各タイプ **10件以上** 貯まってから比較する（サンプル数が少ないと誤差大）
- 差が **1.5倍以上** あれば入れ替え検討
- 「いいね が多い = 拡散力あり」「paid_clicks が多い = 収益直結」は別物なので目的に合わせて選ぶ

