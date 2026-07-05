# AI-Generation Metadata Extraction — Implementation Plan

## Goal
Extract the generation metadata that AI image tools (SD WebUI/A1111, ComfyUI,
NovelAI, Fooocus, etc.) embed directly inside PNG files, and store it
structured in the Pi's DB so it can be served to the frontend for filtering
and search. **No AI computation on the Pi** — this is pure metadata parsing,
same as `infinite-image-browsing`'s parser layer (not its optional
embedding/clustering feature, which we are NOT doing).

## Constraints
- Coupled with existing Pi BE repo. Two entrypoints, shared SQLite DB:
  - `app.py` (existing FastAPI server, unchanged responsibilities)
  - `worker.py` (new — scan + parse loop, run via systemd or cron, separate process)
- No ML models, no GPU, no embeddings. Just reading text/JSON chunks out of image files.
- SQLite is sufficient at personal-library scale.

## Dependencies (explicit — do not substitute or hand-roll)
- **Pillow (`PIL`)** — opens the image and exposes embedded PNG `tEXt`/`iTXt`/
  `zTXt` chunks via `img.info` (a plain dict). This is how we get metadata OUT
  of the file. Do not manually parse PNG chunk structure/CRCs — Pillow already
  handles that correctly.
  - `Image.open(path).info` → dict of whatever chunks exist, e.g.
    `{'parameters': '...'}` for A1111, `{'prompt': '...', 'workflow': '...'}`
    for ComfyUI.
- **stdlib `json`** — for parsing ComfyUI's `workflow`/`prompt` chunk contents
  (already JSON once extracted via Pillow) and for NovelAI/Fooocus JSON fields.
- **stdlib `re`** — for A1111's semi-structured `parameters` string (splitting
  prompt / negative prompt / the `Steps: X, Sampler: Y, ...` line).
- **`watchdog`** — inotify-based filesystem watching for real-time change
  detection (step 8 in build order below). Only new third-party dep beyond Pillow.
- **JPEG note**: if any images in scope are JPEG (not PNG), Pillow's `.info`
  PNG-chunk trick does NOT apply — JPEG metadata lives in EXIF/APP1 segments
  instead, read via `img.getexif()` (still Pillow) or `piexif` if raw APP1
  access is needed. Confirm before implementing whether this is in scope —
  it is NOT covered by the parsers below as currently planned (PNG only).

Nothing beyond Pillow + stdlib + watchdog should be needed for this feature.
If a parser module seems to need something else, stop and flag it rather than
adding a new dependency silently.

---

## 1. What metadata actually looks like (per tool)

Different generators embed data differently — the parser needs to be
plugin-based per source, same pattern IIB uses:

- **A1111 / SD WebUI**: PNG `tEXt` chunk named `parameters`, a semi-structured
  string: prompt, then `Negative prompt: ...`, then a line of
  `Steps: X, Sampler: Y, CFG scale: Z, Seed: N, Size: WxH, Model: ...`.
- **ComfyUI**: PNG `tEXt` chunk named `workflow` (and/or `prompt`) containing a
  full JSON node graph. Need to walk the graph to find positive/negative
  prompt text nodes, checkpoint loader node, sampler node params, etc.
  (Note: nested/wildcard text nodes can be multiple layers deep — walk
  recursively rather than assuming a fixed depth.)
- **NovelAI**: PNG metadata with its own JSON-ish fields (`Description`,
  `Comment` containing JSON with prompt/seed/etc).
- **Fooocus**: similar `parameters`-style embedded JSON.
- Plain photos / non-AI images: no relevant chunk — just store basic file info,
  no generation metadata rows.

Each of these becomes its own parser module implementing a common interface,
so adding a new tool later = adding one file, not touching the pipeline.

## 2. Repo structure additions

```
/app
  main.py                 # existing FastAPI app (unchanged)
  routes/
    metadata.py            # new: search, item metadata, tag endpoints
  worker/
    worker.py              # new: entrypoint, scan loop
    scanner.py              # filesystem scan + change detection
    parsers/
      __init__.py           # dispatch: sniff which tool generated the image
      a1111.py               # parse `parameters` tEXt chunk
      comfyui.py             # parse `workflow`/`prompt` JSON graph
      novelai.py             # parse NovelAI fields
      fooocus.py              # parse Fooocus fields
    db.py                    # shared DB access (used by both app + worker)
  models/
    schema.sql               # table definitions
  config.py                  # paths, scan interval, etc.
```

## 3. Database schema (SQLite)

