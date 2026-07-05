# peakpicsbe — Python image folder server

Serves a local folder tree of images as a REST API. Designed to sit alongside
[PeakPictures]() — point `IMAGE_ROOT` at the same `downloads/` directory.

## Endpoints

All endpoints require `?api_key=` query param or `Authorization: Bearer <key>` header.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/collections` | List all folders (collections) with cover image + image count |
| `GET` | `/api/collections/<name>/images` | List all images in a collection |
| `GET` | `/api/images?path=...` | Serve a raw image file |
| `GET` | `/api/items` | Structured filter (model, sampler, source) with pagination |
| `GET` | `/api/items/<id>` | Full item metadata (generation_meta + tags) |
| `GET` | `/api/search?q=...` | FTS5 full-text search on prompt / negative_prompt |
| `GET` | `/api/tags/<tag>?type=` | Items matching a specific tag |
| `GET` | `/api/models` | Distinct list of models used |

## Run

```bash
pip install -r requirements.txt
python main.py         # FastAPI server
python worker.py       # background scan + parse worker
```

## systemd setup (worker)

```bash
sudo cp peakpics-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now peakpics-worker
sudo journalctl -u peakpics-worker -f
```

## Configuration (.env)

| Variable | Default | Description |
|---|---|---|
| `IMAGE_ROOT` | `./downloads` | Path to image library |
| `DB_PATH` | `./data/peakpics.db` | SQLite database path |
| `API_KEY` | (none) | API key for auth |
| `PORT` | `8000` | API server port |
| `SCAN_INTERVAL_SEC` | `300` | Fallback full-scan interval |
| `SUPPORTED_SOURCES` | `a1111,comfyui,novelai,fooocus` | Enabled parser plugins |

## Collection → Post Mapping

Each subfolder under `IMAGE_ROOT` maps to a "collection" (post).
The folder name is the post title.
Images inside are sorted alphabetically.
The first image is used as the cover/thumbnail.

## Supported Formats

- **A1111 / SD WebUI** — `parameters` tEXt chunk (semi-structured string)
- **ComfyUI** — `prompt` or `workflow` tEXt chunk (JSON node graph)
- **NovelAI** — `Comment` tEXt chunk (JSON)
- **Fooocus** — `parameters` tEXt chunk (JSON)
- **Non-AI images** — detected, no generation_meta row