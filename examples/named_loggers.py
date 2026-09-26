"""Named logger hierarchy and per-subsystem levels."""

import slogger


def main() -> None:
    slogger.configure(level=slogger.INFO, console_level=slogger.DEBUG)

    app = slogger.get_logger("shop")
    api = slogger.get_logger("shop.api")
    database = slogger.get_logger("shop.database")

    # Names form a hierarchy. Children with no explicit level inherit from
    # their nearest named parent, then from the configured root.
    app.set_level(slogger.INFO)
    database.set_level(slogger.DEBUG)

    api.debug("hidden API detail")  # inherits INFO from "shop"
    api.info("request accepted", route="/orders")

    # Only the database subtree was opted into DEBUG.
    database.debug("query planned", table="orders", index="orders_pkey")
    slogger.get_logger("shop.database.pool").debug("connection checked out", size=5)

    # get_logger() is cached by name.
    assert database is slogger.get_logger("shop.database")


if __name__ == "__main__":
    main()
