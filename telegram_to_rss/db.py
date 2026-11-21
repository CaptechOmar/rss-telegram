import logging

from tortoise import Tortoise


async def _add_missing_columns():
    """generate_schemas() never alters existing tables, so add new columns here.

    Keeps databases created by older versions working without a reset.
    """
    connection = Tortoise.get_connection("default")
    columns = await connection.execute_query_dict('PRAGMA table_info("feedentry")')
    names = {column["name"] for column in columns}

    if "extra" not in names:
        logging.info("db -> adding feedentry.extra column")
        await connection.execute_query(
            "ALTER TABLE \"feedentry\" ADD COLUMN \"extra\" JSON NOT NULL DEFAULT '{}'"
        )


async def init_feeds_db(db_path: str):
    await Tortoise.init(
        db_url="sqlite://{}".format(db_path),
        modules={"models": ["telegram_to_rss.models"]},
    )
    # Generate the schema
    await Tortoise.generate_schemas(safe=True)
    await _add_missing_columns()


async def close_feeds_db():
    await Tortoise.close_connections()
