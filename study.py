"""Shared study state for the Streamlit views (cached data access)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import streamlit as st

import config
import data_loader as dl
import database as db
import manifest as mf
import validation as val


@st.cache_data(ttl=300, show_spinner="Checking the study dataset…")
def _preflight(data_root: str) -> list[val.SceneCheck]:
    return val.run_preflight(Path(data_root))


def checks() -> list[val.SceneCheck]:
    return _preflight(str(config.DATA_ROOT))


def clear_caches() -> None:
    _preflight.clear()
    _manifest.clear()
    _image_index.clear()


@st.cache_data(show_spinner=False)
def _manifest(path: str, sha: str) -> pd.DataFrame:
    return mf.load_manifest(Path(path))


def manifest() -> tuple[pd.DataFrame | None, str, str]:
    """(manifest, sha256, error message)."""
    if not mf.manifest_exists():
        return None, "", "missing"
    sha = mf.manifest_sha256()
    try:
        return _manifest(str(config.MANIFEST_PATH), sha), sha, ""
    except Exception as exc:  # malformed manifest
        return None, sha, f"invalid: {exc}"


def allow_partial() -> bool:
    v = db.get_meta("allow_partial_dataset")
    return config.DEV_ALLOW_PARTIAL_DATASET_DEFAULT if v is None else v == "1"


@dataclass
class StudyState:
    ready: bool
    reason: str
    checks: list
    manifest: pd.DataFrame | None
    manifest_sha: str
    available: list[str] = field(default_factory=list)


def state() -> StudyState:
    cks = checks()
    man, sha, err = manifest()
    usable = [c.scene_id for c in cks if c.available]
    if man is None:
        return StudyState(False, "manifest " + (err or "missing"), cks, None, sha, [])
    in_manifest = set(man.loc[man["included"] == 1, "scene_id"])
    available = [s for s in config.SCENES if s in usable and s in in_manifest]
    if not available:
        return StudyState(False, "no available scenes", cks, man, sha, [])
    if len(usable) < len(config.SCENES) and not allow_partial():
        return StudyState(False, "partial dataset not allowed", cks, man, sha, available)
    return StudyState(True, "", cks, man, sha, available)


def label(scene_id: str) -> str:
    return config.SCENE_LABELS.get(scene_id, scene_id.replace("_", " ").title())


def scene_images(scene_id: str) -> list[Path]:
    for c in checks():
        if c.scene_id == scene_id:
            return c.scene_images
    return []


@st.cache_data(show_spinner=False)
def _image_index(scene_id: str, csv_sha: str, data_root: str) -> dict[int, dict[str, list[str]]]:
    chk = next(c for c in checks() if c.scene_id == scene_id)
    idx = dl.build_object_image_index(scene_id, chk.objects, Path(data_root))
    return {r: {k: [str(p) for p in v] for k, v in d.items()} for r, d in idx.by_row.items()}


def object_images(obj: dict) -> dict[str, list[Path]]:
    """Isolated + context views for a study object; empty lists if none."""
    chk = next((c for c in checks() if c.scene_id == obj["scene_id"]), None)
    out = {"iso": [], "context": []}
    if chk and chk.available:
        found = _image_index(obj["scene_id"], chk.csv_sha256, str(config.DATA_ROOT)).get(int(obj["source_row_index"]), {})
        out = {k: [Path(p) for p in found.get(k, [])] for k in ("iso", "context")}
    hint = obj.get("object_image_path") or ""
    if not out["iso"] and hint:
        p = config.DATA_ROOT / hint
        if p.is_file():
            out["iso"] = [p]
    return out


_GROUND_RE = re.compile(config.GROUND_EQUIVALENT_PATTERN, re.IGNORECASE)


def components(scene_id: str, objs: list[dict]) -> list[dict]:
    """Nodes for the heat-transfer graph: environment nodes + study objects.

    A synthetic ground node is omitted if a study object already represents
    the ground / floor / terrain.
    """
    nodes = [dict(id=config.ENV_AMBIENT_AIR[0], name=config.ENV_AMBIENT_AIR[1], short="Ambient air", env=True)]
    if not any(_GROUND_RE.search(o["object_category"]) for o in objs):
        nodes.append(dict(id=config.ENV_GROUND[0], name=config.ENV_GROUND[1], short="Supporting surface", env=True))
    if scene_id in config.RADIANT_NODE_SCENES:
        nodes.append(dict(id=config.ENV_RADIANT[0], name=config.ENV_RADIANT[1], short="Sky / sun", env=True))
    counts: dict[str, int] = {}
    for o in objs:
        counts[o["object_category"]] = counts.get(o["object_category"], 0) + 1
    for o in objs:
        cat = o["object_category"]
        name = cat[:1].upper() + cat[1:]
        short = name if counts[cat] == 1 else f"{name} #{int(o['source_row_index'])}"
        nodes.append(dict(id=o["object_id"], name=name, short=short, env=False, internal=o["object_name"]))
    return nodes
