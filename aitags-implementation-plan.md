# AI-Generation Metadata Extraction — Detailed Implementation Plan

Companion to `aitags-plan.md`. This document breaks the work into
self-contained tasks an agent can pick up and verify. Each task lists scope,
files touched, dependencies, and **acceptance criteria** (verifiable).

## Resolved decisions (from clarifying round)

- **Layout**: flat at repo root. `main.py` stays where it is; new code goes
  into `worker/`, `routes/`, `models/`, plus `worker.py`, `db.py`, `config.py`
  at root. No `/app/` migration.
- **Image scope**: PNG only for v1. JPEG/non-PNG images still get an `items`
  row but no `generation_meta` row, `source='none'`.
- **Hash column**: dropped. Change detection uses `(size, mtime)` only.
- **Tag normalization**: strip A1111 weighting syntax `(...:1.3)`, strip
  `<lora:name:0.8>` weight, lowercase, trim, dedupe. Original prompt text
  preserved verbatim in `generation_meta.prompt`.
- **Search backend**: SQLite FTS5 virtual table on `generation_meta.prompt`
  + `negative_prompt`, kept in sync via triggers.
- **Worker**: plain `while True: work; sleep` loop, run via systemd unit
  (`peakpics-worker.service`). No new dep for scheduling.
- **Real-time detection**: `watchdog` (inotify) on top of periodic poll.
- **DB file**: `data/peakpics.db` (gitignored). Path configurable via
  `DB_PATH` env, default `./data/peakpics.db`.
- **API prefix**: all new routes under `/api/*` (matches existing routes).

---

## Target repo structure (final state)

```
/
  main.py                    # existing FastAPI app; only add router include
  worker.py                  # NEW: worker entrypoint (loop + watchdog)
  db.py                      # NEW: shared DB connection + init/migrate
  config.py                  # NEW: paths, intervals, env loading
  requirements.txt           # +Pillow +watchdog
  routes/
    __init__.py
    metadata.py              # NEW: /api/items /api/search /api/tags /api/models
  worker/
    __init__.py
    scanner.py               # full walk + (size,mtime) diff + watchdog handler
    parsers/
      __init__.py            # dispatch by sniff
      base.py                # Parser interface + normalized dict dataclass
      a1111.py
      comfyui.py
      novelai.py
      fooocus.py
    pipeline.py              # pending → processing → done lifecycle + tag extract
  models/
    schema.sql               # tables + FTS5 + triggers
  data/
    peakpics.db              # gitignored
  peakpics-worker.service    # systemd unit template
```

---

## Schema (final)

```sql
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  size INTEGER,
  mtime REAL,
  source TEXT,                       -- 'a1111'|'comfyui'|'novelai'|'fooocus'|'none'
  status TEXT DEFAULT 'pending',    -- pending|processing|done|error
  last_scanned REAL,
  created_at REAL
);

CREATE TABLE IF NOT EXISTS generation_meta (
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
  raw_json TEXT
);

CREATE TABLE IF NOT EXISTS item_tags (
  item_id INTEGER REFERENCES items(id) ON DELETE CASCADE,
  tag TEXT,
  tag_type TEXT,            -- 'prompt'|'model'|'lora'|'sampler'
  PRIMARY KEY (item_id, tag, tag_type)
);

-- FTS5 mirror for prompt + negative_prompt search
CREATE VIRTUAL TABLE IF NOT EXISTS generation_meta_fts USING fts5(
  item_id UNINDEXED, prompt, negative_prompt, content=''
);

-- keep FTS in sync on insert/update/delete of generation_meta
CREATE TRIGGER IF NOT EXISTS gen_meta_ai AFTER INSERT ON generation_meta BEGIN
  INSERT INTO generation_meta_fts(item_id, prompt, negative_prompt)
  VALUES (new.item_id, new.prompt, new.negative_prompt);
END;
CREATE TRIGGER IF NOT EXISTS gen_meta_ad AFTER DELETE ON generation_meta BEGIN
  DELETE FROM generation_meta_fts WHERE item_id = old.item_id;
END;
CREATE TRIGGER IF NOT EXISTS gen_meta_au AFTER UPDATE ON generation_meta BEGIN
  DELETE FROM generation_meta_fts WHERE item_id = old.item_id;
  INSERT INTO generation_meta_fts(item_id, prompt, negative_prompt)
  VALUES (new.item_id, new.prompt, new.negative_prompt);
END;
```

