"""Propagate span context into worker threads."""

from concurrent.futures import ThreadPoolExecutor

import slogger

log = slogger.get_logger("example.worker")


def work(label: str) -> None:
    log.info("worker ran", label=label)


def main() -> None:
    slogger.configure(level=slogger.DEBUG, console_level=slogger.DEBUG)

    with log.span("batch", batch_id="batch-5"):
        with ThreadPoolExecutor(max_workers=2) as pool:
            # ThreadPoolExecutor does not copy contextvars. This record has no
            # span or batch_id.
            plain = pool.submit(work, "without context")

            # wrap_context captures the current span. The wrapped callable is
            # reusable and safe to submit concurrently.
            wrapped = slogger.wrap_context(work)
            copied = pool.submit(wrapped, "with context")

            plain.result()
            copied.result()


if __name__ == "__main__":
    main()
