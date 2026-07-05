from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from db import get_conn
from auth import auth

router = APIRouter(prefix="/api", tags=["metadata"])


@router.get("/items/{item_id}")
def get_item(item_id: int, _auth=Depends(auth)):
    with get_conn() as conn:
        item = conn.execute(
            "SELECT * FROM items WHERE id=?", (item_id,)
        ).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        meta = conn.execute(
            "SELECT * FROM generation_meta WHERE item_id=?", (item_id,)
        ).fetchone()

        tags = conn.execute(
            "SELECT tag, tag_type FROM item_tags WHERE item_id=? ORDER BY tag_type, tag",
            (item_id,),
        ).fetchall()

    result = dict(item)
    result["generation_meta"] = dict(meta) if meta else None
    result["tags"] = [dict(t) for t in tags]
    return result


@router.get("/search")
def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _auth=Depends(auth),
):
    with get_conn() as conn:
        # FTS5 query: escape special chars and use prefix matching
        fts_query = " OR ".join(f'"{w}"*' for w in q.split() if w)
        if not fts_query:
            raise HTTPException(status_code=400, detail="No valid search terms")

        rows = conn.execute(
            """SELECT fts.rowid, fts.item_id, gm.prompt, gm.negative_prompt, i.path, i.source
               FROM generation_meta_fts fts
               JOIN generation_meta gm ON fts.item_id = gm.item_id
               JOIN items i ON i.id = gm.item_id
               WHERE generation_meta_fts MATCH ?
               ORDER BY rank
               LIMIT ? OFFSET ?""",
            (fts_query, limit, offset),
        ).fetchall()

        count = conn.execute(
            """SELECT COUNT(*) as cnt FROM generation_meta_fts
               WHERE generation_meta_fts MATCH ?""",
            (fts_query,),
        ).fetchone()["cnt"]

    return {
        "query": q,
        "total": count,
        "offset": offset,
        "limit": limit,
        "results": [dict(r) for r in rows],
    }


@router.get("/tags/{tag}")
def get_tag(
    tag: str,
    tag_type: str | None = Query(None, alias="type"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _auth=Depends(auth),
):
    with get_conn() as conn:
        if tag_type:
            rows = conn.execute(
                """SELECT i.id, i.path, i.source, i.status
                   FROM item_tags t
                   JOIN items i ON i.id = t.item_id
                   WHERE t.tag = ? AND t.tag_type = ?
                   ORDER BY i.id
                   LIMIT ? OFFSET ?""",
                (tag.lower(), tag_type, limit, offset),
            ).fetchall()
            count = conn.execute(
                "SELECT COUNT(*) FROM item_tags WHERE tag=? AND tag_type=?",
                (tag.lower(), tag_type),
            ).fetchone()[0]
        else:
            rows = conn.execute(
                """SELECT DISTINCT i.id, i.path, i.source, i.status
                   FROM item_tags t
                   JOIN items i ON i.id = t.item_id
                   WHERE t.tag = ?
                   ORDER BY i.id
                   LIMIT ? OFFSET ?""",
                (tag.lower(), limit, offset),
            ).fetchall()
            count = conn.execute(
                "SELECT COUNT(DISTINCT item_id) FROM item_tags WHERE tag=?",
                (tag.lower(),),
            ).fetchone()[0]

    return {
        "tag": tag,
        "tag_type": tag_type,
        "total": count,
        "offset": offset,
        "limit": limit,
        "results": [dict(r) for r in rows],
    }


@router.get("/models")
def list_models(_auth=Depends(auth)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT model FROM generation_meta WHERE model IS NOT NULL AND model != '' ORDER BY model"
        ).fetchall()
    return {"models": [r["model"] for r in rows]}


@router.get("/items")
def list_items(
    model: str | None = Query(None),
    sampler: str | None = Query(None),
    source: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _auth=Depends(auth),
):
    conditions = []
    params = []
    if model:
        conditions.append("gm.model = ?")
        params.append(model)
    if sampler:
        conditions.append("gm.sampler = ?")
        params.append(sampler)
    if source:
        conditions.append("i.source = ?")
        params.append(source)

    where = " AND ".join(conditions) if conditions else "1"

    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT i.id, i.path, i.source, i.status,
                       gm.prompt, gm.model, gm.sampler, gm.seed, gm.steps, gm.cfg_scale,
                       gm.width, gm.height
                FROM items i
                LEFT JOIN generation_meta gm ON gm.item_id = i.id
                WHERE {where}
                ORDER BY i.id
                LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()

        count = conn.execute(
            f"""SELECT COUNT(*) FROM items i
                LEFT JOIN generation_meta gm ON gm.item_id = i.id
                WHERE {where}""",
            params,
        ).fetchone()[0]

    return {
        "total": count,
        "offset": offset,
        "limit": limit,
        "results": [dict(r) for r in rows],
    }