"""Presentation-free TagStore model.

This module owns all data logic (JSON schema, hashing, tag inference, search,
tag editing) and returns plain Python data. It never prints to the console and
never calls ``sys.exit``; callers are expected to handle errors themselves.

A UI (CLI, browser, etc.) can drive this class directly. Long-running methods
accept an optional ``progress_cb`` callable and a ``cancel`` flag (a callable
returning a bool or an object exposing ``is_set()``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata

from .errors import DatabaseLoadError, NoMatchError, QuerySyntaxError

DB_FILE = ".tagstore.json"
SYNONYMS_FILE = "synonyms.txt"
SCHEMA_VERSION = 3
HASH_CHUNK = 64 * 1024
SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SKIP_DIRS = {
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".idea",
    ".vs",
    "venvs",
}
MIN_TOKEN_LEN = 2
MIN_TAG_MATCHES = 2


def get_default_schema():
    return {
        "version": SCHEMA_VERSION,
        "settings": {"min_tag_count_for_search": MIN_TAG_MATCHES},
        "tags": {},
        "hashes": {},
    }


def normalize_tag(tag):
    return (
        unicodedata.normalize("NFC", str(tag))
        .strip()
        .casefold()
        .replace(" ", "_")
    )


def _is_numeric(tag):
    """Return True for purely numeric content, ignoring '-'/'_' separators."""
    core = tag.replace("_", "").replace("-", "")
    return bool(core) and bool(re.fullmatch(r"[0-9]+", core))


def _unique_keep_order(items):
    seen = set()
    out = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _as_tag_record(value):
    """Normalize a global tag entry. Old DBs stored a synonym list; now {synonyms, count}."""
    if isinstance(value, dict):
        synonyms = value.get("synonyms", [])
        if not isinstance(synonyms, list):
            synonyms = []
        try:
            count = int(value.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        value["synonyms"] = synonyms
        value["count"] = max(0, count)
        return value
    synonyms = value if isinstance(value, list) else []
    return {"synonyms": synonyms, "count": 0}


def rebuild_tag_counts(data):
    """Count how many unique assets carry each tag. Metadata only — no image I/O."""
    counts = {}
    for info in (data.get("hashes") or {}).values():
        if not isinstance(info, dict):
            continue
        seen = set()
        for raw in info.get("tags") or []:
            tag = normalize_tag(raw)
            if tag:
                seen.add(tag)
        for tag in seen:
            counts[tag] = counts.get(tag, 0) + 1

    tags = data.setdefault("tags", {})
    if not isinstance(tags, dict):
        tags = {}
        data["tags"] = tags

    for tag in list(tags):
        tags[tag] = _as_tag_record(tags[tag])
        tags[tag]["count"] = counts.get(tag, 0)
    for tag, n in counts.items():
        if tag not in tags:
            tags[tag] = {"synonyms": [], "count": n}
        else:
            tags[tag]["count"] = n
    return counts


def migrate_schema(data):
    """Upgrade older .tagstore.json files in place without dropping fields."""
    if not isinstance(data, dict):
        raise ValueError("database root must be a JSON object")

    data.setdefault("version", 1)
    data.setdefault("settings", {})
    if not isinstance(data["settings"], dict):
        data["settings"] = {}
    data["settings"].setdefault("min_tag_count_for_search", MIN_TAG_MATCHES)
    data.setdefault("tags", {})
    data.setdefault("hashes", {})
    if not isinstance(data["tags"], dict):
        data["tags"] = {}
    if not isinstance(data["hashes"], dict):
        data["hashes"] = {}

    for h, info in list(data["hashes"].items()):
        if not isinstance(info, dict):
            data["hashes"][h] = {
                "path": "",
                "paths": [],
                "tags": [],
                "files": {},
            }
            continue
        paths = []
        raw_paths = info.get("paths")
        if isinstance(raw_paths, list):
            paths.extend(str(p).replace("\\", "/") for p in raw_paths if p)
        elif isinstance(raw_paths, str) and raw_paths:
            paths.append(raw_paths.replace("\\", "/"))
        single = info.get("path")
        if isinstance(single, str) and single:
            paths.insert(0, single.replace("\\", "/"))
        info["paths"] = _unique_keep_order(paths)
        info["path"] = info["paths"][0] if info["paths"] else ""
        info.setdefault("animated", False)
        tags = info.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        info["tags"] = _unique_keep_order(normalize_tag(t) for t in tags)
        files = info.get("files")
        if not isinstance(files, dict):
            files = {}
        cleaned = {}
        for p, meta in files.items():
            if not isinstance(meta, dict):
                continue
            cleaned[str(p).replace("\\", "/")] = {
                "size": int(meta["size"]) if "size" in meta else None,
                "mtime_ns": int(meta["mtime_ns"]) if "mtime_ns" in meta else None,
            }
        info["files"] = cleaned

    for tag, value in list(data["tags"].items()):
        data["tags"][tag] = _as_tag_record(value)

    rebuild_tag_counts(data)
    data["version"] = SCHEMA_VERSION
    return data


def _read_exact(f, n):
    """Read exactly ``n`` bytes or return ``None`` if the stream is too short."""
    data = f.read(n)
    return data if len(data) == n else None


def _skip_sub_blocks(f):
    """Consume a GIF sub-block stream (size byte + data, terminated by 0x00)."""
    while True:
        size = _read_exact(f, 1)
        if size is None:
            return False
        if size[0] == 0:
            return True
        if _read_exact(f, size[0]) is None:
            return False


def detect_animation(path):
    """Return True if the image at ``path`` is animated (GIF/WebP/APNG).

    Only small header reads are performed; the file is never fully loaded.
    Any malformed or unknown input simply returns False.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            if len(head) < 12:
                return False
            if head[:6] in (b"GIF87a", b"GIF89a"):
                f.seek(6)
                return _detect_gif_animation(f)
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                f.seek(12)
                return _detect_webp_animation(f)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                f.seek(8)
                return _detect_png_animation(f)
    except OSError:
        return False
    return False


