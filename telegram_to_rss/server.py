import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from quart import Quart, Response, jsonify, render_template, request
from tortoise.functions import Count
from telegram_to_rss.client import TelegramToRssClient
from telegram_to_rss.config import (
    api_hash,
    api_id,
    base_url,
    session_path,
    password,
    static_path,
    feed_size_limit,
    initial_feed_size,
    update_interval_seconds,
    db_path,
    loglevel,
    max_video_size,
    max_file_size,
)
from telegram_to_rss.qr_code import get_qr_code_image
from telegram_to_rss.db import init_feeds_db, close_feeds_db
from telegram_to_rss.generate_feed import update_feeds_cache
from telegram_to_rss.poll_telegram import (
    TelegramPoller,
    update_feeds_in_db,
    reset_feeds_in_db,
)
from telegram_to_rss.models import Feed
import logging

logging.basicConfig(
    level=loglevel,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

app = Quart(__name__, static_folder=static_path, static_url_path="/static")
client = TelegramToRssClient(
    session_path=session_path, api_id=api_id, api_hash=api_hash, password=password
)
telegram_poller = TelegramPoller(
    client=client,
    message_limit=feed_size_limit,
    new_feed_limit=initial_feed_size,
    static_path=static_path,
    max_video_size=max_video_size,
    max_file_size=max_file_size,
)
rss_task: asyncio.Task | None = None

# Shown on the web page and in /status.json. Purely informational.
sync_state: dict = {
    "syncing": False,
    "last_success": None,
    "last_error": None,
}


async def start_rss_generation():
    global rss_task

    logging.info("start_rss_generation")

    async def update_rss():
        global rss_task

        should_reschedule = True
        try:
            sync_state["syncing"] = True
            logging.info("update_rss -> db")
            await update_feeds_in_db(telegram_poller=telegram_poller)

            logging.info("update_rss -> cache")
            await update_feeds_cache(feed_render_dir=static_path)

            sync_state.update(
                syncing=False,
                last_success=datetime.now(timezone.utc),
                last_error=None,
            )

            logging.info("update_rss -> sleep")
            await asyncio.sleep(update_interval_seconds)
        except asyncio.CancelledError:
            should_reschedule = False
        except Exception as e:
            sync_state.update(syncing=False, last_error=str(e) or type(e).__name__)
            logging.error(f"update_rss -> error: {e}")
            logging.warning("update_rss -> rebuilding feeds from scratch")
            await reset_feeds_in_db(telegram_poller=telegram_poller)
            raise e
        finally:
            if should_reschedule:
                logging.info("update_rss -> scheduling a new run")
                loop = asyncio.get_event_loop()
                rss_task = loop.create_task(update_rss())

    await client.start()

    loop = asyncio.get_event_loop()
    rss_task = loop.create_task(update_rss())

    logging.info("start_rss_generation -> done")


@app.before_serving
async def startup():
    global rss_task

    logging.info("startup")

    await init_feeds_db(db_path=db_path)
    loop = asyncio.get_event_loop()
    rss_task = loop.create_task(start_rss_generation())

    logging.info("startup -> done")


@app.after_serving
async def cleanup():
    logging.info("cleanup")

    if rss_task is not None:
        rss_task.cancel()
    await client.stop()
    await close_feeds_db()

    logging.info("cleanup -> done")


def public_base_url() -> str:
    """Where readers reach this app: BASE_URL if set, else the request's host."""
    return base_url or request.host_url.rstrip("/")


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@app.route("/")
async def root():
    logging.debug("GET /root %s", bool(client.qr_code_url))

    if client.qr_code_url is not None:
        qr_code_image = get_qr_code_image(client.qr_code_url)
        return await render_template("qr_code.html", qr_code=qr_code_image)

    feeds = await Feed.annotate(entry_count=Count("entries")).order_by("name")
    logging.debug("GET /root -> feeds %s", len(feeds))

    return await render_template(
        "feeds.html",
        user=client.user,
        feeds=feeds,
        sync=sync_state,
        public_url=public_base_url(),
    )


@app.route("/status.json")
async def status():
    """Login and sync state. Handy for the web page and for health checks."""
    qr_code_url = client.qr_code_url
    return jsonify(
        logged_in=client.user is not None and qr_code_url is None,
        qr=get_qr_code_image(qr_code_url) if qr_code_url else None,
        syncing=sync_state["syncing"],
        last_success=iso(sync_state["last_success"]),
        last_error=sync_state["last_error"],
        feeds=await Feed.all().count(),
    )


@app.route("/feeds.opml")
async def opml():
    """All feeds as one OPML file, to import into a feed reader in one go."""
    root_url = public_base_url()
    feeds = await Feed.all().order_by("name")

    opml_el = ET.Element("opml", {"version": "2.0"})
    head_el = ET.SubElement(opml_el, "head")
    ET.SubElement(head_el, "title").text = "Telegram to RSS"
    body_el = ET.SubElement(opml_el, "body")
    for feed in feeds:
        ET.SubElement(
            body_el,
            "outline",
            {
                "type": "rss",
                "text": feed.name,
                "title": feed.name,
                "xmlUrl": "{}/static/{}.xml".format(root_url, feed.id),
            },
        )

    return Response(
        ET.tostring(opml_el, encoding="utf-8", xml_declaration=True),
        mimetype="text/x-opml+xml",
        headers={"Content-Disposition": 'attachment; filename="telegram-feeds.opml"'},
    )
