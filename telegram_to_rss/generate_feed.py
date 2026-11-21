from datetime import timezone
from email.utils import format_datetime
from pathlib import Path
from quart import utils
from telegram_to_rss.models import Feed, FeedEntry
from tortoise.query_utils import Prefetch
from telegram_to_rss.config import base_url
from telegram_to_rss.poll_telegram import parse_feed_entry_id
from telegram_to_rss.render import clean_title, entry_title, render_entry  # noqa: F401
from telegram_to_rss.client import telethon_dialog_id_to_tg_id
import xml.etree.ElementTree as ET
import logging


def rfc822(date) -> str:
    """RSS 2.0 wants RFC 822 dates; ISO 8601 trips up several readers."""
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return format_datetime(date)


def generate_feed(feed_render_dir: Path, feed: Feed):
    logging.info("generate_feed %s %s", feed.name, feed.id)

    feed_url = "https://t.me/c/{}".format(telethon_dialog_id_to_tg_id(feed.id))

    rss_root_el = ET.Element("rss", {"version": "2.0"})

    rss_feed_el = ET.SubElement(rss_root_el, "channel")

    ET.SubElement(rss_feed_el, "title").text = feed.name
    ET.SubElement(rss_feed_el, "pubDate").text = rfc822(feed.last_update)
    ET.SubElement(rss_feed_el, "link").text = feed_url
    ET.SubElement(rss_feed_el, "description").text = feed.name

    for feed_entry in feed.entries:
        [feed_id, entry_id] = parse_feed_entry_id(feed_entry.id)
        feed_entry_url = "https://t.me/c/{}/{}".format(
            telethon_dialog_id_to_tg_id(feed_id), entry_id
        )

        def message_url(message_id: int, feed_id=feed_id) -> str:
            return "https://t.me/c/{}/{}".format(
                telethon_dialog_id_to_tg_id(feed_id), message_id
            )

        rss_item_el = ET.SubElement(rss_feed_el, "item")

        ET.SubElement(rss_item_el, "guid", {"isPermaLink": "true"}).text = feed_entry_url
        ET.SubElement(rss_item_el, "title").text = entry_title(feed_entry)
        ET.SubElement(rss_item_el, "description").text = render_entry(
            feed_entry, message_url=message_url, base_url=base_url
        )
        ET.SubElement(rss_item_el, "pubDate").text = rfc822(feed_entry.date)
        ET.SubElement(rss_item_el, "link").text = feed_entry_url

    final_feed_file = feed_render_dir.joinpath("{}.xml".format(feed.id))

    rss_xml_tree = ET.ElementTree(rss_root_el)
    rss_xml_tree.write(
        file_or_filename=final_feed_file, encoding="UTF-8", short_empty_elements=True
    )

    logging.info("generate_feed -> done %s %s", feed.name, feed.id)


async def update_feeds_cache(feed_render_dir: str):
    feeds = await Feed.all().prefetch_related(
        Prefetch("entries", queryset=FeedEntry.all().order_by("-date"))
    )

    for feed in feeds:
        await utils.run_sync(generate_feed)(feed_render_dir, feed)
