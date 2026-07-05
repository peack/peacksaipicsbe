"""peakpics-worker — background scan + parse loop."""
from __future__ import annotations

import argparse
import logging
import time
from queue import Queue

from config import SCAN_INTERVAL_SEC
from worker.scanner import scan_full, start_watchdog, drain_watchdog_queue, scan_path
from worker.pipeline import process_pending

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("worker")


def _process_loop(label: str = ""):
    processed = process_pending(batch=10)
    while processed > 0:
        tag = f" [{label}]" if label else ""
        log.info("parsed %d items%s", processed, tag)
        processed = process_pending(batch=10)
    return processed


def run_loop():
    log.info("starting worker loop (interval=%ds)", SCAN_INTERVAL_SEC)
    queue: Queue = Queue()
    observer = start_watchdog(queue)

    try:
        while True:
            scan_result = scan_full()
            log.info("scan: new=%d changed=%d missing=%d", scan_result["new"], scan_result["changed"], scan_result["missing"])
            _process_loop()

            log.info("sleep %ds...", SCAN_INTERVAL_SEC)

            for _ in range(SCAN_INTERVAL_SEC):
                time.sleep(1)
                paths = drain_watchdog_queue(queue)
                if paths:
                    for p in paths:
                        log.info("watchdog: %s", p)
                        scan_path(p)
                    _process_loop("watchdog")
    finally:
        observer.stop()
        observer.join()


def run_oneshot():
    scan_result = scan_full()
    log.info("scan: new=%d changed=%d missing=%d", scan_result["new"], scan_result["changed"], scan_result["missing"])

    processed = process_pending(batch=100)
    while processed > 0:
        log.info("parsed %d items", processed)
        processed = process_pending(batch=100)

    log.info("oneshot complete")


def main():
    parser = argparse.ArgumentParser(description="peakpics worker")
    parser.add_argument("--oneshot", action="store_true", help="run once and exit")
    args = parser.parse_args()

    from db import init_db
    init_db()

    if args.oneshot:
        run_oneshot()
    else:
        run_loop()


if __name__ == "__main__":
    main()