from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image

from db import get_conn
from worker.parsers import parse
from worker.parsers.base import tokenize_prompt
from config import PARSEABLE_EXTS


def process_file(path: str) -> None:
    p = Path(path)
    if p.suffix.lower() not in PARSEABLE_EXTS:
        with get_conn() as conn:
            conn.execute(
                "UPDATE items SET source='none', status='done', last_scanned=? WHERE path=?",
                (time.time(), path),
            )
        return

    try:
        img = Image.open(p)
        info = img.info
    except Exception as e:
        with get_conn() as conn:
            conn.execute(
                "UPDATE items SET status='error', last_scanned=? WHERE path=?",
                (time.time(), path),
            )
        return

    source_name, meta = parse(info)
    now = time.time()

    with get_conn() as conn:
        row = conn.execute("SELECT id FROM items WHERE path=?", (path,)).fetchone()
        if row is None:
            return
        item_id = row["id"]

        if meta is None:
            conn.execute(
                "UPDATE items SET source=?, status='done', last_scanned=? WHERE id=?",
                (source_name or "none", now, item_id),
            )
            return

        conn.execute(
            "UPDATE items SET source=?, status='done', last_scanned=? WHERE id=?",
            (source_name, now, item_id),
        )

        conn.execute(
            """INSERT OR REPLACE INTO generation_meta
               (item_id, prompt, negative_prompt, model, sampler, steps,
                cfg_scale, seed, width, height, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item_id,
                meta.prompt,
                meta.negative_prompt,
                meta.model,
                meta.sampler,
                meta.steps,
                meta.cfg_scale,
                meta.seed,
                meta.width,
                meta.height,
                meta.raw_json,
            ),
        )

        conn.execute("DELETE FROM item_tags WHERE item_id=?", (item_id,))

        tag_rows = []
        for tag in tokenize_prompt(meta.prompt):
            tag_rows.append((item_id, tag, "prompt"))
        if meta.model:
            tag_rows.append((item_id, meta.model.lower(), "model"))
        if meta.sampler:
            tag_rows.append((item_id, meta.sampler.lower(), "sampler"))
        for lora in meta.loras:
            tag_rows.append((item_id, lora.lower(), "lora"))

        if tag_rows:
            conn.executemany(
                "INSERT OR IGNORE INTO item_tags (item_id, tag, tag_type) VALUES (?, ?, ?)",
                tag_rows,
            )

        conn.commit()


def process_pending(batch: int = 10) -> int:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, path FROM items WHERE status='pending' ORDER BY id LIMIT ?",
            (batch,),
        ).fetchall()

        if not rows:
            return 0

        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE items SET status='processing' WHERE id IN ({placeholders})", ids
        )
        conn.commit()

    for r in rows:
        try:
            process_file(r["path"])
        except Exception as e:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE items SET status='error', last_scanned=? WHERE id=?",
                    (time.time(), r["id"]),
                )
                conn.commit()

    return len(rows)