def _detect_gif_animation(f):
    """Count GIF image separators (frames); animated when more than one."""
    lsd = _read_exact(f, 7)
    if lsd is None:
        return False
    packed = lsd[4]
    if packed & 0x80:
        gct_size = 3 * (2 ** ((packed & 0x07) + 1))
        if _read_exact(f, gct_size) is None:
            return False
    frames = 0
    while True:
        block = _read_exact(f, 1)
        if block is None:
            return False
        marker = block[0]
        if marker == 0x3B:
            return frames > 1
        if marker == 0x2C:
            frames += 1
            desc = _read_exact(f, 9)
            if desc is None:
                return False
            packed = desc[8]
            if packed & 0x80:
                lct_size = 3 * (2 ** ((packed & 0x07) + 1))
                if _read_exact(f, lct_size) is None:
                    return False
            if _read_exact(f, 1) is None:  # LZW minimum code size
                return False
            if not _skip_sub_blocks(f):
                return False
        elif marker == 0x21:
            label = _read_exact(f, 1)
            if label is None:
                return False
            if not _skip_sub_blocks(f):
                return False
        else:
            return False


def _detect_webp_animation(f):
    """Scan RIFF chunks for a VP8X chunk; its flags byte bit 0x02 marks animation."""
    while True:
        chunk = _read_exact(f, 8)
        if chunk is None:
            return False
        fourcc, size = chunk[:4], int.from_bytes(chunk[4:8], "little")
        if fourcc == b"VP8X":
            flags = _read_exact(f, 4)
            if flags is None:
                return False
            return bool(flags[0] & 0x02)
        size += size & 1
        if size and _read_exact(f, size) is None:
            return False
        if fourcc == b"VP8 " or fourcc == b"VP8L":
            return False


