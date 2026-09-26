"""Nested spans, span events, and function instrumentation."""

import asyncio

import slogger

log = slogger.get_logger("example.checkout").bind(service="checkout")


@slogger.instrument(capture=["order_id"], logger=log)
def charge(order_id: str, amount: float) -> None:
    log.info("card charged", amount=amount, currency="USD")


@slogger.instrument(name="send-receipt", capture="order_id", logger=log)
async def send_receipt(order_id: str) -> None:
    await asyncio.sleep(0.01)
    log.info("receipt sent")


async def checkout() -> None:
    # A span adds IDs and context to every record inside it. It also emits
    # span.start and span.end records with duration and status.
    with log.span("checkout", cart_id="cart-7") as span:
        span.set(item_count=3)  # visible on later records and span.end

        # Child spans inherit context and trace_id, but get a new span_id and
        # parent_span_id.
        with log.span("inventory", warehouse="east"):
            log.info("stock reserved")

        charge("order-42", 19.99)
        await send_receipt("order-42")

    # asyncio tasks automatically copy the active context.
    with log.span("background", job_id="job-1"):
        await asyncio.create_task(send_receipt("order-42"))


def main() -> None:
    # DEBUG is required to see successful span.start/span.end events.
    slogger.configure(level=slogger.DEBUG, console_level=slogger.DEBUG)
    asyncio.run(checkout())


if __name__ == "__main__":
    main()
