"""Apply slogger formatting and span context to ordinary stdlib loggers."""

import logging

import slogger


def third_party_code() -> None:
    # Pretend this logger belongs to a dependency that knows nothing about
    # slogger. Its normal logging call still receives the active span fields.
    dependency_log = logging.getLogger("payment_provider.client")
    dependency_log.info("sending request", extra={"endpoint": "/charge"})


def main() -> None:
    # capture_stdlib=True is the default: handlers are installed on root.
    slogger.configure(
        level=slogger.DEBUG,
        console_level=slogger.DEBUG,
        capture_stdlib=True,
    )
    log = slogger.get_logger("example.integration")

    with log.span("payment", payment_id="pay-9"):
        log.info("payment started")
        third_party_code()

    # Set capture_stdlib=False if the application must leave root logging
    # untouched. Then only "slogger" and "slogger.*" names are captured.


if __name__ == "__main__":
    main()
