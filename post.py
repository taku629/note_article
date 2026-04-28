"""
note.com 単体投稿スクリプト

使い方:
  python post.py --file articles/article_10.md           # 下書き保存
  python post.py --file articles/article_10.md --publish # 公開投稿
  python post.py --title "タイトル" --body "本文" --dry-run
"""

import argparse
import re
import sys
import time
import uuid
from pathlib import Path

import requests

try:
    import markdown
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False

from config import (
    NOTE_SESSION_COOKIE,
    ANTHROPIC_API_KEY,
    API_CREATE,
    API_DRAFT,
    MAX_RETRY,
    RETRY_WAIT,
    get_headers,
    get_session,
    get_account,
    get_session_for,
)

# note.com のユーザー名（公開URL構築に使う）
NOTE_URLNAME = "taku629"


def markdown_to_note_html(md_text: str) -> tuple[str, int]:
    """
    Markdown を note 独自の HTML 形式に変換する。
    各タグに uuid4() で生成した name 属性と id 属性を付与する。
    戻り値: (html文字列, テキスト文字数)
    """
    lines = md_text.split("\n")
    html_parts = []
    text_length = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        uid = str(uuid.uuid4())

        if line.startswith("### "):
            text = line[4:]
            html_parts.append(f'<h3 name="{uid}" id="{uid}">{text}</h3>')
        elif line.startswith("## "):
            text = line[3:]
            html_parts.append(f'<h2 name="{uid}" id="{uid}">{text}</h2>')
        elif line.startswith("# "):
            text = line[2:]
            html_parts.append(f'<h1 name="{uid}" id="{uid}">{text}</h1>')
        else:
            html_parts.append(f'<p name="{uid}" id="{uid}">{line}</p>')

        text_length += len(line)

    return "".join(html_parts), text_length


