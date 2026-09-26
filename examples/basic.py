"""Basic structured fields, bound context, and exception logging."""

import slogger


def main() -> None:
    # Console-only configuration. Importing slogger itself configures nothing.
    slogger.configure(level=slogger.DEBUG, console_level=slogger.DEBUG)
    log = slogger.get_logger("example.basic")

    # Keyword arguments become queryable fields in JSON and key=value pairs
    # on the console.
    log.info("user signed in", user_id=42, plan="pro")

    # bind() returns a new logger; it does not mutate the original.
    request_log = log.bind(request_id="req-123", method="GET")
    request_log.info("request started", path="/account")
    request_log.info("request finished", path="/account", status_code=200)
    log.info("outside request")  # no request_id or method

    # exception() is ERROR plus the active traceback.
    try:
        int("not-a-number")
    except ValueError:
        request_log.exception("request failed", path="/account")


if __name__ == "__main__":
    main()
