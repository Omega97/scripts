"""Browser UI backend for TagStore.

Serves a small single-page app at ``/`` and a JSON API under ``/api`` that
operates on the local ``.tagstore.json`` and image files in the root directory.

Run with::

    pip install fastapi uvicorn
    python -m tagstore.web --root /path/to/images [--port 8000]

The server binds to ``127.0.0.1`` by default so it is only reachable from the
local machine.
"""

from __future__ import annotations

import os
import random
import subprocess
import threading
from urllib.parse import quote

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError as e:  # pragma: no cover - depends on optional deps
    raise ImportError(
        "tagstore web UI requires 'fastapi' and 'uvicorn'. "
        "Install them with: pip install fastapi uvicorn"
    ) from e

from .errors import NoMatchError, QuerySyntaxError
from .model import SYNONYMS_FILE, TagStore

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _media_type(path):
    return _MEDIA_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def _safe_resolve(root, rel):
    root = os.path.abspath(root)
    rel = (rel or "").replace("\\", "/")
    full = os.path.abspath(os.path.join(root, rel))
    try:
        if os.path.commonpath([root, full]) != root:
            return None
    except ValueError:
        return None
    if os.path.isfile(full):
        return full
    return _case_insensitive_resolve(root, rel)


def _case_insensitive_resolve(root, rel):
    """Locate a file whose on-disk casing differs from the index (Linux/cloud FS)."""
    current = root
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    for i, part in enumerate(parts):
        try:
            entries = os.listdir(current)
        except OSError:
            return None
        lowered = part.lower()
        match = next((e for e in entries if e.lower() == lowered), None)
        if match is None:
            return None
        current = os.path.join(current, match)
    return current if os.path.isfile(current) else None


def _preview_url(root, entry):
    """Return a preview URL for an entry, preferring a path that exists on disk."""
    for p in entry.get("paths") or []:
        if _safe_resolve(root, p) is not None:
            return "/api/file?path=" + quote(p)
    return None


def _reveal_in_explorer(path):
    """Reveal a file in the OS file manager, selecting it where supported."""
    path = os.path.abspath(path)
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", path])
    else:
        import webbrowser

        webbrowser.open(os.path.dirname(path))


def _open_in_editor(path):
    """Open a file in the OS default editor for its type."""
    path = os.path.abspath(path)
    if os.name == "nt":
        os.startfile(path)  # noqa: PTH102 - Windows-only, no stdlib equivalent
    else:
        import webbrowser

        webbrowser.open(path)


class ModifyBody(BaseModel):
    query: str
    tags: list[str] = []
    op: str = "add"  # add | remove | override


class SettingsBody(BaseModel):
    min_tag_matches: int


class AssetTagsBody(BaseModel):
    tags: list[str] = []
    op: str = "add"  # add | remove | override


class RenameBody(BaseModel):
    name: str


class BatchTagsBody(BaseModel):
    hashes: list[str]
    tags: list[str] = []
    op: str = "add"  # add | remove | override


class HashesBody(BaseModel):
    hashes: list[str]


def _sort_key(sort):
    if sort == "date":
        return lambda e: e["date"]
    if sort == "name":
        return lambda e: (e["name"].lower(), e["primary_path"].lower())
    return lambda e: e["primary_path"].lower()


class ScanJob:
    """Runs at most one scan in a background thread, reporting progress/cancel."""

    def __init__(self, store):
        self.store = store
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._state = {"running": False, "done": 0, "total": 0, "summary": None}
        self._recompute = False

    def is_running(self):
        with self._lock:
            return self._state["running"]

    def state(self):
        with self._lock:
            return dict(self._state)

    def start(self, recompute_tags=False):
        with self._lock:
            if self._state["running"]:
                return False
            self._cancel.clear()
            self._recompute = recompute_tags
            self._state = {"running": True, "done": 0, "total": 0, "summary": None}
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def cancel(self):
        self._cancel.set()
        return self.state()

    def _run(self):
        def cb(done, total):
            with self._lock:
                self._state["done"] = done
                self._state["total"] = total

        try:
            summary = self.store.scan(
                progress_cb=cb, cancel=self._cancel, recompute_tags=self._recompute
            )
        except Exception as e:  # noqa: BLE001 - surface any failure to the UI
            with self._lock:
                self._state["running"] = False
                self._state["summary"] = {"error": str(e)}
            return

        with self._lock:
            self._state["running"] = False
            self._state["summary"] = summary


