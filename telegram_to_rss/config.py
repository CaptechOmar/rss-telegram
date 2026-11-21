import os
from pathlib import Path
from platformdirs import user_data_dir

api_id = int(os.environ.get("TG_API_ID"))
api_hash = os.environ.get("TG_API_HASH")
password = os.environ.get("TG_PASSWORD")

update_interval_seconds = int(os.environ.get("UPDATE_INTERVAL") or 3600)
feed_size_limit = int(os.environ.get("FEED_SIZE") or 200)
initial_feed_size = int(os.environ.get("INITIAL_FEED_SIZE") or 50)


def normalize_base_url(value: str | None) -> str:
    """Make BASE_URL absolute, so media links work in feed readers.

    "example.com" -> "https://example.com"
    "192.168.1.5:3042" / "localhost:3042" -> "http://..." (no TLS on a LAN)
    "https://example.com/" -> "https://example.com"
    """
    value = (value or "").strip().rstrip("/")
    if not value or "://" in value:
        return value
    host = value.split("/")[0].rsplit(":", 1)[0]
    is_local = (
        ":" in value.split("/")[0]
        or host == "localhost"
        or host.replace(".", "").isdigit()
    )
    return ("http://" if is_local else "https://") + value


base_url = normalize_base_url(os.environ.get("BASE_URL"))
bind = os.environ.get("BIND") or "127.0.0.1:3042"
max_video_size_mb = int(os.environ.get("MAX_VIDEO_SIZE_MB", 10))
max_video_size = max_video_size_mb * 1024 * 1024
# Audio, voice messages and other files. 0 turns file downloads off.
max_file_size_mb = int(os.environ.get("MAX_FILE_SIZE_MB", 10))
max_file_size = max_file_size_mb * 1024 * 1024

loglevel = os.environ.get("LOGLEVEL", "INFO").upper()

data_dir = (
    Path(os.environ.get("DATA_DIR"))
    if os.environ.get("DATA_DIR")
    else Path(user_data_dir()).joinpath("telegram_to_rss")
)
session_path = data_dir.joinpath("telegram_to-rss.session")
static_path = data_dir.joinpath("static")
db_path = data_dir.joinpath("feeds.db")

data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
static_path.mkdir(mode=0o700, exist_ok=True)
