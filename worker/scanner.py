import os
import time
from pathlib import Path
from queue import Queue, Empty

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from db import get_conn
from config import IMAGE_ROOT, IMAGE_EXTS, PARSEABLE_EXTS



def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def is_parseable(path: Path) -> bool:
    return path.suffix.lower() in PARSEABLE_EXTS


def _walk(path: Path) -> list[tuple[Path, int, float]]:
    results = []
    try:
        with os.scandir(str(path)) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    results.extend(_walk(Path(entry.path)))
                elif entry.is_file(follow_symlinks=False) and is_image(Path(entry.name)):
                    st = entry.stat()
                    results.append((Path(entry.path), st.st_size, st.st_mtime))
    except PermissionError:
        pass
    return results


def _ensure_image_root():
    IMAGE_ROOT.mkdir(parents=True, exist_ok=True)


def _upsert_item(path_str: str, conn):
    p = Path(path_str)
    if not p.exists() or not p.is_file():
        return
    st = p.stat()
    size = st.st_size
    mtime = st.st_mtime
    now = time.time()

    row = conn.execute("SELECT id FROM items WHERE path=?", (path_str,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO items (path, size, mtime, status, last_scanned, created_at) "
            "VALUES (?, ?, ?, 'pending', ?, ?)",
            (path_str, size, mtime, now, now),
        )
    else:
        conn.execute(
            "UPDATE items SET size=?, mtime=?, status='pending', last_scanned=? WHERE id=?",
            (size, mtime, now, row["id"]),
        )


def scan_path(path_str: str):
    if not is_image(Path(path_str)):
        return
    with get_conn() as conn:
        _upsert_item(path_str, conn)
        conn.commit()


def scan_full() -> dict:
    _ensure_image_root()
    now = time.time()
    files = _walk(IMAGE_ROOT)
    file_map = {str(p): (size, mtime) for p, size, mtime in files}

    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id, path, size, mtime FROM items"
        ).fetchall()
        existing_map = {r["path"]: r for r in existing}
        seen = set()
        new = changed = missing = 0

        for path_str, (size, mtime) in file_map.items():
            seen.add(path_str)
            row = existing_map.get(path_str)
            if row is None:
                conn.execute(
                    "INSERT INTO items (path, size, mtime, status, last_scanned, created_at) "
                    "VALUES (?, ?, ?, 'pending', ?, ?)",
                    (path_str, size, mtime, now, now),
                )
                new += 1
            elif row["size"] != size or row["mtime"] != mtime:
                conn.execute(
                    "UPDATE items SET size=?, mtime=?, status='pending', last_scanned=? "
                    "WHERE id=?",
                    (size, mtime, now, row["id"]),
                )
                changed += 1
            else:
                conn.execute(
                    "UPDATE items SET last_scanned=? WHERE id=?",
                    (now, row["id"]),
                )

        for path_str, row in existing_map.items():
            if path_str not in seen:
                conn.execute("DELETE FROM items WHERE id=?", (row["id"],))
                missing += 1

        conn.commit()
        return {"new": new, "changed": changed, "missing": missing}
    finally:
        conn.close()


class WatchdogHandler(FileSystemEventHandler):
    def __init__(self, queue: Queue):
        super().__init__()
        self.queue = queue

    def dispatch(self, event):
        if event.is_directory:
            return
        path = event.src_path
        ext = Path(path).suffix.lower()
        if ext not in IMAGE_EXTS:
            return
        if event.event_type in ("created", "modified"):
            self.queue.put(path)


def start_watchdog(queue: Queue) -> Observer:
    _ensure_image_root()
    event_handler = WatchdogHandler(queue)
    observer = Observer()
    observer.schedule(event_handler, str(IMAGE_ROOT), recursive=True)
    observer.start()
    return observer


def drain_watchdog_queue(queue: Queue) -> list[str]:
    seen = set()
    paths = []
    while True:
        try:
            p = queue.get_nowait()
            if p not in seen:
                seen.add(p)
                paths.append(p)
        except Empty:
            break
    return paths