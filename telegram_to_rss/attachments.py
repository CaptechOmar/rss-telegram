"""Describe Telegram message attachments as plain, JSON-serialisable dicts.

Nothing in here touches the network or the disk, so it can be unit-tested with
hand-built Telethon objects. Downloading lives in poll_telegram.py and turning
the descriptions into HTML lives in render.py.

The result of `describe_media` is stored in `FeedEntry.extra`.
"""

from telethon import types
from telethon.utils import get_display_name

# Media types we can show in some form. Anything else is flagged as unsupported.
_HANDLED_MEDIA = (
    types.MessageMediaEmpty,
    types.MessageMediaPhoto,
    types.MessageMediaDocument,
    types.MessageMediaWebPage,
    types.MessageMediaPoll,
    types.MessageMediaGeo,
    types.MessageMediaGeoLive,
    types.MessageMediaVenue,
    types.MessageMediaContact,
    types.MessageMediaDice,
)


def _text(value) -> str:
    """Poll texts are plain strings in old API layers, TextWithEntities in new."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return getattr(value, "text", "") or ""


def _describe_poll(media: types.MessageMediaPoll) -> dict:
    poll = media.poll
    results = media.results

    votes: dict[bytes, int] = {}
    correct: set[bytes] = set()
    total = None
    if results is not None:
        total = getattr(results, "total_voters", None)
        for answer_votes in results.results or []:
            votes[answer_votes.option] = answer_votes.voters
            if getattr(answer_votes, "correct", False):
                correct.add(answer_votes.option)

    return {
        "question": _text(poll.question),
        "answers": [
            {
                "text": _text(answer.text),
                "voters": votes.get(answer.option),
                "correct": answer.option in correct,
            }
            for answer in poll.answers
        ],
        "closed": bool(poll.closed),
        "quiz": bool(poll.quiz),
        "multiple": bool(poll.multiple_choice),
        "total_voters": total,
    }


def _describe_webpage(webpage) -> dict | None:
    if not isinstance(webpage, types.WebPage):
        return None
    info = {
        "url": webpage.url,
        "site_name": webpage.site_name,
        "title": webpage.title,
        "description": webpage.description,
    }
    if not (info["title"] or info["description"] or info["site_name"]):
        return None
    return info


def _geo(geo) -> dict | None:
    lat = getattr(geo, "lat", None)
    lon = getattr(geo, "long", None)
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon}


def classify_document(document) -> dict:
    """Work out what kind of file a Telegram document is, without downloading.

    kind is one of: video, image, sticker, animated_sticker, voice, audio, file.
    """
    mime = getattr(document, "mime_type", None) or ""
    attrs = {type(a): a for a in getattr(document, "attributes", [])}

    filename = attrs.get(types.DocumentAttributeFilename)
    audio = attrs.get(types.DocumentAttributeAudio)
    sticker = attrs.get(types.DocumentAttributeSticker)
    video = attrs.get(types.DocumentAttributeVideo)

    if sticker is not None or mime == "application/x-tgsticker":
        # .tgs stickers are Lottie JSON, which no feed reader can show.
        kind = "animated_sticker" if mime == "application/x-tgsticker" else "sticker"
    elif mime.startswith("video/"):
        kind = "video"
    elif mime.startswith("image/"):
        kind = "image"
    elif audio is not None or mime.startswith("audio/"):
        kind = "voice" if getattr(audio, "voice", False) else "audio"
    else:
        kind = "file"

    info = {
        "kind": kind,
        "mime": mime,
        "size": getattr(document, "size", None),
        "name": filename.file_name if filename else None,
    }
    if sticker is not None:
        info["emoji"] = getattr(sticker, "alt", None)
    if audio is not None:
        info["title"] = getattr(audio, "title", None)
        info["performer"] = getattr(audio, "performer", None)
        info["duration"] = getattr(audio, "duration", None)
    if video is not None and getattr(video, "round_message", False):
        info["round"] = True
    return info


# Files a browser would run or render actively if served from our own origin.
_UNSAFE_EXTENSIONS = {
    ".html", ".htm", ".xhtml", ".xht", ".svg", ".xml", ".js", ".mjs", ".swf",
}
_UNSAFE_MIMES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
    "text/xml",
    "application/xml",
    "application/javascript",
    "text/javascript",
}


def is_unsafe_to_host(info: dict) -> bool:
    """True for files that must not be served from /static (script injection)."""
    name = (info.get("name") or "").lower()
    ext = name[name.rfind("."):] if "." in name else ""
    return ext in _UNSAFE_EXTENSIONS or (info.get("mime") or "").lower() in _UNSAFE_MIMES


def describe_media(message) -> dict:
    """Describe the non-file parts of a message's media (polls, places, ...)."""
    media = message.media
    extra: dict = {}

    if isinstance(media, types.MessageMediaPoll):
        extra["poll"] = _describe_poll(media)
    elif isinstance(media, types.MessageMediaWebPage):
        webpage = _describe_webpage(media.webpage)
        if webpage:
            extra["webpage"] = webpage
    elif isinstance(media, types.MessageMediaVenue):
        geo = _geo(media.geo)
        if geo:
            extra["geo"] = {
                **geo,
                "title": media.title,
                "address": media.address,
            }
    elif isinstance(media, (types.MessageMediaGeo, types.MessageMediaGeoLive)):
        geo = _geo(media.geo)
        if geo:
            extra["geo"] = {**geo, "live": isinstance(media, types.MessageMediaGeoLive)}
    elif isinstance(media, types.MessageMediaContact):
        extra["contact"] = {
            "name": " ".join(
                part for part in (media.first_name, media.last_name) if part
            ),
            "phone": media.phone_number,
        }
    elif isinstance(media, types.MessageMediaDice):
        extra["dice"] = {"emoji": media.emoticon, "value": media.value}
    elif media is not None and not isinstance(media, _HANDLED_MEDIA):
        extra["unsupported"] = True

    return extra


def describe_context(message) -> dict:
    """Forward and reply info for the top of an entry."""
    extra: dict = {}

    fwd = getattr(message, "fwd_from", None)
    if fwd is not None:
        name = getattr(fwd, "from_name", None)
        if not name:
            forward = getattr(message, "forward", None)
            # .chat / .sender only read what Telegram already sent: no network.
            entity = getattr(forward, "chat", None) or getattr(forward, "sender", None)
            if entity is not None:
                try:
                    name = get_display_name(entity)
                except Exception:
                    name = None
        extra["forwarded_from"] = name or ""

    reply_to = getattr(message, "reply_to", None)
    reply_id = getattr(reply_to, "reply_to_msg_id", None)
    if reply_id:
        topic_id = getattr(reply_to, "reply_to_top_id", None)
        # In forum groups every message "replies" to its topic; that isn't a reply.
        is_topic_root = getattr(reply_to, "forum_topic", False) and (
            topic_id is None or reply_id == topic_id
        )
        if not is_topic_root:
            extra["reply_to"] = reply_id

    return extra


def merge_extra(target: dict, new: dict) -> None:
    """Merge the description of an album member into the album's first message."""
    for key, value in new.items():
        if key in ("media_meta", "skipped_files"):
            continue
        target.setdefault(key, value)
