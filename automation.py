import json
import os
import sys
import logging
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

import trend_selector
import article_generator
from post import post_article, parse_markdown_file, get_session, create_note, draft_save, generate_tags
from config import NOTE_URLNAME, get_account, get_session_for

load_dotenv(Path(__file__).parent / ".env")

# 下書き管理ファイル
DRAFTS_FILE = Path(__file__).parent / "drafts.json"

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("posting.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# drafts.json ヘルパー
# ──────────────────────────────────────────

def _load_drafts(drafts_file: Path = None) -> list[dict]:
    path = drafts_file or DRAFTS_FILE
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save_drafts(drafts: list[dict], drafts_file: Path = None) -> None:
    path = drafts_file or DRAFTS_FILE
    path.write_text(
        json.dumps(drafts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ──────────────────────────────────────────
# モード: create-draft（下書き投稿 + drafts.json 記録）
# ──────────────────────────────────────────

def mode_create_draft(filepath: str, account: str = "a") -> None:
    """
    記事を下書きとして note に投稿し、note_id / key / 日時 を drafts_X.json に記録する。
    使い方: python3 automation.py --mode create-draft --file articles/article_4.md --account a
    """
    acct = get_account(account)
    drafts_path = Path(__file__).parent / acct["drafts_file"]
    logger.info(f"=== create-draft モード: {filepath} (アカウント{account.upper()}) ===")

    abs_path = str(Path(filepath).resolve())
    title, body_html, body_md = parse_markdown_file(abs_path)

    # タグ生成（失敗してもスキップ）
    tags = []
    try:
        from config import ANTHROPIC_API_KEY
        if ANTHROPIC_API_KEY:
            tags = generate_tags(title, body_md)
            logger.info(f"タグ: {tags}")
    except Exception as e:
        logger.warning(f"タグ生成スキップ: {e}")

    logger.info(f"タイトル: {title}  ({len(body_md)}字)")

    # note 作成（アカウント別セッション）
    session = get_session_for(account)
    logger.info("note 作成中...")
    note_id, key = create_note(session, title, body_html)
    logger.info(f"作成完了: note_id={note_id}, key={key}")

    # 下書き保存（is_temp_saved=true）
    logger.info("下書き保存中...")
    draft_save(session, note_id, title, body_html, body_md, publish=False, hashtags=tags)

    # drafts_X.json に記録
    entry = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "note_id": note_id,
        "key": key,
        "title": title,
        "file": abs_path,
        "published": False,
        "account": account,
    }
    drafts = _load_drafts(drafts_path)
    drafts.append(entry)
    _save_drafts(drafts, drafts_path)

    logger.info(f"✓ 下書き保存完了: https://note.com/notes/{note_id}/edit")
    logger.info(f"  {acct['drafts_file']} に記録しました (note_id={note_id})")


# ──────────────────────────────────────────
# モード: publish-latest（最新下書きを公開）
# ──────────────────────────────────────────

def _publish_via_playwright(title: str, body_md: str, tags: list, keyword: str = "お金", account: str = "a") -> str:
    """
    Firefox Playwright でエディタを開き、記事を公開して公開URLを返す。
    keyword はアイキャッチ画像の色テーマ選択に使用する。
    """
    from playwright.sync_api import sync_playwright
    import eyecatch_generator
    acct = get_account(account)
    session_cookie = acct["session_cookie"]
    urlname = acct["urlname"]

    # Markdown記号を除去した本文テキスト
    lines = []
    for line in body_md.split("\n"):
        s = line.strip()
        if s.startswith("### "): s = s[4:]
        elif s.startswith("## "): s = s[3:]
        elif s.startswith("# "): s = s[2:]
        elif s in ("---", "***", "___"): continue
        lines.append(s)
    body_text = "\n".join(lines).strip()

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        context = browser.new_context()
        context.add_cookies([
            {"name": "_note_session_v5", "value": session_cookie, "domain": "note.com", "path": "/"},
            {"name": "_note_session_v5", "value": session_cookie, "domain": "editor.note.com", "path": "/"},
        ])
        page = context.new_page()

        logger.info("  Playwright: エディタを開いています...")
        page.goto("https://editor.note.com/new/")
        time.sleep(3)
        page.keyboard.press("Escape")
        time.sleep(0.5)

        # タイトル入力
        page.locator('[placeholder="記事タイトル"]').first.click()
        page.keyboard.type(title, delay=0)
        time.sleep(0.3)
        logger.info(f"  タイトル入力完了: {title}")

        # 本文入力
        page.locator(".ProseMirror").first.click()
        time.sleep(0.3)
        paragraphs = [l for l in body_text.split("\n") if l.strip()]
        for i, para in enumerate(paragraphs):
            page.keyboard.type(para, delay=0)
            if i < len(paragraphs) - 1:
                page.keyboard.press("Enter")
        time.sleep(2)
        pm_len = len(page.locator(".ProseMirror").first.inner_text())
        logger.info(f"  本文入力完了: {pm_len}字")

        # ── アイキャッチ画像をアップロード ──────────────────────────
        try:
            eyecatch_path = eyecatch_generator.generate(title, keyword)
            logger.info(f"  アイキャッチ生成: {eyecatch_path}")

            eyecatch_btn = page.locator('[aria-label="画像を追加"]').first
            if eyecatch_btn.count() > 0:
                with page.expect_file_chooser(timeout=12000) as fc_info:
                    eyecatch_btn.click(force=True)
                    time.sleep(1.5)
                    # 「画像をアップロード」ボタンを探す
                    for b in page.locator("button").all():
                        try:
                            if "画像をアップロード" in (b.text_content() or ""):
                                box = b.bounding_box()
                                if box and box["width"] > 0:
                                    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                    break
                        except Exception:
                            pass

                fc_info.value.set_files(eyecatch_path)
                time.sleep(4)

                # CropModal の「保存」を確定（ReactModalPortal 内に限定）
                modal = page.locator('.ReactModalPortal')
                if modal.count() > 0:
                    save_btn = modal.get_by_role("button", name="保存", exact=True)
                    if save_btn.count() > 0:
                        save_btn.first.wait_for(state="visible", timeout=6000)
                        save_btn.first.click()
                        logger.info("  CropModal 確定")
                        time.sleep(3)

                # モーダルが消えるまで待つ
                try:
                    page.locator('.ReactModal__Overlay').first.wait_for(state="hidden", timeout=10000)
                except Exception:
                    pass
                time.sleep(2)
                logger.info("  アイキャッチ設定完了")
            else:
                logger.warning("  ⚠ 「画像を追加」ボタンが見つからない（アイキャッチをスキップ）")
        except Exception as e:
            logger.warning(f"  ⚠ アイキャッチ設定失敗（スキップして続行）: {e}")

        # 公開に進む
        page.locator('button:has-text("公開に進む")').first.click()
        time.sleep(3)

        # ハッシュタグ入力
        if tags:
            tag_input = page.locator('[placeholder="ハッシュタグを追加する"]').first
            for tag in tags:
                tag_input.click()
                page.keyboard.type(tag, delay=0)
                page.keyboard.press("Enter")
                time.sleep(0.3)
            logger.info(f"  タグ入力完了: {tags}")

        # 投稿する
        page.locator('button:has-text("投稿する")').first.click()
        logger.info("  「投稿する」クリック")
        time.sleep(5)

        final_url = page.url
        browser.close()

    # 公開URLを抽出
    if "/notes/" in final_url and "/publish" in final_url:
        note_key = final_url.split("/notes/")[-1].split("/")[0]
        return f"https://note.com/{urlname}/n/{note_key}"
    return final_url


def mode_publish_latest(account: str = "a") -> None:
    """
    drafts_X.json から最後に作成された未公開下書きを取得し、Playwright で公開する。
    使い方: python3 automation.py --mode publish-latest --account a
    """
    acct = get_account(account)
    drafts_path = Path(__file__).parent / acct["drafts_file"]
    logger.info(f"=== publish-latest モード (アカウント{account.upper()}) ===")

    drafts = _load_drafts(drafts_path)
    if not drafts:
        logger.error(f"{acct['drafts_file']} が空です。先に --mode auto-trend を実行してください。")
        sys.exit(1)

    unpublished = [d for d in drafts if not d.get("published") and Path(d.get("file", "")).exists()]
    if not unpublished:
        logger.error("未公開の下書きがありません。")
        sys.exit(1)

    entry    = unpublished[-1]
    title    = entry["title"]
    filepath = entry["file"]
    keyword  = entry.get("keyword") or trend_selector._extract_keyword(title)
    logger.info(f"対象: {title}")
    logger.info(f"note_id: {entry.get('note_id')} / key: {entry.get('key')}")
    logger.info(f"ファイル: {filepath}")

    _, body_html, body_md = parse_markdown_file(filepath)

    tags = []
    try:
        from config import ANTHROPIC_API_KEY
        if ANTHROPIC_API_KEY:
            tags = generate_tags(title, body_md)
            logger.info(f"タグ: {tags}")
    except Exception as e:
        logger.warning(f"タグ生成スキップ: {e}")

    public_url = _publish_via_playwright(title, body_md, tags, keyword=keyword, account=account)

    # drafts_X.json を更新
    for d in drafts:
        if d.get("file") == entry["file"]:
            d["published"] = True
            d["published_at"] = datetime.now().isoformat(timespec="seconds")
            d["public_url"] = public_url
            break
    _save_drafts(drafts, drafts_path)

    logger.info(f"✓ 公開完了: {public_url}")


# ──────────────────────────────────────────

def run_daily_trend_post(dry_run=False, account: str = "a"):
    """朝8時のトレンド連動投稿タスク"""
    logger.info(f"=== 朝8時のトレンド連動投稿を開始 (dry_run={dry_run}, account={account}) ===")

    try:
        logger.info("トレンドを取得中...")
        trends = trend_selector.get_google_trends()
        if not trends:
            logger.warning("トレンドが取得できませんでした。デフォルトテーマで進行します。")

        theme = trend_selector.select_theme(trends)
        logger.info(f"選定されたテーマ: {theme}")

        logger.info("記事を生成中...")
        title, body = article_generator.generate_article(theme)

        logger.info("投稿を開始します...")
        post_article(title=title, body_html=body, body_md=body, publish=True, dry_run=dry_run, account=account)
        logger.info(f"✓ トレンド連動記事の投稿が完了しました: {title}")
        return True

    except ValueError as ve:
        logger.error(f"品質チェック不合格またはバリデーションエラー: {ve}")
        return False
    except Exception as e:
        logger.exception(f"トレンド投稿中に予期せぬエラーが発生しました: {e}")
        return False


def run_stock_post(dry_run=False, account: str = "a"):
    """14時のストック消化投稿タスク"""
    logger.info(f"=== 14時のストック消化投稿を開始 (dry_run={dry_run}, account={account}) ===")

    try:
        from post_all import get_article_files, load_posted, save_posted
        from post import parse_markdown_file

        all_files = get_article_files()
        posted = load_posted()
        pending = [f for f in all_files if f.name not in posted]

        if not pending:
            logger.info("ストック記事がありません。")
            return

        target_file = pending[0]
        logger.info(f"投稿対象ファイル: {target_file.name}")

        title, body_html, body_md = parse_markdown_file(str(target_file))
        post_article(title, body_html, body_md, publish=True, dry_run=dry_run, account=account)

        if not dry_run:
            save_posted(target_file.name)
        logger.info(f"✓ ストック記事の投稿が完了しました: {target_file.name}")

    except ValueError as ve:
        logger.error(f"ストック記事の品質チェック不合格: {ve}")
    except Exception as e:
        logger.exception(f"ストック投稿中に予期せぬエラーが発生しました: {e}")

# ──────────────────────────────────────────
# モード: auto-trend（完全自動フロー）
# ──────────────────────────────────────────

def mode_auto_trend(account: str = "a") -> None:
    """
    完全自動フロー:
      トレンド取得 → テーマ選定 → 記事生成 → .md 保存 → drafts_X.json 記録

    cron での使い方:
      python3 automation.py --mode auto-trend --account a
    """
    acct = get_account(account)
    drafts_path = Path(__file__).parent / acct["drafts_file"]
    output_dir  = Path(acct["articles_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"=== auto-trend: 完全自動フロー開始 (アカウント{account.upper()}) ===")

    # ① トレンド取得 & テーマ選定
    logger.info("① Google Trends 取得中...")
    topic_info = trend_selector.select_today_theme()
    logger.info(f"   picked_topic : {topic_info['topic']}")
    logger.info(f"   trend_raw    : {topic_info['picked_raw']} (score={topic_info['score']})")
    logger.info(f"   keyword      : {topic_info['keyword']}")

    # ② 記事生成（taku キャラ / アカウントAのみ対応。Bは今後拡張）
    logger.info(f"② 記事生成中 (Claude / taku キャラ)...")
    title, body_md = article_generator.generate_article_taku(topic_info)
    logger.info(f"   タイトル: {title}  ({len(body_md)}字)")

    # ③ .md ファイルに保存（同日ファイルがあれば連番で回避）
    today    = datetime.now().strftime("%Y%m%d")
    filepath = output_dir / f"article_{today}.md"
    if filepath.exists():
        n = 2
        while (output_dir / f"article_{today}_{n}.md").exists():
            n += 1
        filepath = output_dir / f"article_{today}_{n}.md"

    filepath.write_text(f"# {title}\n\n{body_md}", encoding="utf-8")
    logger.info(f"③ ファイル保存: {filepath}")

    # ④ drafts_X.json に記録（21時の publish-latest で Playwright 投稿）
    entry = {
        "created_at":   datetime.now().isoformat(timespec="seconds"),
        "note_id":      None,
        "key":          None,
        "title":        title,
        "file":         str(filepath.resolve()),
        "published":    False,
        "account":      account,
        "picked_topic": topic_info["topic"],
        "trend_raw":    topic_info["picked_raw"],
        "keyword":      topic_info["keyword"],
    }
    drafts = _load_drafts(drafts_path)
    drafts.append(entry)
    _save_drafts(drafts, drafts_path)

    logger.info(f"✓ 記事生成完了: {filepath}")
    logger.info(f"  {acct['drafts_file']} に記録しました（21時に自動公開）")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=[
            "auto-trend",      # 完全自動: トレンド取得→記事生成→下書き保存
            "publish-latest",  # 最新下書きを公開
            "create-draft",    # 指定ファイルを下書き保存
            "trend", "stock", "scheduler",
            "dry-post-once", "test-post-once",
        ],
        default="scheduler",
        help="実行モード",
    )
    parser.add_argument("--dry-run", action="store_true", help="実際に投稿せずに動作確認")
    parser.add_argument("--publish", action="store_true", help="テスト投稿で公開する (デフォルトは下書き)")
    parser.add_argument("--file", help="テスト投稿に使用するファイル (例: articles/article_4.md)")
    parser.add_argument("--account", choices=["a", "b"], default="a", help="投稿先アカウント (default: a)")
    args = parser.parse_args()

    if args.mode == "auto-trend":
        mode_auto_trend(account=args.account)

    elif args.mode == "dry-post-once":
        if not args.file:
            print("エラー: --file でファイルを指定してください（例: --file articles/article_4.md）")
            sys.exit(1)
        logger.info(f"=== dry-post-once モード (ファイル: {args.file}, account={args.account}) ===")
        from post import parse_markdown_file
        title, body_html, body_md = parse_markdown_file(args.file)
        post_article(title=title, body_html=body_html, body_md=body_md, publish=args.publish, dry_run=True, account=args.account)

    elif args.mode == "test-post-once":
        if not args.file:
            print("エラー: --file でファイルを指定してください（例: --file articles/article_4.md）")
            sys.exit(1)
        logger.info(f"=== test-post-once モード (ファイル: {args.file}, publish={args.publish}, account={args.account}) ===")
        from post import parse_markdown_file
        title, body_html, body_md = parse_markdown_file(args.file)
        post_article(title=title, body_html=body_html, body_md=body_md, publish=args.publish, dry_run=False, account=args.account)

    elif args.mode == "create-draft":
        if not args.file:
            print("エラー: --file でファイルを指定してください（例: --file articles/article_4.md）")
            sys.exit(1)
        mode_create_draft(args.file, account=args.account)

    elif args.mode == "publish-latest":
        mode_publish_latest(account=args.account)

    elif args.mode == "trend":
        run_daily_trend_post(dry_run=args.dry_run, account=args.account)
    elif args.mode == "stock":
        run_stock_post(dry_run=args.dry_run, account=args.account)
    elif args.mode == "scheduler":
        logger.info(f"スケジューラーモードで起動しました (account={args.account} / 7時: テーマ決定, 8時: 投稿, 14時: ストック投稿)")
        current_theme = None
        while True:
            now = datetime.now()
            if now.hour == 7 and now.minute == 0:
                logger.info("--- 7:00 トレンド取得とテーマ決定を開始 ---")
                trends = trend_selector.get_google_trends()
                current_theme = trend_selector.select_theme(trends)
                logger.info(f"決定されたテーマ: {current_theme}")
                Path("current_theme.txt").write_text(current_theme, encoding="utf-8")
                time.sleep(60)

            if now.hour == 8 and now.minute == 0:
                logger.info("--- 8:00 トレンド連動記事の生成と投稿を開始 ---")
                theme = current_theme
                if not theme and Path("current_theme.txt").exists():
                    theme = Path("current_theme.txt").read_text(encoding="utf-8")

                if theme:
                    logger.info(f"テーマ「{theme}」で記事を生成中...")
                    title, body = article_generator.generate_article(theme)
                    try:
                        post_article(title=title, body_html=body, body_md=body, publish=True, dry_run=args.dry_run, account=args.account)
                        logger.info(f"✓ トレンド連動記事の投稿が完了しました: {title}")
                    except Exception as e:
                        logger.error(f"投稿エラー: {e}")
                else:
                    logger.warning("テーマが決定されていないため、投稿をスキップします。")
                time.sleep(60)

            if now.hour == 14 and now.minute == 0:
                run_stock_post(dry_run=args.dry_run, account=args.account)
                time.sleep(60)

            time.sleep(30)
