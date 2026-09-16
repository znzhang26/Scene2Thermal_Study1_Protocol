"""Read the Scene2Thermal dataset.

Only Object_name and Object_category are read from the scene CSV. From
request_log.csv only the *request* side of object-inference rows is parsed
(object name + image paths); model responses are never interpreted.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

import config

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

_RUN_RE = re.compile(r"^(?P<run>.+?_[0-9a-fA-F]{6,})_(?P<idx>\d+)_(?P<kind>[A-Za-z]+)(?P<n>\d*)$")


def scene_dir(scene_id: str, data_root: Path | None = None) -> Path:
    return (data_root or config.DATA_ROOT) / config.SCENES[scene_id]


def scene_csv_path(scene_id: str, data_root: Path | None = None) -> Path:
    return scene_dir(scene_id, data_root) / config.SCENE_CSV_NAME


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_scene_objects(csv_path: Path) -> pd.DataFrame:
    """Return source_row_index, object_name, object_category.

    Raises ValueError if the required columns are missing. The thermal
    prediction columns are never loaded (usecols filter).
    """
    header = pd.read_csv(csv_path, nrows=0, encoding="utf-8-sig")
    stripped = {c.strip(): c for c in header.columns}
    missing = [c for c in config.REQUIRED_COLUMNS if c not in stripped]
    if missing:
        raise ValueError(f"missing column(s): {', '.join(missing)}")
    wanted = {stripped[c] for c in config.REQUIRED_COLUMNS}
    df = pd.read_csv(
        csv_path,
        usecols=lambda c: c in wanted,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={"Object_name": "object_name", "Object_category": "object_category"})
    df["object_name"] = df["object_name"].str.strip()
    df["object_category"] = df["object_category"].str.strip()
    df.insert(0, "source_row_index", range(len(df)))
    return df[["source_row_index", "object_name", "object_category"]]


def _image_sort_key(p: Path):
    m = _RUN_RE.match(p.stem)
    if m:
        return (m.group("run"), int(m.group("idx")), p.name)
    return ("", 0, p.name)


def image_run(p: Path) -> str:
    m = _RUN_RE.match(p.stem)
    return m.group("run") if m else ""


def list_scene_images(scene_id: str, data_root: Path | None = None, *, apply_pin: bool = True) -> list[Path]:
    d = scene_dir(scene_id, data_root) / config.SCENE_IMAGE_SUBDIR
    if not d.is_dir():
        return []
    imgs = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in config.IMAGE_EXTENSIONS
            and not p.name.startswith(".") and p.stat().st_size > 0]
    imgs.sort(key=_image_sort_key)
    pin = config.SCENE_IMAGE_RUN.get(scene_id) if apply_pin else None
    if pin:
        imgs = [p for p in imgs if image_run(p) == pin]
    return imgs


def count_object_images(scene_id: str, data_root: Path | None = None) -> int:
    d = scene_dir(scene_id, data_root) / config.OBJECT_IMAGE_SUBDIR
    if not d.is_dir():
        return 0
    return sum(1 for p in d.iterdir() if p.suffix.lower() in config.IMAGE_EXTENSIONS)


@dataclass
class ObjectImageIndex:
    """Maps source_row_index -> object-inference image paths."""
    by_row: dict[int, dict[str, list[Path]]] = field(default_factory=dict)
    request_count: int = 0
    matched_rows: int = 0
    notes: list[str] = field(default_factory=list)


def build_object_image_index(scene_id: str, objects: pd.DataFrame, data_root: Path | None = None) -> ObjectImageIndex:
    """Match object-inference requests to CSV rows by object name.

    request_log.csv has no row index, so the k-th row with a given name is
    matched to the k-th request with that name (file order). This is a
    best-effort mapping for display only.
    """
    idx = ObjectImageIndex()
    sdir = scene_dir(scene_id, data_root)
    log = sdir / config.REQUEST_LOG_NAME
    if not log.is_file():
        idx.notes.append("request_log.csv not found — no object images")
        return idx
    requests: dict[str, list[list[str]]] = {}
    try:
        with open(log, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            header = next(reader, [])
            try:
                t_col = header.index("request-type")
                c_col = header.index("request content")
            except ValueError:
                idx.notes.append("request_log.csv has unexpected columns — no object images")
                return idx
            for row in reader:  # response column is never parsed
                if len(row) <= max(t_col, c_col) or row[t_col].strip() != "object inference":
                    continue
                try:
                    content = json.loads(row[c_col])
                    name = str(json.loads(content.get("jsonText", "{}")).get("name", "")).strip()
                    images = [str(i) for i in content.get("images", [])]
                except (json.JSONDecodeError, AttributeError, TypeError):
                    continue
                requests.setdefault(name, []).append(images)
                idx.request_count += 1
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        idx.notes.append(f"request_log.csv unreadable ({type(exc).__name__}) — no object images")
        return idx

    seen: dict[str, int] = {}
    for rec in objects.itertuples(index=False):
        k = seen.get(rec.object_name, 0)
        seen[rec.object_name] = k + 1
        reqs = requests.get(rec.object_name, [])
        if k >= len(reqs):
            continue
        iso, ctx = [], []
        for rel in reqs[k]:
            p = sdir.joinpath(*re.split(r"[\\/]", rel))
            if not p.is_file():
                continue
            kind = (_RUN_RE.match(p.stem).group("kind") if _RUN_RE.match(p.stem) else "").lower()
            (iso if kind.startswith("iso") else ctx).append(p)
        if iso or ctx:
            idx.by_row[int(rec.source_row_index)] = {"iso": iso, "context": ctx}
            idx.matched_rows += 1
    mismatched = [n for n, c in seen.items() if c != len(requests.get(n, []))]
    if mismatched:
        idx.notes.append(f"{len(mismatched)} object name(s) have a different number of CSV rows and image requests")
    return idx


def rel_to_data_root(p: Path | None, data_root: Path | None = None) -> str:
    if p is None:
        return ""
    root = data_root or config.DATA_ROOT
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()