```sql
-- tracked files
CREATE TABLE items (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  hash TEXT,
  size INTEGER,
  mtime REAL,
  source TEXT,              -- 'a1111' | 'comfyui' | 'novelai' | 'fooocus' | 'none'
  status TEXT DEFAULT 'pending',   -- pending | processing | done | error
  last_scanned REAL,
  created_at REAL
);

-- parsed generation metadata, one row per item
CREATE TABLE generation_meta (
  item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  prompt TEXT,
  negative_prompt TEXT,
  model TEXT,
  sampler TEXT,
  steps INTEGER,
  cfg_scale REAL,
  seed TEXT,
  width INTEGER,
  height INTEGER,
  raw_json TEXT             -- full parsed structure, for anything not modeled above
);

-- prompt/model/lora broken into searchable tags
CREATE TABLE item_tags (
  item_id INTEGER REFERENCES items(id) ON DELETE CASCADE,
  tag TEXT,
  tag_type TEXT,            -- 'prompt' | 'model' | 'lora' | 'sampler'
  PRIMARY KEY (item_id, tag, tag_type)
);
```

## 4. Worker (`worker.py`) — background process

### 4.1 Scan / change detection
- On startup: full walk of image root. Compare `(size, mtime)` against DB.
  - New file → insert row, `status='pending'`.
  - Changed file → update row, reset `status='pending'`, drop old `generation_meta`/`item_tags`.
  - Missing file → cascade-delete row.
- Ongoing: `watchdog` (inotify) for real-time detection, plus a periodic full
  re-scan as a fallback safety net (covers missed events after restarts etc).

### 4.2 Parse job
- Loop: pull N `pending` items, mark `processing`.
- Sniff which parser applies (check for known PNG chunk names/keys — cheap,
  no need to fully parse to determine this).
- Run the matching parser, get back a normalized dict: prompt, negative
  prompt, model, sampler, steps, cfg, seed, size, loras (list).
- Insert into `generation_meta`.
- Split prompt into comma-separated tokens → insert into `item_tags` as
  `tag_type='prompt'`. Same for model name and any LoRA names.
- Mark `status='done'` (or `'error'` + log, don't crash the loop on a bad file).
- This is all just string/JSON parsing — no model loading, so the loop can run
  fast and cheap even on constrained Pi CPU.

## 5. API routes (added to existing FastAPI app)

- `GET /items/{id}` → full item metadata (generation_meta + tags)
- `GET /search?q=...` → simple tag/text match against `item_tags` /
  `generation_meta.prompt` (SQL `LIKE` or FTS5 virtual table for better
  full-text search — SQLite FTS5 is built-in, no extra dependency)
- `GET /tags/{tag}` → items matching a specific tag
- `GET /models` → distinct list of models used, for a filter dropdown
- `GET /items?model=...&sampler=...` → structured filtering

Frontend stays a pure consumer — no parsing logic client-side, just query params.

## 6. Config (`config.py`)
- `IMAGE_ROOT` — path to Pi image library
- `SCAN_INTERVAL_SEC` — fallback full-scan interval
- `SUPPORTED_SOURCES` — list of enabled parser plugins (easy to add/remove)

## 7. Build order (for harness to work through)
1. `schema.sql` + DB init/migration helper (shared by app + worker).
2. `scanner.py` — full walk + hash/mtime diff, populate `items` table (no parsing yet).
3. `parsers/a1111.py` — via `Image.open(path).info['parameters']` (Pillow), then `re`-split the string into prompt / negative prompt / steps / sampler / cfg / seed / size (most common/simplest format). Test against real files.
4. `worker.py` — queue loop tying scanner + a1111 parser together, `pending → done` lifecycle.
5. `parsers/comfyui.py` — via `Image.open(path).info['prompt']`/`['workflow']` (Pillow) then `json.loads()` (stdlib), recursively resolve prompt/sampler nodes.
6. `parsers/novelai.py`, `parsers/fooocus.py` — add remaining sources as needed.
7. Tag extraction: split prompt/model/lora into `item_tags` rows.
8. Add `watchdog`-based real-time scanning on top of the periodic scan.
9. `routes/metadata.py` — `/search`, `/items/{id}`, `/tags/{tag}`, `/models` endpoints on existing FastAPI app. Consider SQLite FTS5 table for prompt search.
10. Wire worker as a systemd service (or cron-triggered script) separate from the API process.

## 8. Explicitly out of scope
- No embeddings, no CLIP, no clustering, no ML inference of any kind on the Pi.
- No moving any computation off-Pi — everything here is local file parsing only.