---

## Parser interface (contract for all parsers)

```python
# worker/parsers/base.py
from dataclasses import dataclass, field

@dataclass
class ParsedMeta:
    prompt: str = ""
    negative_prompt: str = ""
    model: str = ""
    sampler: str = ""
    steps: int | None = None
    cfg_scale: float | None = None
    seed: str = ""
    width: int | None = None
    height: int | None = None
    loras: list[str] = field(default_factory=list)
    raw_json: str = ""   # full parsed structure as JSON string

class BaseParser:
    name: str                       # 'a1111', 'comfyui', ...
    @classmethod
    def sniff(cls, info: dict) -> bool: ...      # cheap: chunk-key check only
    @classmethod
    def parse(cls, info: dict) -> ParsedMeta: ...  # full parse
```

Sniff order matters: ComfyUI before A1111 (ComfyUI files can carry both
`workflow` and `parameters`-style chunks in rare cases; prefer the
structured one).

---

## Tasks

Each task is independently assignable. Verify with the listed check before
marking done.

### Task 1 — Config + DB layer
**Scope**: shared config loading + SQLite connection + schema bootstrap.
**Files**: `config.py`, `db.py`, `models/schema.sql`, `data/.gitkeep`,
update `.gitignore` (add `data/*.db`).
**Depends on**: nothing.
**Acceptance**:
- `python -c "import db; db.init_db()"` creates `data/peakpics.db` with all
  tables + triggers (verify via `sqlite3 data/peakpics.db ".schema"`).
- `config.py` reads `IMAGE_ROOT`, `DB_PATH`, `SCAN_INTERVAL_SEC`,
  `SUPPORTED_SOURCES` from env with documented defaults.
- `db.py` exposes `get_conn()` returning a `sqlite3.Connection` with
  `row_factory=sqlite3.Row` and `PRAGMA foreign_keys=ON` set.
- Re-running `init_db()` is idempotent (uses `CREATE IF NOT EXISTS`).

### Task 2 — Scanner (full walk + diff)
**Scope**: walk `IMAGE_ROOT`, diff `(size, mtime)` against `items` table.
**Files**: `worker/__init__.py`, `worker/scanner.py`.
**Depends on**: Task 1.
**Acceptance**:
- `scan_full()` inserts new files as `status='pending'`, updates changed
  files (reset to `pending`, delete their `generation_meta`/`item_tags` via
  cascade), deletes missing rows.
- Returns a stats dict `{"new": N, "changed": N, "missing": N}`.
- Walks recursively, ignores permission errors, only picks up
  `.png` (v1 scope; later extend `SUPPORTED_EXTS`).
- Test: drop a PNG into `IMAGE_ROOT`, run `scan_full()`, confirm row appears
  with `status='pending'` and `source IS NULL` (sniff happens in pipeline).

### Task 3 — Parser base + A1111 parser
**Scope**: parser interface + the most common format.
**Files**: `worker/parsers/__init__.py`, `worker/parsers/base.py`,
`worker/parsers/a1111.py`.
**Depends on**: Task 1 (for `ParsedMeta` only — actually self-contained).
**Acceptance**:
- `A1111.sniff({'parameters': '...'})` returns True iff `parameters` key
  present and starts with non-empty text.
- `A1111.parse(...)` correctly splits a real A1111 parameters string into
  prompt / negative prompt / steps / sampler / cfg / seed / size / model /
  loras (parse `<lora:name:weight>` occurrences from prompt).
- Tested against at least one real A1111 PNG: read it via
  `Image.open(path).info` and run through the parser; output matches the
  visible metadata in the file.
