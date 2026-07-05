"""
peakpicsbe — lightweight image folder server.
Serves a local directory tree as REST API, with folder=collection mapping.
"""
from __future__ import annotations

import os
import mimetypes
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

ROOT = Path(os.getenv("IMAGE_ROOT", "./downloads")).resolve()
API_KEY = os.getenv("API_KEY", "")
PORT = int(os.getenv("PORT", "8000"))

app = FastAPI(title="peakpicsbe", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".svg"}


# ── Auth ────────────────────────────────────────────────────────────────

def auth(
    api_key: Optional[str] = Query(default=None),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    """Require API key via ?api_key= or Authorization: Bearer <key>."""
    if not API_KEY:
        return  # no key configured = open
    key = api_key or (creds.credentials if creds else None)
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ── Helpers ─────────────────────────────────────────────────────────────

def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def find_images(path: Path) -> list[Path]:
    """Recursively collect all images under a directory."""
    result: list[Path] = []
    try:
        for entry in path.iterdir():
            if entry.is_dir():
                result.extend(find_images(entry))
            elif is_image(entry):
                result.append(entry)
    except PermissionError:
        pass
    return sorted(result, key=lambda x: x.name)


# ── Routes ──────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "root": str(ROOT)}


@app.get("/api/collections")
def list_collections(_auth=Depends(auth)):
    """Return all subfolders as collections with cover image + count."""
    if not ROOT.exists() or not ROOT.is_dir():
        return JSONResponse({"collections": [], "root": str(ROOT), "exists": False})

    collections = []
    for entry in sorted(ROOT.iterdir()):
        if not entry.is_dir():
            continue
        images = find_images(entry)
        if not images:
            continue

        collections.append(
            {
                "name": entry.name,
                "path": str(entry.relative_to(ROOT)),
                "image_count": len(images),
                "cover": f"/api/images?path={images[0].relative_to(ROOT)}",
            }
        )

    return JSONResponse({"collections": collections, "root": str(ROOT), "count": len(collections)})


@app.get("/api/collections/{name}/images")
def list_collection_images(name: str, _auth=Depends(auth)):
    """List all images in a collection folder."""
    folder = (ROOT / name).resolve()
    if not str(folder).startswith(str(ROOT)):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=404, detail="Collection not found")

    images = find_images(folder)

    return JSONResponse(
        {
            "collection": name,
            "images": [
                {
                    "filename": img.name,
                    "url": f"/api/images?path={img.relative_to(ROOT)}",
                }
                for img in images
            ],
            "count": len(images),
        }
    )


@app.get("/api/images")
def serve_image(
    path: str = Query(..., description="Relative path from IMAGE_ROOT"),
    _auth=Depends(auth),
):
    """Serve a raw image file with correct content type."""
    full = (ROOT / path).resolve()
    if not str(full).startswith(str(ROOT)):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    if not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    content_type, _ = mimetypes.guess_type(str(full))
    return FileResponse(
        full,
        media_type=content_type or "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ── Main ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"peakpicsbe → {ROOT}")
    print(f"  http://localhost:{PORT}/api/health")
    print(f"  http://localhost:{PORT}/api/collections")
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)