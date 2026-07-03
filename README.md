# peakpicsbe — Python image folder server

Serves a local folder tree of images as a REST API. Designed to sit alongside
[PeakPictures]() — point `IMAGE_ROOT` at the same `downloads/` directory.

## Endpoints

All endpoints require `?api_key=` query param or `Authorization: Bearer <key>` header.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/collections` | List all folders (collections) with cover image + image count |
| `GET` | `/api/collections/<name>/images` | List all images in a collection |
| `GET` | `/api/images?path=...` | Serve a raw image file |
| `GET` | `/api/health` | Health check |

## Run

```bash
pip install -r requirements.txt
python main.py
```

## Collection → Post Mapping

Each subfolder under `IMAGE_ROOT` maps to a "collection" (post).
The folder name is the post title.
Images inside are sorted alphabetically.
The first image is used as the cover/thumbnail.