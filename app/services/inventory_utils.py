from __future__ import annotations

from urllib.parse import urlparse


VIDEO_EXTENSIONS = {
    ".mkv",
    ".avi",
    ".mp4",
    ".mov",
    ".wmv",
    ".flv",
    ".m4v",
    ".ts",
    ".m2ts",
    ".webm",
}

AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".aac",
    ".m4a",
    ".ogg",
    ".opus",
    ".wav",
    ".alac",
    ".wma",
}


def classify_file_type(filename: str) -> str:
    lower = filename.lower()
    extension = f".{lower.rsplit('.', 1)[1]}" if "." in lower else ""
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    return "other"


def pick_file_type(file_types: set[str]) -> str:
    if "video" in file_types:
        return "video"
    if "audio" in file_types:
        return "audio"
    return "other"


def tracker_is_disabled(url: str, status: str) -> bool:
    normalized_status = status.strip().lower()
    normalized_url = url.strip().lower()
    if normalized_status in {"disabled", "0"}:
        return True
    compact_url = " ".join(normalized_url.split())
    return compact_url in {"** [dht]", "** [dht] **", "** [pex]", "** [pex] **", "** [lsd]", "** [lsd] **"}


def extract_tracker_name(url: str) -> str:
    normalized_url = url.strip()
    if not normalized_url or tracker_is_disabled(normalized_url, ""):
        return ""

    parsed = urlparse(normalized_url)
    host = (parsed.hostname or parsed.path.split("/", 1)[0] or "").strip(".").lower()
    if not host:
        return "unknown"

    parts = [part for part in host.split(".") if part]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[1] if parts[0] in {"tracker", "trackers", "open"} else parts[0]
    if len(parts) >= 3:
        return parts[-2]
    return "unknown"
