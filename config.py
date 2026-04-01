"""
note-automation 設定ファイル
"""
import os
from dotenv import load_dotenv

load_dotenv()

# note.com のセッションクッキー（.env から読み込む）
NOTE_SESSION_COOKIE = os.getenv("NOTE_SESSION_COOKIE", "")

# Anthropic API キー（.env から読み込む）
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# note.com API エンドポイント
API_BASE = "https://note.com/api/v1"
API_CREATE   = f"{API_BASE}/text_notes"
# draft_save の is_temp_saved=false が公開に相当する
API_DRAFT    = f"{API_BASE}/text_notes/draft_save"

# リクエストヘッダー（セッションクッキーを含む）
def get_headers() -> dict:
    return {
        "Content-Type": "application/json",
        # note.com API は X-Requested-With が必須（ないと422になる）
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
    """クッキーをセットした requests.Session を返す。"""
    import requests as _requests
    session = _requests.Session()
    session.cookies.set("_note_session_v5", NOTE_SESSION_COOKIE, domain="note.com")
    return session

# note.com ユーザー名（公開URL構築に使う）
NOTE_URLNAME = "taku629"

# 一括投稿のデフォルト設定
DEFAULT_INTERVAL = 30   # 投稿間隔（秒）
MAX_RETRY        = 3    # レートリミット時の最大リトライ回数
RETRY_WAIT       = 60   # レートリミット時の待機時間（秒）
