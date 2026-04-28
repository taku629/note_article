"""
note-automation 設定ファイル
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── 後方互換用（既存コードがそのまま動く）─────────────────────────
# Step 6 で NOTE_SESSION_A に完全移行したら削除する
NOTE_SESSION_COOKIE = os.getenv("NOTE_SESSION_COOKIE", "")
NOTE_URLNAME = "taku629"

# Anthropic API キー（.env から読み込む）
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# note.com API エンドポイント
API_BASE   = "https://note.com/api/v1"
API_CREATE = f"{API_BASE}/text_notes"
API_DRAFT  = f"{API_BASE}/text_notes/draft_save"

# 一括投稿のデフォルト設定
DEFAULT_INTERVAL = 30
MAX_RETRY        = 3
RETRY_WAIT       = 60

# ── 2アカウント対応 ────────────────────────────────────────────────

ACCOUNTS: dict[str, dict] = {
    "a": {
        "session_cookie": os.getenv("NOTE_SESSION_A", ""),
        "urlname":        os.getenv("NOTE_URLNAME_A", "taku629"),
        "drafts_file":    "drafts_a.json",
        "posted_file":    "posted_a.txt",
        "articles_dir":   "/home/tk250127/note-articles/output/a",
        "quality_keywords": ["大学生", "副業", "バイト", "奨学金", "就活", "インターン", "資産形成", "節約", "フリーランス", "スキルアップ", "お金の勉強"],
    },
    "b": {
        "session_cookie": os.getenv("NOTE_SESSION_B", ""),
        "urlname":        os.getenv("NOTE_URLNAME_B", ""),
        "drafts_file":    "drafts_b.json",
        "posted_file":    "posted_b.txt",
        "articles_dir":   "/home/tk250127/note-articles/output/b",
        "quality_keywords": ["AI", "自動化", "LLM", "効率化", "仕組み化", "副業", "ツール", "ChatGPT", "Claude", "Python"],
    },
}


def get_account(name: str) -> dict:
    """
    アカウント設定を返す。
    - name が "a" / "b" 以外 → ValueError
    - B の session_cookie が空のまま呼ばれた場合はここではエラーにしない。
      実際に投稿を試みるスクリプト側（post.py）で検出してエラーにする。
    """
    if name not in ACCOUNTS:
        raise ValueError(f"未知のアカウント名: '{name}'。'a' または 'b' を指定してください。")
    return ACCOUNTS[name]


# ── リクエストヘッダー（全アカウント共通）────────────────────────

def get_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://note.com/",
        "Origin": "https://note.com",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }


def get_session() -> "requests.Session":
    """後方互換用。NOTE_SESSION_COOKIE（= アカウントA）でセッションを作る。"""
    import requests as _requests
    session = _requests.Session()
    session.cookies.set("_note_session_v5", NOTE_SESSION_COOKIE, domain="note.com")
    return session


def get_session_for(account_name: str) -> "requests.Session":
    """指定アカウントのCookieでセッションを作る。Step 3 以降で使う。"""
    import requests as _requests
    acct = get_account(account_name)
    cookie = acct["session_cookie"]
    if not cookie:
        raise ValueError(f"アカウント '{account_name}' の NOTE_SESSION_{account_name.upper()} が .env に設定されていません。")
    session = _requests.Session()
    session.cookies.set("_note_session_v5", cookie, domain="note.com")
    return session
