"""Dataset preflight checks and answer validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

import config
import data_loader as dl

OK, WARN, ERROR = "ok", "warn", "error"


@dataclass
class SceneCheck:
    scene_id: str
    label: str
    folder: str
    available: bool = False
    status: str = ERROR
    messages: list[tuple[str, str]] = field(default_factory=list)  # (level, text)
    n_rows: int = 0
    n_categories: int = 0
    n_distinct_names: int = 0
    repeated_names: int = 0              # names occurring more than once
    rows_with_repeated_name: int = 0
    repeated_name_category: int = 0      # (name, category) pairs occurring more than once
    names_with_multiple_categories: int = 0
    scene_images: list[Path] = field(default_factory=list)
    scene_image_runs: int = 0
    object_image_files: int = 0
    object_image_rows: int = 0
    has_request_log: bool = False
    csv_sha256: str = ""
    objects: pd.DataFrame | None = None

    def add(self, level: str, text: str) -> None:
        self.messages.append((level, text))


def check_scene(scene_id: str, data_root: Path | None = None) -> SceneCheck:
    root = data_root or config.DATA_ROOT
    chk = SceneCheck(scene_id, config.SCENE_LABELS.get(scene_id, scene_id), config.SCENES[scene_id])
    sdir = dl.scene_dir(scene_id, root)

    # ---- required ----
    if not sdir.is_dir():
        chk.add(ERROR, "Configured folder not found — scene skipped")
        return chk
    csv_path = sdir / config.SCENE_CSV_NAME
    if not csv_path.is_file():
        chk.add(ERROR, f"{config.SCENE_CSV_NAME} not found — scene skipped")
        return chk
    try:
        objects = dl.read_scene_objects(csv_path)
    except ValueError as exc:
        chk.add(ERROR, f"CSV {exc} — scene skipped")
        return chk
    except Exception as exc:  # unreadable / malformed
        chk.add(ERROR, f"CSV could not be read ({type(exc).__name__}) — scene skipped")
        return chk
    if objects.empty:
        chk.add(ERROR, "CSV has no object rows — scene skipped")
        return chk
    blank_cat = int((objects["object_category"] == "").sum())
    chk.objects = objects
    chk.csv_sha256 = dl.file_sha256(csv_path)
    chk.n_rows = len(objects)
    chk.n_categories = objects.loc[objects["object_category"] != "", "object_category"].nunique()
    chk.n_distinct_names = objects["object_name"].nunique()
    chk.add(OK, f"CSV loaded · {chk.n_rows} source rows · {chk.n_categories} categories")
    if blank_cat:
        chk.add(WARN, f"{blank_cat} row(s) have an empty Object_category and will not be sampled")

    images = dl.list_scene_images(scene_id, root)
    chk.scene_images = images
    if not images:
        pinned = config.SCENE_IMAGE_RUN.get(scene_id)
        chk.add(ERROR, "No usable scene images found" + (f" for pinned run {pinned}" if pinned else "") + " — scene skipped")
        return chk
    runs = {dl.image_run(p) for p in images}
    chk.scene_image_runs = len(runs)
    chk.add(OK, f"{len(images)} scene image(s)")
    if len(runs) > 1:
        chk.add(WARN, f"Scene images come from {len(runs)} scene-inference runs — all are shown. "
                      f"Pin one in config.SCENE_IMAGE_RUN before freezing.")

    # ---- duplicates (report only; no automatic decision) ----
    name_counts = objects["object_name"].value_counts()
    chk.repeated_names = int((name_counts > 1).sum())
    chk.rows_with_repeated_name = int(name_counts[name_counts > 1].sum())
    pair_counts = objects.groupby(["object_name", "object_category"]).size()
    chk.repeated_name_category = int((pair_counts > 1).sum())
    cats_per_name = objects.groupby("object_name")["object_category"].nunique()
    chk.names_with_multiple_categories = int((cats_per_name > 1).sum())
    if chk.repeated_names:
        chk.add(WARN, f"Possible duplicate objects: {chk.n_rows} rows but {chk.n_distinct_names} distinct Object_name values "
                      f"({chk.repeated_names} names repeated; {chk.repeated_name_category} repeated name+category pairs)")
    if chk.names_with_multiple_categories:
        chk.add(WARN, f"{chk.names_with_multiple_categories} Object_name value(s) appear with more than one Object_category")

    # ---- optional ----
    chk.has_request_log = (sdir / config.REQUEST_LOG_NAME).is_file()
    chk.object_image_files = dl.count_object_images(scene_id, root)
    if not chk.has_request_log:
        chk.add(WARN, "request_log.csv not found (optional) — object images unavailable")
    if chk.object_image_files == 0:
        chk.add(WARN, "No object-inference images (optional) — annotation continues without them")
    else:
        index = dl.build_object_image_index(scene_id, objects, root)
        chk.object_image_rows = index.matched_rows
        chk.add(OK, f"{chk.object_image_files} object image files · images matched for {index.matched_rows}/{chk.n_rows} rows")
        for note in index.notes:
            chk.add(WARN, note)

    chk.available = True
    chk.status = WARN if any(l == WARN for l, _ in chk.messages) else OK
    return chk


def run_preflight(data_root: Path | None = None) -> list[SceneCheck]:
    return [check_scene(s, data_root) for s in config.SCENES]


# ---------------------------------------------------------------------------
# Answer validation
# ---------------------------------------------------------------------------
def temperature_error(lower, most_likely, upper, cannot_determine: bool) -> str:
    """Return a user-facing error, or '' when the range is valid or incomplete-but-ordered."""
    if cannot_determine:
        return ""
    vals = [lower, most_likely, upper]
    for v in vals:
        if v is not None and not isinstance(v, (int, float)):
            return "Enter numbers only (decimals are fine)."
    lo, ml, hi = vals
    if lo is not None and ml is not None and lo > ml:
        return "Lower bound must be ≤ most likely."
    if ml is not None and hi is not None and ml > hi:
        return "Most likely must be ≤ upper bound."
    if lo is not None and hi is not None and lo > hi:
        return "Lower bound must be ≤ upper bound."
    return ""


def temperature_complete(lower, most_likely, upper, cannot_determine: bool) -> bool:
    if cannot_determine:
        return True
    return None not in (lower, most_likely, upper) and not temperature_error(lower, most_likely, upper, False)


def activation_applicable(role: str | None, state: str | None) -> bool:
    """Conditional activation depends only on the expert's own answers."""
    return role in config.ACTIVATION_ROLES and state in config.ACTIVATION_STATES


