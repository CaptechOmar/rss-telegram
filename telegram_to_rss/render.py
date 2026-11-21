"""Turn a stored FeedEntry into the title and HTML that feed readers show.

Pure functions, no database or network access. `entry` is anything with the
FeedEntry attributes (message, media, extra, has_unsupported_media).
"""

import html
import re
from os.path import splitext
from typing import Callable
from urllib.parse import quote

CLEAN_TITLE = re.compile("<.*?>")

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")
VIDEO_EXT = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}
AUDIO_EXT = (".mp3", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wav", ".flac")

# Placeholders stored in FeedEntry.media by older versions and for failures.
FAIL = "FAIL"
TOO_LARGE = "TOO_LARGE"


def clean_title(raw_html: str) -> str:
    text = re.sub(CLEAN_TITLE, "", raw_html or "").replace("\n", " ")
    return html.unescape(text).strip()


def human_size(size) -> str:
    if not size:
        return ""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def _e(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _safe_url(url) -> str | None:
    if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
        return url
    return None


def _media_kind(path: str, meta: dict) -> str:
    kind = meta.get("kind")
    if kind in ("sticker", "image"):
        ext = splitext(path)[1].lower()
        return "video" if ext in VIDEO_EXT else "image"
    if kind:
        return kind
    ext = splitext(path)[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    return "file"


def _render_media(path: str, meta: dict, base_url: str) -> str:
    url = "{}/static/{}".format(base_url, quote(path))
    kind = _media_kind(path, meta)

    if kind == "image":
        return '<p><img src="{}" alt="media"/></p>'.format(_e(url))

    if kind == "video":
        mime = VIDEO_EXT.get(splitext(path)[1].lower(), "video/mp4")
        return (
            '<p><video controls preload="none" style="max-width:100%;">'
            '<source src="{url}" type="{mime}">'
            "Your reader does not support the video tag.</video>"
            '<br /><a href="{url}">Download video</a></p>'
        ).format(url=_e(url), mime=mime)

    if kind in ("audio", "voice"):
        if kind == "voice":
            label = "🎙 Voice message"
        else:
            title = meta.get("title") or meta.get("name") or "Audio"
            performer = meta.get("performer")
            label = "🎵 {}".format(
                "{} — {}".format(performer, title) if performer else title
            )
        return (
            '<p>{label}<br /><audio controls preload="none" src="{url}"></audio>'
            '<br /><a href="{url}">Download</a></p>'
        ).format(label=_e(label), url=_e(url))

    name = meta.get("name") or path
    size = human_size(meta.get("size"))
    label = "{} ({})".format(name, size) if size else name
    return '<p>📎 <a href="{}">{}</a></p>'.format(_e(url), _e(label))


def _render_poll(poll: dict) -> str:
    flags = ["Quiz" if poll.get("quiz") else "Poll"]
    if poll.get("closed"):
        flags.append("closed")
    if poll.get("multiple"):
        flags.append("multiple answers")
    total = poll.get("total_voters")
    if total is not None:
        flags.append("{} vote{}".format(total, "" if total == 1 else "s"))

    items = ""
    for answer in poll.get("answers", []):
        line = _e(answer.get("text"))
        voters = answer.get("voters")
        if voters is not None:
            line += " — {}".format(voters)
            if total:
                line += " ({:.0f}%)".format(100 * voters / total)
        if answer.get("correct"):
            line += " ✓"
        items += "<li>{}</li>".format(line)

    return (
        "<div><p><strong>📊 {question}</strong><br /><small>{flags}</small></p>"
        "<ul>{items}</ul></div>"
    ).format(question=_e(poll.get("question")), flags=_e(" · ".join(flags)), items=items)


def _render_webpage(page: dict) -> str:
    parts = []
    if page.get("site_name"):
        parts.append("<small>{}</small>".format(_e(page["site_name"])))
    title = page.get("title")
    url = _safe_url(page.get("url"))
    if title:
        heading = _e(title)
        if url:
            heading = '<a href="{}">{}</a>'.format(_e(url), heading)
        parts.append("<strong>{}</strong>".format(heading))
    if page.get("description"):
        parts.append(_e(page["description"]))
    return "<blockquote>{}</blockquote>".format("<br />".join(parts))


def _render_geo(geo: dict) -> str:
    lat, lon = geo["lat"], geo["lon"]
    url = "https://www.openstreetmap.org/?mlat={}&mlon={}#map=16/{}/{}".format(
        lat, lon, lat, lon
    )
    if geo.get("title"):
        label = geo["title"] + (" — " + geo["address"] if geo.get("address") else "")
    elif geo.get("live"):
        label = "Live location"
    else:
        label = "Location ({:.5f}, {:.5f})".format(lat, lon)
    return '<p>📍 <a href="{}">{}</a></p>'.format(_e(url), _e(label))


def _render_contact(contact: dict) -> str:
    label = contact.get("name") or "Contact"
    if contact.get("phone"):
        label += " — " + contact["phone"]
    return "<p>👤 {}</p>".format(_e(label))


def render_entry(
    entry,
    message_url: Callable[[int], str],
    base_url: str = "",
) -> str:
    """Build the HTML body of one feed item."""
    extra = getattr(entry, "extra", None) or {}
    meta_by_file = extra.get("media_meta") or {}

    header = ""
    if "forwarded_from" in extra:
        source = extra["forwarded_from"]
        header += "<p><em>↪ Forwarded{}</em></p>".format(
            " from " + _e(source) if source else ""
        )
    if extra.get("reply_to"):
        header += '<p><em>↩ Reply to <a href="{}">post #{}</a></em></p>'.format(
            _e(message_url(extra["reply_to"])), extra["reply_to"]
        )

    body = (entry.message or "").replace("\n", "<br />")

    blocks = ""
    failed = too_large = False
    for path in entry.media or []:
        if path == FAIL:
            failed = True
        elif path == TOO_LARGE:
            too_large = True
        else:
            blocks += _render_media(path, meta_by_file.get(path, {}), base_url)

    if extra.get("sticker"):
        blocks += "<p><em>Sticker {}</em></p>".format(_e(extra["sticker"]))
    if extra.get("webpage"):
        blocks += _render_webpage(extra["webpage"])
    if extra.get("poll"):
        blocks += _render_poll(extra["poll"])
    if extra.get("geo"):
        blocks += _render_geo(extra["geo"])
    if extra.get("contact"):
        blocks += _render_contact(extra["contact"])
    if extra.get("dice"):
        blocks += "<p>{} {}</p>".format(
            _e(extra["dice"].get("emoji")), _e(extra["dice"].get("value"))
        )

    for skipped in extra.get("skipped_files") or []:
        size = human_size(skipped.get("size"))
        blocks += (
            "<p><em>📎 {name}{size} was not downloaded ({reason}). "
            "Open Telegram to get it.</em></p>"
        ).format(
            name=_e(skipped.get("name") or "File"),
            size=" ({})".format(size) if size else "",
            reason=_e(skipped.get("reason") or "skipped"),
        )

    notes = ""
    if extra.get("unsupported") or getattr(entry, "has_unsupported_media", False):
        notes += "<p><strong>This message has an attachment that can't be shown here. Open Telegram to view it.</strong></p>"
    if failed:
        notes += "<p><strong>Downloading some of the media for this message failed. Open Telegram to view it.</strong></p>"
    if too_large:
        notes += "<p><strong>The video is too large.</strong></p>"

    return header + body + blocks + notes


def entry_title(entry) -> str:
    """Title from the text, or a short description of the attachment."""
    text = clean_title(entry.message)[:100]
    if text:
        return text

    extra = getattr(entry, "extra", None) or {}
    meta_by_file = extra.get("media_meta") or {}

    if extra.get("poll"):
        return "📊 " + (extra["poll"].get("question") or "Poll")[:95]
    if extra.get("webpage"):
        page = extra["webpage"]
        return (page.get("title") or page.get("site_name") or "Link")[:100]
    if extra.get("geo"):
        return "📍 " + (extra["geo"].get("title") or "Location")[:95]
    if extra.get("contact"):
        return "👤 " + (extra["contact"].get("name") or "Contact")[:95]
    if extra.get("dice"):
        return "{} {}".format(extra["dice"].get("emoji") or "🎲", extra["dice"].get("value"))
    if extra.get("sticker"):
        return "Sticker " + extra["sticker"]

    for path in entry.media or []:
        if path in (FAIL, TOO_LARGE):
            continue
        meta = meta_by_file.get(path, {})
        kind = meta.get("kind") or _media_kind(path, meta)
        if kind == "voice":
            return "🎙 Voice message"
        if kind == "audio":
            return "🎵 " + (meta.get("title") or meta.get("name") or "Audio")[:95]
        if kind == "video":
            return "🎬 Video"
        if kind in ("image", "sticker"):
            return "📷 Photo"
        return "📎 " + (meta.get("name") or path)[:95]

    skipped = extra.get("skipped_files") or []
    if skipped:
        return "📎 " + (skipped[0].get("name") or "File")[:95]
    if TOO_LARGE in (entry.media or []):
        return "🎬 Video"
    return "Message"
