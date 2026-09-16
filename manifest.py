"""Study manifest: the frozen set of study objects.

Sampling (which objects are in the study) is separate from per-expert
presentation order (database.py). Sampling uses only Object_category,
Object_name, source row and scene membership.
"""
from __future__ import annotations

import hashlib
import random
from pathlib import Path

import pandas as pd

import config
import data_loader as dl

MANIFEST_COLUMNS = [
    "scene_id", "object_id", "source_row_index", "object_name", "object_category",
    "object_image_path", "included", "sampling_seed", "sampling_pass", "category_size",
    "source_csv_sha256",
]


def make_object_id(scene_id: str, source_row_index: int) -> str:
    return f"{scene_id}_{int(source_row_index):04d}"


def _rng(seed: str, scene_id: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{scene_id}".encode()).hexdigest()
    return random.Random(int(digest[:12], 16))


def sample_scene(objects: pd.DataFrame, scene_id: str, seed: str = config.SAMPLING_SEED,
                 n: int = config.OBJECTS_PER_SCENE) -> pd.DataFrame:
    """Category-balanced sample. `objects` must only hold row/name/category."""
    assert set(objects.columns) <= {"source_row_index", "object_name", "object_category"}, \
        "sampling must not see thermal prediction columns"
    rng = _rng(seed, scene_id)
    usable = objects[objects["object_category"] != ""]
    groups: dict[str, list[tuple[int, str]]] = {}
    for r in usable.itertuples(index=False):
        groups.setdefault(r.object_category, []).append((int(r.source_row_index), r.object_name))

    categories = sorted(groups)
    rng.shuffle(categories)
    first_cats = categories[:n]  # >n categories: a random n are covered

    picks: list[dict] = []
    for cat in first_cats:
        row, name = rng.choice(groups[cat])
        picks.append(dict(source_row_index=row, object_name=name, object_category=cat, sampling_pass=1))

    remaining = n - len(picks)
    if remaining > 0:
        def eligible(cat):
            chosen = {p["source_row_index"] for p in picks if p["object_category"] == cat}
            chosen_names = {p["object_name"] for p in picks if p["object_category"] == cat}
            pool = [(r, nm) for r, nm in groups[cat] if r not in chosen]
            if config.SECOND_INSTANCE_REQUIRE_DISTINCT_NAME:
                pool = [(r, nm) for r, nm in pool if nm not in chosen_names]
            return pool
        repeated = [c for c in first_cats if eligible(c)]
        tiebreak = {c: rng.random() for c in repeated}
        repeated.sort(key=lambda c: (-len(groups[c]), tiebreak[c]))  # most-repeated first
        for cat in repeated[:remaining]:
            row, name = rng.choice(eligible(cat))
            picks.append(dict(source_row_index=row, object_name=name, object_category=cat, sampling_pass=2))

    out = pd.DataFrame(picks)
    out.insert(0, "scene_id", scene_id)
    out.insert(1, "object_id", [make_object_id(scene_id, r) for r in out["source_row_index"]])
    out["category_size"] = [len(groups[c]) for c in out["object_category"]]
    out["sampling_seed"] = seed
    out["included"] = 1
    return out.sort_values(["sampling_pass", "source_row_index"]).reset_index(drop=True)


def generate_manifest(checks, seed: str = config.SAMPLING_SEED, data_root: Path | None = None) -> pd.DataFrame:
    """Draft manifest for every available scene (checks from validation.run_preflight)."""
    frames = []
    for chk in checks:
        if not chk.available or chk.objects is None:
            continue
        df = sample_scene(chk.objects, chk.scene_id, seed)
        index = dl.build_object_image_index(chk.scene_id, chk.objects, data_root)
        paths = []
        for r in df["source_row_index"]:
            imgs = index.by_row.get(int(r), {})
            first = (imgs.get("iso") or imgs.get("context") or [None])[0]
            paths.append(dl.rel_to_data_root(first, data_root))
        df["object_image_path"] = paths
        df["source_csv_sha256"] = chk.csv_sha256
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=MANIFEST_COLUMNS)
    return pd.concat(frames, ignore_index=True)[MANIFEST_COLUMNS]


def manifest_exists(path: Path | None = None) -> bool:
    return (path or config.MANIFEST_PATH).is_file()


def load_manifest(path: Path | None = None) -> pd.DataFrame:
    p = path or config.MANIFEST_PATH
    df = pd.read_csv(p, dtype={"scene_id": str, "object_id": str, "object_name": str,
                               "object_category": str, "object_image_path": str},
                     keep_default_na=False)
    missing = [c for c in ("scene_id", "object_id", "source_row_index", "object_name", "object_category") if c not in df]
    if missing:
        raise ValueError(f"manifest is missing column(s): {', '.join(missing)}")
    if "included" not in df:
        df["included"] = 1
    df["included"] = pd.to_numeric(df["included"], errors="coerce").fillna(0).astype(int)
    df["source_row_index"] = df["source_row_index"].astype(int)
    if df["object_id"].duplicated().any():
        raise ValueError("manifest has duplicate object_id values")
    return df


def manifest_sha256(path: Path | None = None) -> str:
    p = path or config.MANIFEST_PATH
    return dl.file_sha256(p) if p.is_file() else ""


def write_manifest(df: pd.DataFrame, path: Path | None = None, *, overwrite: bool = False) -> Path:
    p = path or config.MANIFEST_PATH
    if p.exists() and not overwrite:
        raise FileExistsError(f"{p.name} already exists; explicit overwrite required")
    tmp = p.with_suffix(".csv.tmp")
    df[MANIFEST_COLUMNS].to_csv(tmp, index=False)
    tmp.replace(p)
    return p


def validate_manifest_against_data(manifest: pd.DataFrame, checks) -> list[tuple[str, str]]:
    """Researcher warnings where manifest rows no longer match the source CSVs."""
    issues = []
    by_scene = {c.scene_id: c for c in checks}
    for scene_id, grp in manifest.groupby("scene_id"):
        chk = by_scene.get(scene_id)
        if chk is None:
            issues.append(("error", f"{scene_id}: scene is not in config.SCENES"))
            continue
        if not chk.available:
            issues.append(("warn", f"{chk.label}: scene unavailable in data — its {len(grp)} manifest objects are skipped"))
            continue
        if "source_csv_sha256" in grp and grp["source_csv_sha256"].iloc[0] and grp["source_csv_sha256"].iloc[0] != chk.csv_sha256:
            issues.append(("warn", f"{chk.label}: source CSV changed since the manifest was generated"))
        objs = chk.objects.set_index("source_row_index")
        for r in grp.itertuples(index=False):
            if r.source_row_index not in objs.index:
                issues.append(("error", f"{r.object_id}: source row {r.source_row_index} no longer exists"))
                continue
            src = objs.loc[r.source_row_index]
            if src["object_name"] != r.object_name or src["object_category"] != r.object_category:
                issues.append(("error", f"{r.object_id}: row now reads {src['object_name']!r} / {src['object_category']!r}"))
    return issues