def parse_markdown_file(filepath: str) -> tuple[str, str, str]:
    """
    Markdown ファイルを読み込み、(タイトル, body_html, body_md) を返す。
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {filepath}")

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    title = ""
    body_start = 0
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        body_start = 1
        while body_start < len(lines) and lines[body_start].strip() == "":
            body_start += 1
    else:
        title = path.stem

    body_md = "\n".join(lines[body_start:])

    if HAS_MARKDOWN:
        body_html = markdown.markdown(body_md, extensions=["extra", "nl2br"])
    else:
        body_html = body_md

    return title, body_html, body_md


def generate_tags(title: str, body_md: str) -> list[str]:
    """記事タイトルと本文からnote用ハッシュタグを5個生成する（新ルール準拠）。"""
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = (
        f"以下のnote記事に最適なハッシュタグを5個生成してください。\n"
        f"タイトル: {title}\n"
        f"本文冒頭: {body_md[:500]}\n\n"
        f"【タグ生成ルール】\n"
        f"- 合計5個\n"
        f"- 1個：超汎用タグ（「大学生」「副業」「お金」のどれか1つ）\n"
        f"- 2個：テーマ関連の中規模タグ（「大学生副業」「節約術」「就活対策」など）\n"
        f"- 2個：記事特有のニッチタグ\n\n"
        f"ハッシュタグはカンマ区切りで出力し、#は不要です。"
    )
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
    )
    tags = [t.strip() for t in response.content[0].text.strip().split(",")]
    return tags[:5]


def quality_check(
    title: str,
    body_md: str,
    tags: list[str],
    keywords: list[str] = None,
) -> list[str]:
    """投稿前の品質チェック。keywords 未指定時はアカウントA向けデフォルトを使う。"""
    errors = []
    if len(body_md) < 1500:
        errors.append(f"文字数が足りません ({len(body_md)}字)。1500字以上必要です。")

    _keywords = keywords or ["大学生", "副業", "バイト", "奨学金", "就活", "インターン", "資産形成", "節約", "フリーランス", "スキルアップ", "お金の勉強"]
    if not any(kw in title for kw in _keywords):
        errors.append(f"タイトルに主要キーワード（{_keywords[0]} 等）が含まれていません。")

    if len(tags) < 5:
        errors.append(f"タグが足りません ({len(tags)}個)。5個必要です。")

    return errors


def _post_with_retry(
    session: requests.Session,
    url: str,
    payload: dict,
    ok_statuses: set = None,
) -> requests.Response:
    if ok_statuses is None:
        ok_statuses = {200, 201}

    headers = get_headers()
    for attempt in range(1, MAX_RETRY + 1):
        print(f"  [API Call] URL: {url}")
        resp = session.post(url, json=payload, headers=headers, timeout=30)
        print(f"  [API Response] Status: {resp.status_code}")
        
        if resp.status_code in ok_statuses:
            return resp
        if resp.status_code == 401:
            raise PermissionError("認証エラー (401): Cookieが無効です")
        if resp.status_code == 403:
            raise PermissionError("アクセス拒否 (403): 権限がありません")
        if resp.status_code == 429:
            print(f"  ⚠ レートリミット (429)。リトライします ({attempt}/{MAX_RETRY})")
            time.sleep(RETRY_WAIT * attempt)
            continue
        raise RuntimeError(f"APIエラー ({resp.status_code}): {url}\n{resp.text[:500]}")
    raise RuntimeError(f"最大リトライ回数を超えました: {url}")


def create_note(session: requests.Session, title: str, body: str) -> tuple[str, str]:
    payload = {"name": title, "body": body}
    resp = _post_with_retry(session, API_CREATE, payload)
    data = resp.json().get("data", resp.json())
    return str(data.get("id")), str(data.get("key", ""))


def draft_save(
    session: requests.Session,
    note_id: str,
    title: str,
    body_html: str,
    body_md: str,
    publish: bool = False,
    hashtags: list = None
) -> dict:
    note_html, body_length = markdown_to_note_html(body_md)
    is_temp = "false" if publish else "true"
    url = f"{API_DRAFT}?id={note_id}&is_temp_saved={is_temp}"
    
    payload = {
        "name": title,
        "body": note_html,
        "body_length": body_length,
        "index": False,
        "is_lead_form": False,
        "hashtags": hashtags or [],
    }
    resp = _post_with_retry(session, url, payload)
    return resp.json()


def post_article(
    title: str,
    body_html: str,
    body_md: str = "",
    publish: bool = False,
    dry_run: bool = False,
    account: str = "a",
) -> None:
    acct = get_account(account)
    urlname = acct["urlname"]
    quality_keywords = acct["quality_keywords"]

    hashtags = []
    if ANTHROPIC_API_KEY:
        try:
            hashtags = generate_tags(title, body_md or body_html)
        except Exception as e:
            print(f"  ⚠ タグ生成エラー: {e}")

    errors = quality_check(title, body_md or body_html, hashtags, keywords=quality_keywords)
    if errors:
        print("  ✗ 品質チェック不合格。投稿を中止します。")
        for err in errors:
            print(f"    - {err}")
        raise ValueError(f"Quality check failed: {', '.join(errors)}")

    print(f"タイトル  : {title}")
    print(f"本文文字数: {len(body_md or body_html)} 文字")
    print(f"投稿先    : アカウント{account.upper()} ({urlname})")
    print(f"投稿モード: {'公開' if publish else '下書き保存'}")
    print(f"タグ      : {', '.join(hashtags)}")

    if dry_run:
        print("[dry-run] 実際のAPIコールはスキップします。")
        return

    cookie = acct["session_cookie"]
    if not cookie:
        print(f"エラー: アカウント'{account}' の NOTE_SESSION_{account.upper()} が .env に設定されていません。", file=sys.stderr)
        sys.exit(1)

    session = get_session_for(account)
    print("  → note を作成中...", end=" ", flush=True)
    note_id, key = create_note(session, title, body_html)
    print(f"完了 (note_id={note_id}, key={key})")

    if publish:
        print("  → 本文保存 & 公開中...", end=" ", flush=True)
        draft_save(session, note_id, title, body_html, body_md or body_html, publish=True, hashtags=hashtags)
        print("完了")
        print(f"✓ 公開完了: https://note.com/{urlname}/n/{key}")
    else:
        print("  → 本文を下書き保存中...", end=" ", flush=True)
        draft_save(session, note_id, title, body_html, body_md or body_html, publish=False, hashtags=hashtags)
        print("完了")
        print(f"✓ 下書き保存完了: https://note.com/notes/{note_id}/edit")


def main() -> None:
    parser = argparse.ArgumentParser(description="note.com に記事を投稿するスクリプト")
    parser.add_argument("--file", help="投稿する Markdown ファイルのパス")
    parser.add_argument("--title", help="記事タイトル")
    parser.add_argument("--body", help="記事本文")
    parser.add_argument("--publish", action="store_true", help="公開する")
    parser.add_argument("--dry-run", action="store_true", help="動作確認")
    parser.add_argument("--account", choices=["a", "b"], default="a", help="投稿先アカウント (default: a)")

    args = parser.parse_args()

    if args.file:
        title, body_html, body_md = parse_markdown_file(args.file)
    elif args.title and args.body:
        title = args.title
        body_md = args.body
        body_html = body_md
    else:
        parser.print_help()
        sys.exit(1)

    post_article(title, body_html, body_md, publish=args.publish, dry_run=args.dry_run, account=args.account)


if __name__ == "__main__":
    main()