def _detect_png_animation(f):
    """Check PNG chunks after IHDR for an ``acTL`` chunk (APNG marker)."""
    ihdr = _read_exact(f, 8)
    if ihdr is None:
        return False
    length = int.from_bytes(ihdr[:4], "big")
    if length != 13:
        return False
    if _read_exact(f, length + 4) is None:  # IHDR payload + CRC
        return False
    for _ in range(32):
        header = _read_exact(f, 8)
        if header is None:
            return False
        length = int.from_bytes(header[:4], "big")
        chunk_type = header[4:8]
        if chunk_type == b"acTL":
            return True
        if chunk_type == b"IDAT" or chunk_type == b"IEND":
            return False
        skip = length + 4
        if skip and _read_exact(f, skip) is None:
            return False
    return False


def _is_cancelled(cancel):
    if cancel is None:
        return False
    if callable(cancel):
        return bool(cancel())
    return bool(cancel.is_set())


class TagStore:
    """Hash-based image tag index. Pure data; no presentation."""

    def __init__(self, root_dir="."):
        self.root_dir = os.path.abspath(root_dir)
        self.db_path = os.path.join(self.root_dir, DB_FILE)
        self.synonym_map = {}
        self.synonym_groups = {}
        self._load_synonyms()
        self.data = self._load()
        self.apply_synonyms()
        self._prune_spurious_tags()

    def _load_synonyms(self):
        """Read the synonyms file: one group per line, first tag is canonical.

        A ``#`` starts a comment when it appears at the start of a line or is
        preceded by whitespace (Python-style). Blank lines are ignored.
        Example: ``cat cats`` maps ``cats`` -> ``cat``.
        """
        self.synonym_map = {}
        self.synonym_groups = {}
        path = os.path.join(self.root_dir, SYNONYMS_FILE)
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return
        for line in lines:
            stripped = self._strip_comment(line).strip()
            if not stripped:
                continue
            parts = [p for p in (normalize_tag(p) for p in stripped.split()) if p]
            if not parts:
                continue
            canon = parts[0]
            aliases = [a for a in parts[1:] if a != canon]
            self.synonym_groups.setdefault(canon, [])
            for alias in aliases:
                if alias not in self.synonym_map:
                    self.synonym_map[alias] = canon
                if alias not in self.synonym_groups[canon]:
                    self.synonym_groups[canon].append(alias)

    def canonicalize(self, tag):
        tag = normalize_tag(tag)
        if not tag:
            return tag
        return self.synonym_map.get(tag, tag)

    @staticmethod
    def _strip_comment(line):
        """Cut a line at the first ``#`` that starts a comment (Python-style)."""
        for i, ch in enumerate(line):
            if ch == "#" and (i == 0 or line[i - 1].isspace()):
                return line[:i]
        return line

    def _clean_tags(self, values):
        """Normalize, canonicalize, de-duplicate and drop numeric/empty tags."""
        out = []
        seen = set()
        for v in values or []:
            c = self.canonicalize(v)
            if not c or _is_numeric(c) or c in seen:
                continue
            seen.add(c)
            out.append(c)
        return out

    def apply_synonyms(self):
        """Canonicalize stored tags and attach synonym metadata; rebuilds counts."""
        if self.synonym_map:
            for info in self.data.get("hashes", {}).values():
                if not isinstance(info, dict):
                    continue
                info["tags"] = sorted(self._clean_tags(info.get("tags") or []))
        rebuild_tag_counts(self.data)
        if not self.synonym_map:
            return
        tags = self.data.setdefault("tags", {})
        for canon, aliases in self.synonym_groups.items():
            if canon in tags:
                rec = _as_tag_record(tags[canon])
                rec["synonyms"] = aliases
                tags[canon] = rec
        for alias in self.synonym_map:
            tags.pop(alias, None)

    def _min_visible_count(self):
        """Minimum matches a tag needs to be treated as a real tag (default: MIN_TAG_MATCHES)."""
        settings = self.data.get("settings") or {}
        try:
            value = int(settings.get("min_tag_count_for_search", MIN_TAG_MATCHES))
        except (TypeError, ValueError):
            value = MIN_TAG_MATCHES
        return max(1, value)

    def tag_count(self, tag):
        rec = (self.data.get("tags") or {}).get(self.canonicalize(tag))
        if isinstance(rec, dict):
            try:
                return int(rec.get("count") or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    def visible_tags(self, tags):
        threshold = self._min_visible_count()
        seen = set()
        out = []
        for t in tags:
            c = self.canonicalize(t)
            if not c or c in seen:
                continue
            seen.add(c)
            if self.tag_count(c) >= threshold:
                out.append(c)
        return out

    def _prune_spurious_tags(self):
        """Hide tags matched fewer than the minimum from the global index.

        Only the global tag index is pruned; asset tags are left intact so they
        are re-counted accurately on the next scan (no tag is ever lost during
        scanning).
        """
        threshold = self._min_visible_count()
        counts = rebuild_tag_counts(self.data)
        for tag in list(self.data["tags"]):
            if _as_tag_record(self.data["tags"][tag]).get("count", 0) < threshold:
                self.data["tags"].pop(tag, None)
        return {t: n for t, n in counts.items() if n >= threshold}

    def _load(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return migrate_schema(data)
            except Exception as e:
                raise DatabaseLoadError(f"error loading database: {e}") from e
        return get_default_schema()

    def save(self):
        payload = json.dumps(self.data, indent=2, ensure_ascii=False)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".tagstore.",
            suffix=".tmp",
            dir=self.root_dir,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.db_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def add_tag_to_global(self, tag):
        tag = self.canonicalize(tag)
        if not tag or _is_numeric(tag):
            return
        existing = self.data["tags"].get(tag)
        if existing is None:
            self.data["tags"][tag] = {"synonyms": [], "count": 0}
        else:
            self.data["tags"][tag] = _as_tag_record(existing)

    def compute_hash(self, filepath):
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(HASH_CHUNK)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()

    def infer_tags(self, rel_path):
        parts = rel_path.replace("\\", "/").split("/")
        tags = set()
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                part = os.path.splitext(part)[0]
            for token in re.split(r"[_\s]+", part):
                token = self.canonicalize(token)
                if (
                    token
                    and len(token) >= MIN_TOKEN_LEN
                    and not _is_numeric(token)
                    and re.match(r"^\w+(-\w+)*$", token)
                ):
                    tags.add(token)
        return tags

    def _rel(self, filepath):
        return os.path.relpath(filepath, self.root_dir).replace("\\", "/")

    def _iter_image_paths(self):
        """Yield image paths without keeping the whole tree in RAM."""
        for root, dirs, files in os.walk(self.root_dir, topdown=True):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if os.path.splitext(name)[1].lower() in SUPPORTED_EXTS:
                    yield os.path.join(root, name)

    def _path_cache(self):
        """rel_path -> (hash, size, mtime_ns) from the existing index."""
        cache = {}
        for h, info in self.data["hashes"].items():
            files = info.get("files") or {}
            for rel in info.get("paths") or []:
                meta = files.get(rel) or {}
                cache[rel] = (h, meta.get("size"), meta.get("mtime_ns"))
        return cache

    def _ensure_entry(self, file_hash):
        entry = self.data["hashes"].get(file_hash)
        if not isinstance(entry, dict):
            entry = {"path": "", "paths": [], "tags": [], "files": {}}
            self.data["hashes"][file_hash] = entry
        entry.setdefault("paths", [])
        entry.setdefault("tags", [])
        entry.setdefault("files", {})
        if not isinstance(entry["files"], dict):
            entry["files"] = {}
        return entry

    def _merge_location(self, file_hash, rel_path, size, mtime_ns, infer=False, animated=False):
        """Attach a path to a hash and union tags (duplicate copies share one record)."""
        entry = self._ensure_entry(file_hash)
        paths = _unique_keep_order(list(entry.get("paths") or []) + [rel_path])
        entry["paths"] = paths
        entry["path"] = paths[0]
        entry.setdefault("files", {})
        entry["files"][rel_path] = {"size": size, "mtime_ns": mtime_ns}

        entry["animated"] = bool(animated)
        tags = set(entry.get("tags") or [])
        if infer:
            tags.update(self.infer_tags(rel_path))
        if entry.get("animated"):
            tags.add("animated")
        entry["tags"] = sorted(tags)
        for tag in tags:
            self.add_tag_to_global(tag)
        return entry

    def _recompute_all_tags(self):
        """Rebuild every asset's tags from scratch based on its current paths."""
        for info in self.data["hashes"].values():
            if not isinstance(info, dict):
                continue
            tags = set()
            for rel in info.get("paths") or []:
                tags.update(self.infer_tags(rel))
            if info.get("animated"):
                tags.add("animated")
            info["tags"] = sorted(tags)

    def scan(self, progress_cb=None, cancel=None, recompute_tags=False):
        """Index images. Returns a summary dict. Fires ``progress_cb(done, total)``.

        When ``recompute_tags`` is true, tags are rebuilt from scratch after the
        walk so renamed folders/files no longer leave stale tags behind.
        """
        self._load_synonyms()
        cache = self._path_cache()
        seen_hashes = set()
        seen_paths = set()
        hashed = 0
        reused = 0
        merged = 0
        error_list = []
        new_assets = 0
        cancelled = False

        total = sum(1 for _ in self._iter_image_paths())

        done = 0
        for filepath in self._iter_image_paths():
            if _is_cancelled(cancel):
                cancelled = True
                break
            try:
                rel = self._rel(filepath)
                st = os.stat(filepath)
                size, mtime_ns = st.st_size, st.st_mtime_ns
                cached = cache.get(rel)
                if (
                    cached
                    and cached[1] == size
                    and cached[2] == mtime_ns
                    and cached[0] in self.data["hashes"]
                ):
                    file_hash = cached[0]
                    reused += 1
                    is_new_path = False
                else:
                    file_hash = self.compute_hash(filepath)
                    hashed += 1
                    is_new_path = rel not in (self.data["hashes"].get(file_hash, {}).get("paths") or [])

                existed = file_hash in self.data["hashes"]
                if existed and is_new_path:
                    merged += 1
                if not existed:
                    new_assets += 1

                animated = detect_animation(filepath)
                infer = True
                self._merge_location(file_hash, rel, size, mtime_ns, infer=infer, animated=animated)
                seen_hashes.add(file_hash)
                seen_paths.add(rel)
            except OSError as e:
                error_list.append(f"{filepath}: {e}")
            done += 1
            if progress_cb:
                progress_cb(done, total)

        stale_hashes = []
        for h, info in self.data["hashes"].items():
            keep = [p for p in (info.get("paths") or []) if p in seen_paths]
            if not keep:
                stale_hashes.append(h)
                continue
            info["paths"] = keep
            info["path"] = keep[0]
            files_meta = info.get("files") or {}
            info["files"] = {p: files_meta[p] for p in keep if p in files_meta}

        for h in stale_hashes:
            del self.data["hashes"][h]

        if recompute_tags:
            self._recompute_all_tags()

        self.apply_synonyms()
        counts = self._prune_spurious_tags()

        self.save()

        return {
            "assets": len(self.data["hashes"]),
            "files_seen": len(seen_paths),
            "hashed": hashed,
            "reused": reused,
            "merged": merged,
            "new_assets": new_assets,
            "tags_total": len(counts),
            "min_matches": self._min_visible_count(),
            "errors": error_list,
            "cancelled": cancelled,
            "total": total,
        }

    def query_details(self, query_str):
        """Parse a query and return ``{results, keywords}``.

        ``keywords`` is an ordered list of ``{"term", "hits"}`` for the literal
        tag terms in the query. Terms with zero hits are treated as ``True``
        (match-all) so they are effectively ignored.
        """
        tokens = re.findall(r"\(|\)|AND|OR|NOT|[\w-]+", query_str.upper())
        pos = 0

        term_hits = {}
        term_order = []
        for tok in tokens:
            if tok in ("(", ")", "AND", "OR", "NOT"):
                continue
            term = self.canonicalize(tok.lower())
            if term not in term_hits:
                term_hits[term] = self.tag_count(term)
                term_order.append(term)
        keywords = [{"term": t, "hits": term_hits[t]} for t in term_order]

        def parse_or():
            nonlocal pos
            left = parse_and()
            while pos < len(tokens) and tokens[pos] == "OR":
                pos += 1
                right = parse_and()
                left = lambda tags, l=left, r=right: l(tags) or r(tags)
            return left

        def parse_and():
            nonlocal pos
            left = parse_not()
            while pos < len(tokens) and tokens[pos] not in (")", "OR"):
                if tokens[pos] == "AND":
                    pos += 1
                    if pos >= len(tokens) or tokens[pos] in (")", "OR"):
                        break
                right = parse_not()
                left = lambda tags, l=left, r=right: l(tags) and r(tags)
            return left

        def parse_not():
            nonlocal pos
            if pos < len(tokens) and tokens[pos] == "NOT":
                pos += 1
                operand = parse_primary()
                return lambda tags, op=operand: not op(tags)
            return parse_primary()

        def parse_primary():
            nonlocal pos
            if pos < len(tokens) and tokens[pos] == "(":
                pos += 1
                res = parse_or()
                if pos < len(tokens) and tokens[pos] == ")":
                    pos += 1
                return res
            if pos < len(tokens):
                tag = self.canonicalize(tokens[pos].lower())
                pos += 1
                if term_hits.get(tag, 0) == 0:
                    return lambda tags: True
                return lambda tags, t=tag: t in tags
            return lambda tags: True

        if not tokens:
            return {"results": [], "keywords": keywords}

        try:
            matcher = parse_or()
        except Exception as e:
            raise QuerySyntaxError(query_str) from e

        results = []
        for h, info in self.data["hashes"].items():
            if not isinstance(info, dict):
                continue
            if matcher(set(info.get("tags") or [])):
                results.append((h, info))
        return {"results": results, "keywords": keywords}

    def search(self, query_str):
        return self.query_details(query_str)["results"]

    def _append_tags_to_filenames(self, entry, tags):
        """Append new tags to each file copy's name (``cat.png`` -> ``cat dog.png``).

        Renames every path of the asset on disk and keeps the index in sync.
        Returns a list of error strings for copies that could not be renamed.
        """
        errors = []
        tags = [t for t in tags if t]
        if not tags:
            return errors

        new_paths = []
        renamed = {}
        for rel in entry.get("paths") or []:
            if "/" in rel:
                directory, filename = rel.rsplit("/", 1)
            else:
                directory, filename = "", rel
            stem, ext = os.path.splitext(filename)
            existing = set(re.split(r"[_\s]+", stem))
            to_add = [t for t in tags if t not in existing]
            if not to_add:
                new_paths.append(rel)
                continue

            new_filename = f"{stem} {' '.join(to_add)}{ext}"
            new_rel = f"{directory}/{new_filename}" if directory else new_filename

            src = os.path.join(self.root_dir, *rel.split("/"))
            dst = os.path.join(self.root_dir, *new_rel.split("/"))
            try:
                os.rename(src, dst)
            except OSError as e:
                errors.append(f"{rel}: {e}")
                new_paths.append(rel)
                continue
            renamed[rel] = new_rel
            new_paths.append(new_rel)

        entry["paths"] = _unique_keep_order(new_paths)
        entry["path"] = entry["paths"][0] if entry["paths"] else ""

        new_files = {}
        for old_rel, meta in (entry.get("files") or {}).items():
            target = renamed.get(old_rel, old_rel)
            try:
                st = os.stat(os.path.join(self.root_dir, *target.split("/")))
                new_files[target] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
            except OSError:
                new_files[target] = meta
        entry["files"] = new_files
        return errors

    def _apply_tag_edit(self, entries, tags_to_add=None, tags_to_remove=None, override=False):
        tags_to_add = self._clean_tags(tags_to_add)
        tags_to_remove = self._clean_tags(tags_to_remove)

        for h, info in entries:
            if override:
                current_tags = set()
            else:
                current_tags = set(info.get("tags") or [])
            current_tags.update(tags_to_add)
            current_tags.difference_update(tags_to_remove)
            info["tags"] = sorted(current_tags)
            for t in tags_to_add:
                self.add_tag_to_global(t)
            if tags_to_add and not override:
                self._append_tags_to_filenames(info, tags_to_add)

        self.apply_synonyms()
        self.save()

    def modify_tags(self, query_str, tags_to_add=None, tags_to_remove=None, override=False):
        results = self.search(query_str)
        if not results:
            raise NoMatchError(query_str)
        self._apply_tag_edit(results, tags_to_add, tags_to_remove, override)
        return len(results)

    def modify_asset_tags(self, file_hash, tags_to_add=None, tags_to_remove=None, override=False):
        entry = self.data["hashes"].get(file_hash)
        if not isinstance(entry, dict):
            raise NoMatchError(file_hash)
        self._apply_tag_edit([(file_hash, entry)], tags_to_add, tags_to_remove, override)
        return 1

    def modify_assets_tags(self, file_hashes, tags_to_add=None, tags_to_remove=None, override=False):
        entries = []
        for h in file_hashes:
            entry = self.data["hashes"].get(h)
            if isinstance(entry, dict):
                entries.append((h, entry))
        if not entries:
            raise NoMatchError(str(file_hashes))
        self._apply_tag_edit(entries, tags_to_add, tags_to_remove, override)
        return len(entries)

    def union_tags(self, file_hashes):
        """Count how many of the given assets carry each tag (union, sorted by count).

        Only tags that meet the global minimum-occurrence threshold are returned.
        """
        counts = {}
        for h in file_hashes:
            info = self.data["hashes"].get(h)
            if not isinstance(info, dict):
                continue
            seen = set()
            for raw in info.get("tags") or []:
                tag = self.canonicalize(raw)
                if tag:
                    seen.add(tag)
            for tag in seen:
                counts[tag] = counts.get(tag, 0) + 1
        threshold = self._min_visible_count()
        return [
            {"tag": t, "count": c}
            for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            if self.tag_count(t) >= threshold
        ]

    def delete_assets(self, file_hashes):
        """Delete the primary copy of each asset (Recycle Bin when available).

        Removes only the primary path from disk and the index. If other copies
        remain, the entry is kept with a new primary; otherwise the whole entry
        is dropped. Returns a summary of what happened.
        """
        try:
            from send2trash import send2trash
        except ImportError:
            send2trash = os.remove

        deleted_files = 0
        deleted_assets = 0
        errors = []
        for h in file_hashes:
            entry = self.data["hashes"].get(h)
            if not isinstance(entry, dict):
                continue
            paths = entry.get("paths") or []
            if not paths:
                del self.data["hashes"][h]
                deleted_assets += 1
                continue
            primary = paths[0]
            full = os.path.join(self.root_dir, *primary.split("/"))
            try:
                send2trash(full)
            except OSError as e:
                errors.append(f"{primary}: {e}")
                continue
            deleted_files += 1

            remaining = paths[1:]
            if remaining:
                entry["paths"] = remaining
                entry["path"] = remaining[0]
                files = entry.get("files") or {}
                entry["files"] = {p: files[p] for p in remaining if p in files}
            else:
                del self.data["hashes"][h]
                deleted_assets += 1

        self.apply_synonyms()
        self._prune_spurious_tags()
        self.save()
        return {
            "deleted_files": deleted_files,
            "deleted_assets": deleted_assets,
            "errors": errors,
        }

    def rename_asset(self, file_hash, new_stem):
        """Rename the primary copy's filename stem and recompute tags.

        Keeps the folder and extension; only the base name changes. Tags are
        re-derived from every remaining path (filename + folders), matching the
        behaviour of a full scan. Returns the updated entry.
        """
        entry = self.data["hashes"].get(file_hash)
        if not isinstance(entry, dict):
            raise NoMatchError(file_hash)

        paths = entry.get("paths") or []
        if not paths:
            raise NoMatchError(file_hash)
        rel = paths[0]

        if "/" in rel:
            directory, filename = rel.rsplit("/", 1)
        else:
            directory, filename = "", rel
        stem, ext = os.path.splitext(filename)

        new_stem = (new_stem or "").strip()
        if not new_stem or "/" in new_stem or "\\" in new_stem:
            raise ValueError("invalid filename stem")
        if new_stem == stem:
            return entry

        new_filename = f"{new_stem}{ext}"
        new_rel = f"{directory}/{new_filename}" if directory else new_filename

        src = os.path.join(self.root_dir, *rel.split("/"))
        dst = os.path.join(self.root_dir, *new_rel.split("/"))
        os.rename(src, dst)

        entry["paths"] = _unique_keep_order([new_rel] + paths[1:])
        entry["path"] = entry["paths"][0]

        files = entry.get("files") or {}
        new_files = {p: files[p] for p in entry["paths"] if p in files}
        new_files.pop(rel, None)
        st = os.stat(dst)
        new_files[new_rel] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
        entry["files"] = new_files

        tags = set()
        for p in entry["paths"]:
            tags.update(self.infer_tags(p))
        if entry.get("animated"):
            tags.add("animated")
        entry["tags"] = sorted(tags)
        for t in tags:
            self.add_tag_to_global(t)

        self.apply_synonyms()
        self._prune_spurious_tags()
        self.save()
        return entry

    def list_tags(self):
        threshold = self._min_visible_count()
        tags = self.data.get("tags") or {}
        records = []
        for tag, rec in tags.items():
            rec = _as_tag_record(rec)
            synonyms = rec.get("synonyms") or []
            count = rec.get("count", 0)
            for alias in synonyms:
                alias_rec = tags.get(alias)
                if isinstance(alias_rec, dict):
                    count += _as_tag_record(alias_rec).get("count", 0)
            records.append(
                {
                    "tag": tag,
                    "count": count,
                    "synonyms": synonyms,
                }
            )
        records.sort(key=lambda r: (-r["count"], r["tag"]))
        for r in records:
            r["visible"] = r["count"] >= threshold
        return records

    def result_entries(self, results):
        """Convert ``search`` results into serializable dicts."""
        out = []
        for h, info in results:
            paths = info.get("paths") or ([info["path"]] if info.get("path") else [])
            primary = paths[0] if paths else ""
            meta = (info.get("files") or {}).get(primary) or {}
            try:
                date = int(meta.get("mtime_ns") or 0)
            except (TypeError, ValueError):
                date = 0
            out.append(
                {
                    "hash": h,
                    "paths": list(paths),
                    "primary_path": primary,
                    "name": os.path.basename(primary) if primary else "",
                    "date": date,
                    "tags": sorted(info.get("tags") or []),
                    "visible_tags": self.visible_tags(info.get("tags") or []),
                }
            )
        return out