- Tag-tokenization helper lives here (or in `pipeline.py`) — strips
  `(token:1.3)` → `token`, strips `<lora:...>` (lora handled separately),
  lowercases, trims whitespace, dedupes preserving order.

### Task 4 — Worker pipeline (queue + A1111 end-to-end)
**Scope**: pending → processing → done lifecycle, tag extraction, first
end-to-end run.
**Files**: `worker/pipeline.py`, `worker.py`.
**Depends on**: Tasks 2, 3.
**Acceptance**:
- `process_pending(batch=10)` pulls N oldest `pending` items, marks them
  `processing`, sniffs source (try parsers in dispatch order: comfyui,
  a1111, novelai, fooocus — only a1111 implemented yet, others
  registered as no-ops or skipped), parses, writes `generation_meta` +
  `item_tags`, marks `done`.
- On parse error: status=`error`, log, do NOT crash loop.
- Items with no matching parser → `source='none'`, status=`done` (skip
  `generation_meta` row entirely).
- `worker.py`: runs `scan_full()` once on startup, then loops
  `process_pending()` + sleep `SCAN_INTERVAL_SEC`. CLI flag `--oneshot`
  for testing.
- End-to-end test: place 2 real A1111 PNGs in `IMAGE_ROOT`, run
  `python worker.py --oneshot`, verify `items.status='done'`,
  `generation_meta` populated, `item_tags` populated.

### Task 5 — ComfyUI parser
**Scope**: parse ComfyUI `workflow`/`prompt` JSON graph.
**Files**: `worker/parsers/comfyui.py`, register in dispatch.
**Depends on**: Task 4 (pipeline + base).
**Acceptance**:
- `ComfyUI.sniff({'workflow': '...'})` or sniff on `prompt` key returns True
  iff that key exists AND parses as JSON AND has top-level node-graph shape
  (object with numeric string keys → `class_type`).
- `parse()` walks the graph:
  - Find positive prompt node(s): `class_type` containing
    `CLIPTextEncode` with positive linkage; resolve nested `ConcatText`/
    wildcard nodes recursively (no fixed depth).
  - Find negative prompt similarly (the other CLIPTextEncode feeding
    `negative` sampler input).
  - Find `CheckpointLoaderSimple` → model name.
  - Find sampler node (`KSampler`/`KSamplerAdvanced`) → seed, steps, cfg,
    sampler_name, denoise.
  - Find LoRA nodes (`LoraLoader`) → lora names list.
- Width/height from latent/EmptyLatentImage node if present.
- `raw_json` stores the original `prompt` chunk (more deterministic than
  `workflow`).
- Tested against at least one real ComfyUI PNG.

### Task 6 — NovelAI + Fooocus parsers
**Scope**: remaining two sources.
**Files**: `worker/parsers/novelai.py`, `worker/parsers/fooocus.py`,
register in dispatch.
**Depends on**: Task 5.
**Acceptance**:
- NovelAI: sniff on `Comment` key being JSON with `steps`/`sampler`
  fields, or `Description` matching NovelAI prompt format. Parse prompt,
  steps, sampler, seed, cfg, size, model from the `Comment` JSON.
- Fooocus: sniff on `parameters` key that parses as JSON (vs A1111's
  non-JSON string — sniff order: try JSON parse, fallback to A1111).
- Both tested against at least one real file each if available; if no
  sample file exists, document the expected chunk structure from the tool's
  source/docs and skip the live test with a `# TODO: verify with real file`
  marker.

### Task 7 — Tag extraction refinement + FTS5 verification
**Scope**: ensure tags are correct, FTS5 search works.
**Files**: minor tweaks to `worker/pipeline.py` if needed.
**Depends on**: Task 6.
**Acceptance**:
- After processing a library with mixed sources, `item_tags` has no
  duplicate `(item_id, tag, tag_type)` rows, all tags lowercase and
  weight-stripped.
- Manual SQL check: `INSERT INTO generation_meta ...` then
  `SELECT * FROM generation_meta_fts` shows the FTS mirror row.
- `DELETE FROM generation_meta WHERE item_id=X` cascades to FTS table
  (trigger fires) and to `item_tags` (FK cascade).

