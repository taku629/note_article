"""
note.com 一括投稿スクリプト

使い方:
  python post_all.py --dry-run --limit 5        # 動作確認
  python post_all.py --limit 10 --interval 60   # 下書き10件
  python post_all.py --publish --limit 5        # 5件公開
"""

import argparse
import sys
import time
from pathlib import Path

from config import DEFAULT_INTERVAL, NOTE_SESSION_COOKIE
from post import parse_markdown_file, post_article

# 投稿済みファイルを記録するリスト
POSTED_FILE = Path(__file__).parent / "posted.txt"

# articles フォルダのパス
ARTICLES_DIR = Path(__file__).parent / "articles"


def load_posted() -> set[str]:
    """投稿済みファイル名の集合を返す。"""
    if not POSTED_FILE.exists():
        return set()
    return set(POSTED_FILE.read_text(encoding="utf-8").splitlines())


def save_posted(filename: str) -> None:
    """投稿済みファイル名を posted.txt に追記する。"""
    with POSTED_FILE.open("a", encoding="utf-8") as f:
        f.write(filename + "\n")


def get_article_files() -> list[Path]:
    """
    articles/ フォルダ内の .md / .txt / .html ファイルを
    ファイル名の自然順（数値順）でソートして返す。
    """
    files = sorted(
        ARTICLES_DIR.glob("*.md"),
        key=lambda p: _natural_sort_key(p.name),
    )
    files += sorted(
        ARTICLES_DIR.glob("*.txt"),
        key=lambda p: _natural_sort_key(p.name),
    )
    files += sorted(
        ARTICLES_DIR.glob("*.html"),
        key=lambda p: _natural_sort_key(p.name),
    )
    return files


def _natural_sort_key(s: str):
    """
    ファイル名を自然順（article_2 < article_10）でソートするためのキー。
    """
    import re
    parts = re.split(r"(\d+)", s)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="articles/ フォルダの記事を一括投稿するスクリプト"
    )
    parser.add_argument(
        "--publish", action="store_true", help="公開投稿する（デフォルト: 下書き）"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"投稿間隔（秒）。デフォルト: {DEFAULT_INTERVAL}秒",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="投稿数の上限。指定しない場合は全件投稿",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際のAPIコールを行わずに動作確認する",
    )
    args = parser.parse_args()

    # 認証チェック（dry-run 以外）
    if not args.dry_run and not NOTE_SESSION_COOKIE:
        print(
            "エラー: .env に NOTE_SESSION_COOKIE が設定されていません。",
            file=sys.stderr,
        )
        sys.exit(1)

    # 記事ファイルの一覧を取得
    all_files = get_article_files()
    if not all_files:
        print(f"記事が見つかりません: {ARTICLES_DIR}")
        sys.exit(1)

    # 投稿済みをスキップ
    posted = load_posted()
    pending = [f for f in all_files if f.name not in posted]

    if not pending:
        print("全記事が投稿済みです。")
        return

    # --limit で件数を絞る
    if args.limit is not None:
        pending = pending[: args.limit]

    total = len(pending)
    mode = "公開" if args.publish else "下書き保存"
    print(f"投稿対象: {total} 件 / モード: {mode} / 間隔: {args.interval}秒")
    if args.dry_run:
        print("[dry-run モード] APIコールはスキップします。\n")

    success = 0
    for i, filepath in enumerate(pending, start=1):
        print(f"\n[{i}/{total}] {filepath.name}")
        print("-" * 50)

        try:
            title, body_html, body_md = parse_markdown_file(str(filepath))
            post_article(
                title=title,
                body_html=body_html,
                body_md=body_md,
                publish=args.publish,
                dry_run=args.dry_run,
            )
            # 投稿済みとして記録（dry-run でも記録しない）
            if not args.dry_run:
                save_posted(filepath.name)
            success += 1

        except FileNotFoundError as e:
            print(f"  ✗ スキップ（ファイルなし）: {e}", file=sys.stderr)
        except PermissionError as e:
            # 認証エラーは継続不可のため即終了
            print(f"\n  ✗ 認証エラーのため処理を中断します: {e}", file=sys.stderr)
            break
        except Exception as e:
            print(f"  ✗ エラー: {e}", file=sys.stderr)
            # 1件失敗しても次の記事に進む

        # 最後の1件の後はインターバルを入れない
        if i < total and not args.dry_run:
            print(f"  （{args.interval}秒待機中...）", flush=True)
            time.sleep(args.interval)

    print(f"\n{'='*50}")
    print(f"完了: {success}/{total} 件を投稿しました。")
    if not args.dry_run and success > 0:
        print(f"投稿済みリスト: {POSTED_FILE}")


if __name__ == "__main__":
    main()
