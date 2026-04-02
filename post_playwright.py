"""
note.com Playwright 投稿スクリプト

ブラウザを操作して note に記事を投稿する。
非公式 API の代わりに実ブラウザ操作で確実に投稿できる。
"""

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from config import NOTE_SESSION_COOKIE


def post_to_note(title: str, body_md: str, publish: bool = False) -> str:
    """
    Playwright で note に記事を投稿する。
    戻り値: 投稿後のページURL
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # セッションクッキーをセット
        context.add_cookies([{
            "name": "_note_session_v5",
            "value": NOTE_SESSION_COOKIE,
            "domain": "note.com",
            "path": "/",
        }])

        page = context.new_page()

        # 新規記事作成ページを開く
        print("  → エディタを開いています...", end=" ", flush=True)
        page.goto("https://editor.note.com/")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        print("完了")

        # タイトル入力
        print("  → タイトルを入力中...", end=" ", flush=True)
        title_area = page.locator('[placeholder="タイトル"]').first
        title_area.click()
        title_area.fill(title)
        time.sleep(1)
        print("完了")

        # 本文エリアをクリック
        body_area = page.locator(".ProseMirror").first
        body_area.click()
        time.sleep(0.5)

        # Markdown を段落ごとに入力（見出し記号は除去）
        print("  → 本文を入力中...", end=" ", flush=True)
        lines = [l for l in body_md.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if line.startswith("### "):
                line = line[4:]
            elif line.startswith("## "):
                line = line[3:]
            elif line.startswith("# "):
                line = line[2:]
            # 水平線はスキップ
            elif line.strip() in ("---", "***", "___"):
                continue

            body_area.type(line, delay=10)
            if i < len(lines) - 1:
                page.keyboard.press("Enter")
            time.sleep(0.1)
        print("完了")

        time.sleep(2)

        # 下書き状態のスクリーンショットを保存
        page.screenshot(path="screenshot_draft.png")
        print("  → スクリーンショット保存: screenshot_draft.png")

        if publish:
            # 「公開」ボタンをクリック
            print("  → 公開ボタンをクリック中...", end=" ", flush=True)
            publish_btn = page.locator('button:has-text("公開")').first
            publish_btn.click()
            time.sleep(2)
            # 確認ダイアログの「公開する」ボタン
            confirm_btn = page.locator('button:has-text("公開する")').first
            confirm_btn.click()
            time.sleep(3)
            url = page.url
            print("完了")
            print(f"✓ 公開完了: {url}")
        else:
            url = page.url
            print(f"✓ 下書き保存完了: {url}")

        browser.close()
        return url
