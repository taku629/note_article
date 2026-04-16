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
from config import NOTE_URLNAME

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

def _load_drafts() -> list[dict]:
    if not DRAFTS_FILE.exists():
        return []
    return json.loads(DRAFTS_FILE.read_text(encoding="utf-8"))


def _save_drafts(drafts: list[dict]) -> None:
    DRAFTS_FILE.write_text(
        json.dumps(drafts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ──────────────────────────────────────────
# モード: create-draft（下書き投稿 + drafts.json 記録）
# ──────────────────────────────────────────

def mode_create_draft(filepath: str) -> None:
    """
    記事を下書きとして note に投稿し、note_id / key / 日時 を drafts.json に記録する。
    使い方: python3 automation.py --mode create-draft --file articles/article_4.md
    """
    logger.info(f"=== create-draft モード: {filepath} ===")

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

    # note 作成
    session = get_session()
    logger.info("note 作成中...")
    note_id, key = create_note(session, title, body_html)
    logger.info(f"作成完了: note_id={note_id}, key={key}")

    # 下書き保存（is_temp_saved=true）
    logger.info("下書き保存中...")
    draft_save(session, note_id, title, body_html, body_md, publish=False, hashtags=tags)

    # drafts.json に記録
    entry = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "note_id": note_id,
        "key": key,
        "title": title,
        "file": abs_path,
        "published": False,
    }
    drafts = _load_drafts()
    drafts.append(entry)
    _save_drafts(drafts)

    logger.info(f"✓ 下書き保存完了: https://note.com/notes/{note_id}/edit")
    logger.info(f"  drafts.json に記録しました (note_id={note_id})")


# ──────────────────────────────────────────
# モード: publish-latest（最新下書きを公開）
# ──────────────────────────────────────────

def mode_publish_latest() -> None:
    """
    drafts.json から最後に作成された未公開下書きを取得し、公開状態に切り替える。
    使い方: python3 automation.py --mode publish-latest
    """
    logger.info("=== publish-latest モード ===")

    drafts = _load_drafts()
    if not drafts:
        logger.error("drafts.json が空です。先に --mode create-draft を実行してください。")
        sys.exit(1)

    # 最新の未公開エントリを取得
    unpublished = [d for d in drafts if not d.get("published")]
    if not unpublished:
        logger.error("未公開の下書きがありません。全件公開済みです。")
        sys.exit(1)

    entry = unpublished[-1]
    note_id = entry["note_id"]
    key     = entry["key"]
    title   = entry["title"]
    filepath = entry["file"]

    logger.info(f"対象: {title}")
    logger.info(f"note_id: {note_id} / key: {key}")
    logger.info(f"ファイル: {filepath}")

    # 本文を再読込してタグ生成
    _, body_html, body_md = parse_markdown_file(filepath)
    tags = []
    try:
        from config import ANTHROPIC_API_KEY
        if ANTHROPIC_API_KEY:
            tags = generate_tags(title, body_md)
    except Exception as e:
        logger.warning(f"タグ生成スキップ: {e}")

    # 公開（is_temp_saved=false）
    session = get_session()
    logger.info("公開中 (is_temp_saved=false)...")
    draft_save(session, note_id, title, body_html, body_md, publish=True, hashtags=tags)

    # drafts.json の published フラグを更新
    for d in drafts:
        if d["note_id"] == note_id:
            d["published"] = True
            d["published_at"] = datetime.now().isoformat(timespec="seconds")
            break
    _save_drafts(drafts)

    url = f"https://note.com/{NOTE_URLNAME}/n/{key}"
    logger.info(f"✓ 公開完了: {url}")


# ──────────────────────────────────────────

def run_daily_trend_post(dry_run=False):
    """朝8時のトレンド連動投稿タスク"""
    logger.info(f"=== 朝8時のトレンド連動投稿を開始 (dry_run={dry_run}) ===")
    
    try:
        # 1. トレンド取得 & テーマ選定
        logger.info("トレンドを取得中...")
        trends = trend_selector.get_google_trends()
        if not trends:
            logger.warning("トレンドが取得できませんでした。デフォルトテーマで進行します。")
        
        theme = trend_selector.select_theme(trends)
        logger.info(f"選定されたテーマ: {theme}")
        
        # 2. 記事生成
        logger.info("記事を生成中...")
        title, body = article_generator.generate_article(theme)
        
        # 3. note投稿 (post_article がタグ生成と品質チェックも行う)
        logger.info("投稿を開始します...")
        post_article(title=title, body_html=body, body_md=body, publish=True, dry_run=dry_run)
        logger.info(f"✓ トレンド連動記事の投稿が完了しました: {title}")
        return True
            
    except ValueError as ve:
        logger.error(f"品質チェック不合格またはバリデーションエラー: {ve}")
        return False
    except Exception as e:
        logger.exception(f"トレンド投稿中に予期せぬエラーが発生しました: {e}")
        return False

def run_stock_post(dry_run=False):
    """14時のストック消化投稿タスク"""
    logger.info(f"=== 14時のストック消化投稿を開始 (dry_run={dry_run}) ===")
    
    try:
        from post_all import get_article_files, load_posted, save_posted
        from post import parse_markdown_file
        
        all_files = get_article_files()
        posted = load_posted()
        pending = [f for f in all_files if f.name not in posted]
        
        if not pending:
            logger.info("ストック記事がありません。")
            return
        
        # 自然順で最初の1件
        target_file = pending[0]
        logger.info(f"投稿対象ファイル: {target_file.name}")
        
        title, body_html, body_md = parse_markdown_file(str(target_file))
        
        # 投稿 (公開) - post_article が品質チェックも行う
        post_article(title, body_html, body_md, publish=True, dry_run=dry_run)
        
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

def mode_auto_trend() -> None:
    """
    完全自動フロー:
      トレンド取得 → テーマ選定 → 記事生成 → .md 保存 → 下書き投稿 → drafts.json 記録

    cron での使い方:
      python3 automation.py --mode auto-trend
    実行ログ出力項目:
      picked_topic, trend_raw, keyword, file_path, note_id, key, 下書きURL
    """
    logger.info("=== auto-trend: 完全自動フロー開始 ===")

    # ① トレンド取得 & テーマ選定
    logger.info("① Google Trends 取得中...")
    topic_info = trend_selector.select_today_theme()
    logger.info(f"   picked_topic : {topic_info['topic']}")
    logger.info(f"   trend_raw    : {topic_info['picked_raw']} (score={topic_info['score']})")
    logger.info(f"   keyword      : {topic_info['keyword']}")

    # ② 記事生成（大学生 taku キャラ）
    logger.info("② 記事生成中 (Claude / taku キャラ)...")
    title, body_md = article_generator.generate_article_taku(topic_info)
    logger.info(f"   タイトル: {title}  ({len(body_md)}字)")

    # ③ .md ファイルに保存（同日ファイルがあれば連番で回避）
    today      = datetime.now().strftime("%Y%m%d")
    output_dir = Path("/home/tk250127/note-articles/output")
    filepath   = output_dir / f"article_{today}.md"
    if filepath.exists():
        n = 2
        while (output_dir / f"article_{today}_{n}.md").exists():
            n += 1
        filepath = output_dir / f"article_{today}_{n}.md"

    filepath.write_text(f"# {title}\n\n{body_md}", encoding="utf-8")
    logger.info(f"③ ファイル保存: {filepath}")

    # ④ note 下書き投稿
    logger.info("④ note 下書き投稿中 (is_temp_saved=true)...")
    _, body_html, body_md_parsed = parse_markdown_file(str(filepath))

    tags = []
    try:
        from config import ANTHROPIC_API_KEY
        if ANTHROPIC_API_KEY:
            tags = generate_tags(title, body_md_parsed)
            logger.info(f"   タグ: {tags}")
    except Exception as e:
        logger.warning(f"   タグ生成スキップ: {e}")

    session = get_session()
    note_id, key = create_note(session, title, body_html)
    draft_save(session, note_id, title, body_html, body_md_parsed, publish=False, hashtags=tags)

    # ⑤ drafts.json に記録
    entry = {
        "created_at":   datetime.now().isoformat(timespec="seconds"),
        "note_id":      note_id,
        "key":          key,
        "title":        title,
        "file":         str(filepath.resolve()),
        "published":    False,
        "picked_topic": topic_info["topic"],
        "trend_raw":    topic_info["picked_raw"],
    }
    drafts = _load_drafts()
    drafts.append(entry)
    _save_drafts(drafts)

    logger.info(f"   note_id : {note_id}")
    logger.info(f"   key     : {key}")
    logger.info(f"✓ 下書き保存完了: https://note.com/notes/{note_id}/edit")
    logger.info(f"  Markdown : {filepath}")
    logger.info(f"  drafts.json に記録しました")


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
    args = parser.parse_args()
    
    if args.mode == "auto-trend":
        mode_auto_trend()

    elif args.mode == "dry-post-once":
        if not args.file:
            print("エラー: --file でファイルを指定してください（例: --file articles/article_4.md）")
            sys.exit(1)
        logger.info(f"=== dry-post-once モード (ファイル: {args.file}) ===")
        from post import parse_markdown_file
        title, body_html, body_md = parse_markdown_file(args.file)
        post_article(title=title, body_html=body_html, body_md=body_md, publish=args.publish, dry_run=True)

    elif args.mode == "test-post-once":
        if not args.file:
            print("エラー: --file でファイルを指定してください（例: --file articles/article_4.md）")
            sys.exit(1)
        logger.info(f"=== test-post-once モード (ファイル: {args.file}, publish={args.publish}) ===")
        from post import parse_markdown_file
        title, body_html, body_md = parse_markdown_file(args.file)
        # 1件だけ投稿を実行
        post_article(title=title, body_html=body_html, body_md=body_md, publish=args.publish, dry_run=False)

    elif args.mode == "create-draft":
        if not args.file:
            print("エラー: --file でファイルを指定してください（例: --file articles/article_4.md）")
            sys.exit(1)
        mode_create_draft(args.file)

    elif args.mode == "publish-latest":
        mode_publish_latest()

    elif args.mode == "trend":
        run_daily_trend_post(dry_run=args.dry_run)
    elif args.mode == "stock":
        run_stock_post(dry_run=args.dry_run)
    elif args.mode == "scheduler":
        logger.info("スケジューラーモードで起動しました（7時: テーマ決定, 8時: 投稿, 14時: ストック投稿）")
        current_theme = None
        while True:
            now = datetime.now()
            # 7:00 トレンド取得 & テーマ決定
            if now.hour == 7 and now.minute == 0:
                logger.info("--- 7:00 トレンド取得とテーマ決定を開始 ---")
                trends = trend_selector.get_google_trends()
                current_theme = trend_selector.select_theme(trends)
                logger.info(f"決定されたテーマ: {current_theme}")
                # ファイルに保存しておく（念のため）
                Path("current_theme.txt").write_text(current_theme, encoding="utf-8")
                time.sleep(60)

            # 8:00 トレンド投稿
            if now.hour == 8 and now.minute == 0:
                logger.info("--- 8:00 トレンド連動記事の生成と投稿を開始 ---")
                theme = current_theme
                if not theme and Path("current_theme.txt").exists():
                    theme = Path("current_theme.txt").read_text(encoding="utf-8")
                
                if theme:
                    # 記事生成 & 投稿
                    logger.info(f"テーマ「{theme}」で記事を生成中...")
                    title, body = article_generator.generate_article(theme)
                    try:
                        post_article(title=title, body_html=body, body_md=body, publish=True, dry_run=args.dry_run)
                        logger.info(f"✓ トレンド連動記事の投稿が完了しました: {title}")
                    except Exception as e:
                        logger.error(f"投稿エラー: {e}")
                else:
                    logger.warning("テーマが決定されていないため、投稿をスキップします。")
                time.sleep(60)
            
            # 14:00 ストック投稿
            if now.hour == 14 and now.minute == 0:
                run_stock_post(dry_run=args.dry_run)
                time.sleep(60)
                
            time.sleep(30)
