import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from slogger import get_logger, run_in_executor, wrap_context


def test_wrap_context_copies_the_span_into_a_worker_thread(records):
    logger = get_logger("workers")

    def work():
        logger.info("from thread")

    with logger.span("job", req=1):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(work).result()
            pool.submit(wrap_context(work)).result()

    rows = [row for row in records if row["message"] == "from thread"]
    assert "span" not in rows[0]
    assert rows[1]["span"] == "job"
    assert rows[1]["req"] == 1
    assert rows[1]["span_id"]


def test_run_in_executor_keeps_the_span(records):
    logger = get_logger("workers")

    def work(value):
        logger.info("executor", value=value)

    async def main():
        loop = asyncio.get_running_loop()
        with logger.span("job", req=2):
            await run_in_executor(loop, None, work, "ok")

    asyncio.run(main())
    row = next(item for item in records if item["message"] == "executor")
    assert row["req"] == 2
    assert row["value"] == "ok"
    assert row["span"] == "job"


def test_one_wrapped_callable_can_run_concurrently(records):
    logger = get_logger("workers")
    barrier = threading.Barrier(2)

    def work(value):
        barrier.wait()
        logger.info("parallel", value=value)

    with logger.span("batch", req=3), ThreadPoolExecutor(max_workers=2) as pool:
        wrapped = wrap_context(work)
        futures = [pool.submit(wrapped, value) for value in (1, 2)]
        for future in futures:
            future.result()

    rows = [row for row in records if row["message"] == "parallel"]
    assert {row["value"] for row in rows} == {1, 2}
    assert all(row["span"] == "batch" and row["req"] == 3 for row in rows)