### Task 8 — watchdog real-time scanner
**Scope**: inotify-based incremental scan, replacing reliance on periodic poll.
**Files**: extend `worker/scanner.py` (watch handler), `worker.py` (start
observer in background thread).
**Depends on**: Task 4.
**Acceptance**:
- `watchdog.Observer` watches `IMAGE_ROOT` recursively; on create/modify
  events for `.png` files, calls a targeted `scan_path(path)` that inserts
  or updates a single `items` row as `pending`.
- Events debounced (a single save can fire many events) — at minimum coalesce
  within ~500ms.
- Periodic `scan_full()` still runs at `SCAN_INTERVAL_SEC` as a safety net
  (covers missed events / restart recovery).
- Test: drop a file in, watch worker logs show the event, file becomes
  `done` without waiting for the poll interval.

### Task 9 — API routes
**Scope**: expose parsed metadata to frontend via existing FastAPI app.
**Files**: `routes/__init__.py`, `routes/metadata.py`, edit `main.py`
(add `app.include_router(metadata.router, prefix="/api")`).
**Depends on**: Task 7 (data must be populated to test against).
**Acceptance**:
- `GET /api/items/{id}` → item row + `generation_meta` + tags list.
- `GET /api/search?q=...&limit=20&offset=0` → uses FTS5
  `MATCH` against `generation_meta_fts`, returns item IDs + path + matched
  prompt snippet. Empty `q` returns 400.
- `GET /api/tags/{tag}?type=prompt` → items with that tag.
- `GET /api/models` → `SELECT DISTINCT model FROM generation_meta` for
  filter dropdown.
- `GET /api/items?model=...&sampler=...&source=...&limit=...&offset=...`
  → structured filtering with all params optional.
- All routes use `Depends(auth)` (reuse existing auth from `main.py`).
- All routes return JSON; pagination via `limit`/`offset` with sane
  defaults and a max cap (e.g. `limit ≤ 100`).
- Verified with curl against a populated DB.

### Task 10 — systemd unit + docs
**Scope**: ship runnable config for the Pi.
**Files**: `peakpics-worker.service`, update `README.md`, update
`requirements.txt`, update `.env.example`.
**Depends on**: Task 8.
**Acceptance**:
- `requirements.txt` adds `Pillow>=11.0.0` and `watchdog>=6.0.0`.
- `peakpics-worker.service` runs `python worker.py` as a systemd service,
  `Restart=on-failure`, points `IMAGE_ROOT`/`DB_PATH` via
  `Environment=` or `EnvironmentFile=`.
- README documents: install deps, init DB, run worker, run API, systemd
  install steps (`systemctl enable --now peakpics-worker`).
- `.env.example` adds `DB_PATH=./data/peakpics.db`,
  `SCAN_INTERVAL_SEC=300`, `SUPPORTED_SOURCES=a1111,comfyui,novelai,fooocus`.
- Smoke test: `pip install -r requirements.txt && python -c "import PIL, watchdog"`.

---

## Out of scope (do not implement)

- ML inference, embeddings, CLIP, clustering.
- JPEG/EXIF metadata parsing (deferred to v2).
- Frontend changes (frontend is pure consumer).
- Multi-host / network DB — single Pi, local SQLite.
- Migrations framework — `CREATE IF NOT EXISTS` is enough for v1.

## Open risks to flag during implementation

- **ComfyUI graph diversity**: custom nodes can hide prompt text behind
  arbitrary node types. If recursion finds no recognizable prompt node, store
  `raw_json` only and `prompt=""` — do not guess.
- **A1111 variant formats**: some forks (Forge, SD.Next) embed slightly
  different parameter strings. If a real file fails to parse, log the raw
  string and skip — do not silently mangle.
- **Pi performance**: large libraries (10k+ files) — full re-scan should
  stream, not load all paths into memory. `os.scandir` over `os.walk`.
- **Concurrent worker + API writes**: SQLite handles it with WAL. Add
  `PRAGMA journal_mode=WAL` in `db.init_db()`.