def create_app(root_dir="."):
    store = TagStore(root_dir)
    job = ScanJob(store)
    lock = threading.Lock()

    app = FastAPI(title="TagStore")

    @app.get("/api/tags")
    def list_tags():
        with lock:
            records = store.list_tags()
        return {"tags": records}

    @app.get("/api/search")
    def search(q: str = "", sort: str = "path", order: str = "asc", page: int = 1, page_size: int = 28, focus: str = "", seed: str = ""):
        q = (q or "").strip()
        with lock:
            if q:
                try:
                    details = store.query_details(q)
                except QuerySyntaxError:
                    raise HTTPException(status_code=400, detail="invalid query")
            else:
                details = {"results": list(store.data["hashes"].items()), "keywords": []}
            results = details["results"]
            keywords = details["keywords"]
            entries = store.result_entries(results)

        if sort == "random":
            rng = random.Random(seed)
            rng.shuffle(entries)
            if order == "desc":
                entries.reverse()
        else:
            entries.sort(key=_sort_key(sort), reverse=(order == "desc"))

        total = len(entries)
        page_size = max(1, page_size)
        pages = (total + page_size - 1) // page_size

        focus_found = False
        if focus:
            for i, entry in enumerate(entries):
                if entry.get("hash") == focus:
                    page = (i // page_size) + 1
                    focus_found = True
                    break

        page = max(1, min(page, pages)) if pages else 1
        start = (page - 1) * page_size
        page_entries = entries[start:start + page_size]
        for entry in page_entries:
            entry["preview_url"] = _preview_url(store.root_dir, entry)
        return {
            "results": page_entries,
            "keywords": keywords,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "focus_found": focus_found,
            "hashes": [e["hash"] for e in entries],
        }

    @app.get("/api/settings")
    def get_settings():
        return {"min_tag_matches": store._min_visible_count()}

    @app.post("/api/settings")
    def update_settings(body: SettingsBody):
        with lock:
            try:
                value = max(1, int(body.min_tag_matches))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="invalid min_tag_matches")
            store.data.setdefault("settings", {})["min_tag_count_for_search"] = value
            store._prune_spurious_tags()
            store.save()
        return {"min_tag_matches": store._min_visible_count()}

    @app.post("/api/tags")
    def modify_tags(body: ModifyBody):
        with lock:
            try:
                if body.op == "add":
                    n = store.modify_tags(body.query, tags_to_add=body.tags)
                elif body.op == "remove":
                    n = store.modify_tags(body.query, tags_to_remove=body.tags)
                elif body.op == "override":
                    n = store.modify_tags(body.query, tags_to_add=body.tags, override=True)
                else:
                    raise HTTPException(status_code=400, detail="unknown op")
            except NoMatchError:
                raise HTTPException(status_code=404, detail="no assets matched")
            except QuerySyntaxError:
                raise HTTPException(status_code=400, detail="invalid query")
        return {"changed": n}

    @app.post("/api/assets/{file_hash}/tags")
    def modify_asset_tags(file_hash: str, body: AssetTagsBody):
        with lock:
            try:
                if body.op == "add":
                    n = store.modify_asset_tags(file_hash, tags_to_add=body.tags)
                elif body.op == "remove":
                    n = store.modify_asset_tags(file_hash, tags_to_remove=body.tags)
                elif body.op == "override":
                    n = store.modify_asset_tags(file_hash, tags_to_add=body.tags, override=True)
                else:
                    raise HTTPException(status_code=400, detail="unknown op")
            except NoMatchError:
                raise HTTPException(status_code=404, detail="asset not found")
        return {"changed": n}

    @app.post("/api/assets/{file_hash}/rename")
    def rename_asset(file_hash: str, body: RenameBody):
        with lock:
            try:
                entry = store.rename_asset(file_hash, body.name)
            except NoMatchError:
                raise HTTPException(status_code=404, detail="asset not found")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except OSError as e:
                raise HTTPException(status_code=400, detail=str(e))
        return store.result_entries([(file_hash, entry)])[0]

    @app.post("/api/assets/tags")
    def modify_assets_tags(body: BatchTagsBody):
        with lock:
            try:
                if body.op == "add":
                    n = store.modify_assets_tags(body.hashes, tags_to_add=body.tags)
                elif body.op == "remove":
                    n = store.modify_assets_tags(body.hashes, tags_to_remove=body.tags)
                elif body.op == "override":
                    n = store.modify_assets_tags(body.hashes, tags_to_add=body.tags, override=True)
                else:
                    raise HTTPException(status_code=400, detail="unknown op")
            except NoMatchError:
                raise HTTPException(status_code=404, detail="no assets matched")
        return {"changed": n}

    @app.post("/api/assets/tags-union")
    def assets_tags_union(body: HashesBody):
        with lock:
            tags = store.union_tags(body.hashes)
        return {"tags": tags}

    @app.post("/api/assets/delete")
    def delete_assets(body: HashesBody):
        with lock:
            result = store.delete_assets(body.hashes)
        return result

    @app.post("/api/assets/{file_hash}/reveal")
    def reveal_asset(file_hash: str):
        with lock:
            info = store.data["hashes"].get(file_hash)
            if not isinstance(info, dict):
                raise HTTPException(status_code=404, detail="asset not found")
            rel = (info.get("paths") or [""])[0]
        full = _safe_resolve(store.root_dir, rel)
        if full is None:
            raise HTTPException(status_code=404, detail="file not found")
        _reveal_in_explorer(full)
        return {"ok": True}

    @app.post("/api/synonyms/open")
    def open_synonyms():
        path = os.path.join(store.root_dir, SYNONYMS_FILE)
        created = False
        if not os.path.isfile(path):
            _SYNONYMS_TEMPLATE = (
                "# TagStore synonyms — one group per line.\n"
                "# The first word is the canonical tag; the rest are aliases.\n"
                "# A '#' at the start of a line (or after a space) is a comment.\n"
                "#\n"
                "# Example:\n"
                "# cat cats kitty\n"
            )
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(_SYNONYMS_TEMPLATE)
                created = True
            except OSError as e:
                raise HTTPException(status_code=400, detail=str(e))
        try:
            _open_in_editor(path)
        except OSError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"path": path, "created": created}

    @app.post("/api/scan")
    def start_scan():
        with lock:
            if not job.start():
                raise HTTPException(status_code=409, detail="scan already running")
        return job.state()

    @app.post("/api/scan/recompute")
    def start_recompute():
        with lock:
            if not job.start(recompute_tags=True):
                raise HTTPException(status_code=409, detail="scan already running")
        return job.state()

    @app.get("/api/scan/status")
    def scan_status():
        return job.state()

    @app.post("/api/scan/cancel")
    def cancel_scan():
        return job.cancel()

    @app.get("/api/file")
    def serve_file(path: str):
        full = _safe_resolve(store.root_dir, path)
        if full is None:
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(full, media_type=_media_type(full))

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


app = create_app(os.environ.get("TAGSTORE_ROOT", "."))


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Run the TagStore browser UI.")
    parser.add_argument("--root", default=".", help="Directory to index (default: current directory)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    args = parser.parse_args()

    app = create_app(args.root)
    uvicorn.run(app, host="127.0.0.1", port=args.port)
