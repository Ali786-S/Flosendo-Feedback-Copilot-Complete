import os
import time
import warnings
import mimetypes
from pathlib import Path

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()

_client = None
_client_error = None


def _get_client():
    """
    Lazily build a Gemini client. Returns None if no key is set
    or the SDK is missing, so callers can fall back to a mock.
    """
    global _client, _client_error
    if _client is not None:
        return _client
    if _client_error is not None:
        return None
    if not GEMINI_API_KEY:
        _client_error = "GEMINI_API_KEY not set"
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        _client = genai
        return _client  # 
    except Exception as e:
        _client_error = f"Gemini client init failed: {e}"
        print(f"[llm_client] {_client_error}")
        return None


def is_available() -> bool:
    return _get_client() is not None


# Supported MIME types for Gemini vision/document input
_SUPPORTED_MIME_PREFIXES = ("image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf")
# Files above this size always use the File API; below this use inline bytes
_INLINE_SIZE_LIMIT = 4 * 1024 * 1024  # 4 MB


def _is_supported(mime: str) -> bool:
    return any(mime == m or mime.startswith(m) for m in _SUPPORTED_MIME_PREFIXES)


def _upload_via_file_api(p: Path, mime: str) -> object | None:
    """Upload to Gemini File API and wait for ACTIVE state. Returns file object or None."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            import google.generativeai as genai
        uploaded = genai.upload_file(path=str(p), mime_type=mime)
        for _ in range(10):
            if uploaded.state.name == "ACTIVE":
                return uploaded
            time.sleep(1)
            uploaded = genai.get_file(uploaded.name)
        return uploaded  # return even if not ACTIVE — Gemini may still accept it
    except Exception as e:
        print(f"[llm_client] File API upload failed for {p.name}: {e}")
        return None


def build_file_parts(attachments: list) -> list:
    """
    Convert attachment dicts to Gemini-compatible parts.
    Supported types: image/jpeg, image/png, image/gif, image/webp, application/pdf.
    Routing: files > 4 MB → File API; files ≤ 4 MB → inline bytes.
    File API is used as fallback if inline fails. Unsupported types are skipped cleanly.
    Text-only calls pass no attachments so this function is never entered.
    """
    parts = []
    for att in attachments or []:
        path_str = att.get("path")
        if not path_str:
            continue
        p = Path(path_str)
        if not p.exists() or not p.is_file():
            continue
        mime = (att.get("content_type") or mimetypes.guess_type(str(p))[0] or "").lower()
        if not mime or not _is_supported(mime):
            print(f"[llm_client] skipping unsupported type: {mime} ({p.name})")
            continue

        file_size = p.stat().st_size
        use_file_api = file_size > _INLINE_SIZE_LIMIT

        if use_file_api:
            result = _upload_via_file_api(p, mime)
            if result is not None:
                parts.append(result)
                continue
            # File API failed — fall through to inline
            print(f"[llm_client] falling back to inline for {p.name}")

        # Inline path (small files, or File API fallback)
        try:
            parts.append({"mime_type": mime, "data": p.read_bytes()})
        except Exception as e:
            print(f"[llm_client] failed to attach {p.name}: {e}")

    return parts


def get_model_name() -> str:
    return GEMINI_MODEL