OBJECT_QUESTION_LABELS = {
    "thermal_role": "Role",
    "operating_state": "State",
    "surface_material": "Material",
    "relative_temperature_to_ambient": "Relative to ambient",
    "temperature": "Surface temperature",
    "thermal_evolution": "Evolution",
    "thermal_evolution_timescale": "Evolution timescale",
    "activation_thermal_response": "Activation response",
    "activation_timescale": "Activation onset",
    "confidence": "Confidence",
}


def missing_object_fields(a: dict) -> list[str]:
    """Keys (from OBJECT_QUESTION_LABELS) that still need an answer."""
    miss = []
    for k in ("thermal_role", "operating_state"):
        if not a.get(k):
            miss.append(k)
    if not a.get("surface_material") or (a.get("surface_material") == "Other" and not (a.get("surface_material_other") or "").strip()):
        miss.append("surface_material")
    if not a.get("relative_temperature_to_ambient"):
        miss.append("relative_temperature_to_ambient")
    if not temperature_complete(a.get("temperature_lower_c"), a.get("temperature_most_likely_c"),
                                a.get("temperature_upper_c"), bool(a.get("temperature_cannot_determine"))):
        miss.append("temperature")
    for k in ("thermal_evolution", "thermal_evolution_timescale"):
        if not a.get(k):
            miss.append(k)
    if activation_applicable(a.get("thermal_role"), a.get("operating_state")):
        for k in ("activation_thermal_response", "activation_timescale"):
            if not a.get(k):
                miss.append(k)
    if a.get("confidence") in (None, ""):
        miss.append("confidence")
    return miss


def scene_context_complete(a: dict) -> bool:
    return temperature_complete(a.get("ambient_temperature_lower_c"), a.get("ambient_temperature_most_likely_c"),
                                a.get("ambient_temperature_upper_c"), bool(a.get("ambient_temperature_cannot_determine"))) \
        and a.get("ambient_temperature_confidence") not in (None, "")
