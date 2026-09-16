"""Researcher-only export of analysis-ready, tidy CSV files."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import config
import database as db

SCENE_COLUMNS = [
    "expert_id", "scene_id",
    "ambient_temperature_lower_c", "ambient_temperature_most_likely_c", "ambient_temperature_upper_c",
    "ambient_temperature_cannot_determine", "ambient_temperature_confidence",
    "annotation_timestamp",
]
OBJECT_COLUMNS = [
    "expert_id", "scene_id", "object_id", "source_row_index", "object_name", "object_category",
    "thermal_role", "operating_state",
    "surface_material", "surface_material_other",
    "relative_temperature_to_ambient",
    "temperature_lower_c", "temperature_most_likely_c", "temperature_upper_c", "temperature_cannot_determine",
    "thermal_evolution", "thermal_evolution_timescale",
    "activation_question_applicable", "activation_thermal_response", "activation_timescale",
    "confidence",
    "annotation_timestamp",
]
EDGE_COLUMNS = [
    "expert_id", "scene_id", "edge_id",
    "source_id", "source_name", "target_id", "target_name",
    "transfer_mechanism", "heat_flow_direction", "strength", "confidence",
    "annotation_timestamp",
]
# Appended after the specified columns (kept last so the core schema is unchanged).
OBJECT_EXTRA = ["object_label_issue", "presentation_index", "is_complete"]
SCENE_EXTRA = ["scene_presentation_index", "is_complete"]

BOOL_COLS = ["ambient_temperature_cannot_determine", "temperature_cannot_determine",
             "activation_question_applicable", "object_label_issue", "is_complete"]


def _bools(df: pd.DataFrame) -> pd.DataFrame:
    for c in BOOL_COLS:
        if c in df:
            df[c] = df[c].map({1: True, 0: False}).astype("boolean")
    return df


def build_tables(include_incomplete: bool = False, db_path=None) -> dict[str, pd.DataFrame]:
    flt = "" if include_incomplete else "AND x.is_complete = 1"
    with db.connect(db_path) as c:
        scenes = pd.read_sql_query(f"""
            SELECT x.expert_id, x.scene_id, x.ambient_temperature_lower_c, x.ambient_temperature_most_likely_c,
                   x.ambient_temperature_upper_c, x.ambient_temperature_cannot_determine,
                   x.ambient_temperature_confidence, x.updated_at AS annotation_timestamp,
                   so.position + 1 AS scene_presentation_index, x.is_complete
            FROM scene_annotations x
            JOIN expert_scene_order so ON so.expert_id = x.expert_id AND so.scene_id = x.scene_id
            WHERE 1=1 {flt}
            ORDER BY x.expert_id, so.position""", c)
        objects = pd.read_sql_query(f"""
            SELECT x.*, x.updated_at AS annotation_timestamp, oo.position + 1 AS presentation_index
            FROM object_annotations x
            JOIN expert_object_order oo ON oo.expert_id = x.expert_id AND oo.object_id = x.object_id
            JOIN expert_scene_order so ON so.expert_id = x.expert_id AND so.scene_id = x.scene_id
            WHERE 1=1 {flt}
            ORDER BY x.expert_id, so.position, oo.position""", c)
        edges = pd.read_sql_query("""
            SELECT x.*, x.updated_at AS annotation_timestamp
            FROM edge_annotations x
            JOIN expert_scene_order so ON so.expert_id = x.expert_id AND so.scene_id = x.scene_id
            WHERE x.deleted_at IS NULL
            ORDER BY x.expert_id, so.position, x.edge_seq""", c)
        sessions = pd.read_sql_query("""
            SELECT e.expert_id, e.created_at, e.submitted_at, e.presentation_seed, e.manifest_sha256,
                   so.scene_id, so.position + 1 AS scene_presentation_index, so.completed_at AS scene_completed_at,
                   oo.object_id, oo.position + 1 AS object_presentation_index
            FROM experts e
            JOIN expert_scene_order so ON so.expert_id = e.expert_id
            JOIN expert_object_order oo ON oo.expert_id = e.expert_id AND oo.scene_id = so.scene_id
            ORDER BY e.expert_id, so.position, oo.position""", c)
    objects["confidence"] = objects["confidence"].astype("Int64")
    scenes["ambient_temperature_confidence"] = scenes["ambient_temperature_confidence"].astype("Int64")
    return {
        "scene_annotations": _bools(scenes[SCENE_COLUMNS + SCENE_EXTRA]),
        "object_annotations": _bools(objects[OBJECT_COLUMNS + OBJECT_EXTRA]),
        "edge_annotations": edges[EDGE_COLUMNS],
        "expert_sessions": sessions,
    }


def export_all(export_dir: Path | None = None, include_incomplete: bool = False, db_path=None) -> dict[str, Path]:
    out_dir = export_dir or config.EXPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, df in build_tables(include_incomplete, db_path).items():
        p = out_dir / f"{name}.csv"
        tmp = p.with_suffix(".csv.tmp")
        df.to_csv(tmp, index=False)
        tmp.replace(p)
        paths[name] = p
    return paths
