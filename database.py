"""SQLite storage — the canonical source of truth for study state and answers."""
from __future__ import annotations

import hashlib
import json
import random
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS study_metadata (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experts (
    expert_id             TEXT PRIMARY KEY,
    resume_token          TEXT NOT NULL UNIQUE,
    presentation_seed     TEXT NOT NULL,
    manifest_sha256       TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    submitted_at          TEXT,
    last_view             TEXT,
    last_scene_id         TEXT,
    last_object_position  INTEGER
);

CREATE TABLE IF NOT EXISTS expert_scene_order (
    expert_id     TEXT NOT NULL REFERENCES experts(expert_id),
    scene_id      TEXT NOT NULL,
    position      INTEGER NOT NULL,
    completed_at  TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (expert_id, scene_id),
    UNIQUE (expert_id, position)
);

CREATE TABLE IF NOT EXISTS expert_object_order (
    expert_id   TEXT NOT NULL,
    scene_id    TEXT NOT NULL,
    object_id   TEXT NOT NULL,
    position    INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (expert_id, object_id),
    UNIQUE (expert_id, scene_id, position),
    FOREIGN KEY (expert_id, scene_id) REFERENCES expert_scene_order(expert_id, scene_id)
);

CREATE TABLE IF NOT EXISTS scene_annotations (
    expert_id                              TEXT NOT NULL,
    scene_id                               TEXT NOT NULL,
    ambient_temperature_lower_c            REAL,
    ambient_temperature_most_likely_c      REAL,
    ambient_temperature_upper_c            REAL,
    ambient_temperature_cannot_determine   INTEGER NOT NULL DEFAULT 0,
    ambient_temperature_confidence         INTEGER CHECK (ambient_temperature_confidence IS NULL
                                                          OR ambient_temperature_confidence BETWEEN 1 AND 5),
    is_complete                            INTEGER NOT NULL DEFAULT 0,
    created_at                             TEXT NOT NULL,
    updated_at                             TEXT NOT NULL,
    PRIMARY KEY (expert_id, scene_id),
    FOREIGN KEY (expert_id, scene_id) REFERENCES expert_scene_order(expert_id, scene_id),
    CHECK (is_complete = 0 OR ambient_temperature_cannot_determine = 1 OR (
        ambient_temperature_lower_c <= ambient_temperature_most_likely_c
        AND ambient_temperature_most_likely_c <= ambient_temperature_upper_c))
);

CREATE TABLE IF NOT EXISTS object_annotations (
    expert_id                        TEXT NOT NULL,
    scene_id                         TEXT NOT NULL,
    object_id                        TEXT NOT NULL,
    source_row_index                 INTEGER NOT NULL,
    object_name                      TEXT NOT NULL,
    object_category                  TEXT NOT NULL,
    thermal_role                     TEXT,
    operating_state                  TEXT,
    surface_material                 TEXT,
    surface_material_other           TEXT,
    relative_temperature_to_ambient  TEXT,
    temperature_lower_c              REAL,
    temperature_most_likely_c        REAL,
    temperature_upper_c              REAL,
    temperature_cannot_determine     INTEGER NOT NULL DEFAULT 0,
    thermal_evolution                TEXT,
    thermal_evolution_timescale      TEXT,
    activation_question_applicable   INTEGER NOT NULL DEFAULT 0,
    activation_thermal_response      TEXT,
    activation_timescale             TEXT,
    confidence                       INTEGER CHECK (confidence IS NULL OR confidence BETWEEN 1 AND 5),
    object_label_issue               INTEGER NOT NULL DEFAULT 0,
    is_complete                      INTEGER NOT NULL DEFAULT 0,
    created_at                       TEXT NOT NULL,
    updated_at                       TEXT NOT NULL,
    completed_at                     TEXT,
    PRIMARY KEY (expert_id, object_id),
    FOREIGN KEY (expert_id, object_id) REFERENCES expert_object_order(expert_id, object_id),
    CHECK (activation_question_applicable = 1 OR
           (activation_thermal_response IS NULL AND activation_timescale IS NULL)),
    CHECK (is_complete = 0 OR temperature_cannot_determine = 1 OR (
        temperature_lower_c <= temperature_most_likely_c
        AND temperature_most_likely_c <= temperature_upper_c))
);

CREATE TABLE IF NOT EXISTS edge_annotations (
    edge_id              TEXT PRIMARY KEY,
    expert_id            TEXT NOT NULL,
    scene_id             TEXT NOT NULL,
    edge_seq             INTEGER NOT NULL,
    source_id            TEXT NOT NULL,
    source_name          TEXT NOT NULL,
    target_id            TEXT NOT NULL,
    target_name          TEXT NOT NULL,
    transfer_mechanism   TEXT NOT NULL,
    heat_flow_direction  TEXT NOT NULL,
    strength             TEXT NOT NULL,
    confidence           INTEGER NOT NULL CHECK (confidence BETWEEN 1 AND 5),
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    deleted_at           TEXT,
    UNIQUE (expert_id, scene_id, edge_seq),
    CHECK (source_id <> target_id),
    FOREIGN KEY (expert_id, scene_id) REFERENCES expert_scene_order(expert_id, scene_id)
);

CREATE TABLE IF NOT EXISTS annotation_history (
    history_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    expert_id   TEXT NOT NULL,
    entity      TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    action      TEXT NOT NULL,
    payload     TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_history_expert ON annotation_history(expert_id, entity);
"""

OBJECT_ANSWER_FIELDS = [
    "thermal_role", "operating_state", "surface_material", "surface_material_other",
    "relative_temperature_to_ambient", "temperature_lower_c", "temperature_most_likely_c",
    "temperature_upper_c", "temperature_cannot_determine", "thermal_evolution",
    "thermal_evolution_timescale", "activation_question_applicable",
    "activation_thermal_response", "activation_timescale", "confidence", "object_label_issue",
]
SCENE_ANSWER_FIELDS = [
    "ambient_temperature_lower_c", "ambient_temperature_most_likely_c", "ambient_temperature_upper_c",
    "ambient_temperature_cannot_determine", "ambient_temperature_confidence",
]

EXPERT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_expert_id(raw: str) -> str:
    eid = (raw or "").strip().upper()
    if not EXPERT_ID_RE.match(eid):
        raise ValueError("Use letters, digits, - or _ (for example E01).")
    return eid


@contextmanager
def connect(db_path: Path | None = None):
    conn = sqlite3.connect(db_path or config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA journal_mode = {config.SQLITE_JOURNAL_MODE}")
    conn.execute("PRAGMA synchronous = FULL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as c:
        c.executescript(SCHEMA)
        c.execute("INSERT OR IGNORE INTO study_metadata(key, value, updated_at) VALUES('schema_version', ?, ?)",
                  (SCHEMA_VERSION, now()))


def _log(c, expert_id, entity, entity_id, action, payload=None):
    c.execute("INSERT INTO annotation_history(expert_id, entity, entity_id, action, payload, created_at) "
              "VALUES(?,?,?,?,?,?)",
              (expert_id, entity, entity_id, action, json.dumps(payload, default=str) if payload is not None else None, now()))


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------
def get_meta(key: str, default: str | None = None, db_path=None) -> str | None:
    with connect(db_path) as c:
        row = c.execute("SELECT value FROM study_metadata WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(key: str, value: str, db_path=None) -> None:
    with connect(db_path) as c:
        c.execute("INSERT INTO study_metadata(key, value, updated_at) VALUES(?,?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                  (key, value, now()))


# ---------------------------------------------------------------------------
# experts & presentation order
# ---------------------------------------------------------------------------
def _presentation_rng(expert_id: str) -> tuple[str, random.Random]:
    seed = hashlib.sha256(f"{config.PRESENTATION_SALT}:{expert_id}".encode()).hexdigest()[:16]
    return seed, random.Random(int(seed, 16))


def get_expert(expert_id: str, db_path=None):
    with connect(db_path) as c:
        return c.execute("SELECT * FROM experts WHERE expert_id=?", (expert_id,)).fetchone()


def get_expert_by_token(token: str, db_path=None):
    if not token:
        return None
    with connect(db_path) as c:
        return c.execute("SELECT * FROM experts WHERE resume_token=?", (token,)).fetchone()


def create_expert(expert_id: str, manifest: pd.DataFrame, available_scenes: list[str],
                  manifest_hash: str, db_path=None):
    """Create an expert with a randomized, stored scene and object order.

    Returns the existing row unchanged if the expert already exists.
    """
    existing = get_expert(expert_id, db_path)
    if existing:
        return existing
    seed, rng = _presentation_rng(expert_id)
    included = manifest[manifest["included"] == 1]
    scenes = [s for s in config.SCENES if s in set(available_scenes) and s in set(included["scene_id"])]
    rng.shuffle(scenes)
    ts = now()
    with connect(db_path) as c:
        c.execute("INSERT INTO experts(expert_id, resume_token, presentation_seed, manifest_sha256, created_at, "
                  "updated_at, last_view) VALUES(?,?,?,?,?,?,?)",
                  (expert_id, secrets.token_urlsafe(16), seed, manifest_hash, ts, ts, "context"))
        for pos, s in enumerate(scenes):
            _add_scene_order(c, expert_id, s, pos, included, rng, ts)
        if scenes:
            c.execute("UPDATE experts SET last_scene_id=?, last_object_position=0 WHERE expert_id=?", (scenes[0], expert_id))
        _log(c, expert_id, "expert", expert_id, "create", {"scene_order": scenes, "seed": seed})
    return get_expert(expert_id, db_path)


def _add_scene_order(c, expert_id, scene_id, pos, included, rng, ts):
    c.execute("INSERT INTO expert_scene_order(expert_id, scene_id, position, created_at, updated_at) VALUES(?,?,?,?,?)",
              (expert_id, scene_id, pos, ts, ts))
    objs = sorted(included.loc[included["scene_id"] == scene_id, "object_id"].tolist())
    rng.shuffle(objs)
    c.executemany("INSERT INTO expert_object_order(expert_id, scene_id, object_id, position, created_at) VALUES(?,?,?,?,?)",
                  [(expert_id, scene_id, o, i, ts) for i, o in enumerate(objs)])


def add_missing_scenes(expert_id: str, manifest: pd.DataFrame, available_scenes: list[str], db_path=None) -> list[str]:
    """Append newly available scenes to an existing expert's order (never reorders)."""
    have = [r["scene_id"] for r in scene_order(expert_id, db_path=db_path, include_unavailable=True)]
    included = manifest[manifest["included"] == 1]
    new = [s for s in config.SCENES if s in set(available_scenes) and s in set(included["scene_id"]) and s not in have]
    if not new:
        return []
    exp = get_expert(expert_id, db_path)
    rng = random.Random(int(hashlib.sha256(f"{exp['presentation_seed']}:{','.join(new)}".encode()).hexdigest()[:12], 16))
    rng.shuffle(new)
    ts = now()
    with connect(db_path) as c:
        for i, s in enumerate(new):
            _add_scene_order(c, expert_id, s, len(have) + i, included, rng, ts)
        _log(c, expert_id, "expert", expert_id, "append_scenes", new)
    return new


def scene_order(expert_id: str, available: list[str] | None = None, *, include_unavailable=False, db_path=None):
    with connect(db_path) as c:
        rows = c.execute("SELECT * FROM expert_scene_order WHERE expert_id=? ORDER BY position", (expert_id,)).fetchall()
    if include_unavailable or available is None:
        return rows
    return [r for r in rows if r["scene_id"] in set(available)]


def object_order(expert_id: str, scene_id: str, manifest: pd.DataFrame, db_path=None) -> list[dict]:
    """Ordered study objects for this expert & scene, joined with the manifest."""
    with connect(db_path) as c:
        rows = c.execute("SELECT object_id, position FROM expert_object_order WHERE expert_id=? AND scene_id=? "
                         "ORDER BY position", (expert_id, scene_id)).fetchall()
    man = manifest.set_index("object_id")
    out = []
    for r in rows:
        if r["object_id"] not in man.index:
            continue  # removed from manifest after the expert started
        m = man.loc[r["object_id"]]
        if int(m["included"]) != 1:
            continue
        out.append(dict(object_id=r["object_id"], position=r["position"], scene_id=scene_id,
                        source_row_index=int(m["source_row_index"]), object_name=m["object_name"],
                        object_category=m["object_category"],
                        object_image_path=str(m.get("object_image_path", "") or "")))
    return out


def set_location(expert_id: str, view: str, scene_id: str | None, object_position: int | None = None, db_path=None):
    with connect(db_path) as c:
        c.execute("UPDATE experts SET last_view=?, last_scene_id=?, last_object_position=?, updated_at=? WHERE expert_id=?",
                  (view, scene_id, object_position, now(), expert_id))


def submit_session(expert_id: str, db_path=None):
    with connect(db_path) as c:
        c.execute("UPDATE experts SET submitted_at=?, updated_at=? WHERE expert_id=?", (now(), now(), expert_id))
        _log(c, expert_id, "expert", expert_id, "submit")


def unlock_session(expert_id: str, db_path=None):
    with connect(db_path) as c:
        c.execute("UPDATE experts SET submitted_at=NULL, updated_at=? WHERE expert_id=?", (now(), expert_id))
        _log(c, expert_id, "expert", expert_id, "unlock")


def set_scene_completed(expert_id: str, scene_id: str, completed: bool, db_path=None):
    with connect(db_path) as c:
        c.execute("UPDATE expert_scene_order SET completed_at=?, updated_at=? WHERE expert_id=? AND scene_id=?",
                  (now() if completed else None, now(), expert_id, scene_id))
        _log(c, expert_id, "scene", scene_id, "complete" if completed else "reopen")


# ---------------------------------------------------------------------------
# scene annotations
# ---------------------------------------------------------------------------
def get_scene_annotation(expert_id: str, scene_id: str, db_path=None) -> dict | None:
    with connect(db_path) as c:
        r = c.execute("SELECT * FROM scene_annotations WHERE expert_id=? AND scene_id=?", (expert_id, scene_id)).fetchone()
    return dict(r) if r else None


def save_scene_annotation(expert_id: str, scene_id: str, values: dict, is_complete: bool, db_path=None):
    vals = {k: values.get(k) for k in SCENE_ANSWER_FIELDS}
    vals["ambient_temperature_cannot_determine"] = int(bool(vals["ambient_temperature_cannot_determine"]))
    if vals["ambient_temperature_cannot_determine"]:
        for k in ("ambient_temperature_lower_c", "ambient_temperature_most_likely_c", "ambient_temperature_upper_c"):
            vals[k] = None
    ts = now()
    cols = ", ".join(SCENE_ANSWER_FIELDS)
    qs = ", ".join("?" for _ in SCENE_ANSWER_FIELDS)
    upd = ", ".join(f"{k}=excluded.{k}" for k in SCENE_ANSWER_FIELDS)
    with connect(db_path) as c:
        c.execute(f"INSERT INTO scene_annotations(expert_id, scene_id, {cols}, is_complete, created_at, updated_at) "
                  f"VALUES(?,?,{qs},?,?,?) ON CONFLICT(expert_id, scene_id) DO UPDATE SET {upd}, "
                  f"is_complete=excluded.is_complete, updated_at=excluded.updated_at",
                  (expert_id, scene_id, *[vals[k] for k in SCENE_ANSWER_FIELDS], int(is_complete), ts, ts))
        _log(c, expert_id, "scene_annotation", scene_id, "save", {**vals, "is_complete": int(is_complete)})


# ---------------------------------------------------------------------------
# object annotations
# ---------------------------------------------------------------------------
def get_object_annotation(expert_id: str, object_id: str, db_path=None) -> dict | None:
    with connect(db_path) as c:
        r = c.execute("SELECT * FROM object_annotations WHERE expert_id=? AND object_id=?", (expert_id, object_id)).fetchone()
    return dict(r) if r else None


def object_annotations_for_scene(expert_id: str, scene_id: str, db_path=None) -> dict[str, dict]:
    with connect(db_path) as c:
        rows = c.execute("SELECT * FROM object_annotations WHERE expert_id=? AND scene_id=?", (expert_id, scene_id)).fetchall()
    return {r["object_id"]: dict(r) for r in rows}


def save_object_annotation(expert_id: str, obj: dict, values: dict, is_complete: bool, db_path=None):
    """Upsert one object's answers. Non-applicable activation answers are stored as NULL."""
    vals = {k: values.get(k) for k in OBJECT_ANSWER_FIELDS}
    vals["temperature_cannot_determine"] = int(bool(vals["temperature_cannot_determine"]))
    vals["object_label_issue"] = int(bool(vals["object_label_issue"]))
    vals["activation_question_applicable"] = int(bool(vals["activation_question_applicable"]))
    if not vals["activation_question_applicable"]:
        vals["activation_thermal_response"] = None
        vals["activation_timescale"] = None
    if vals["temperature_cannot_determine"]:
        vals["temperature_lower_c"] = vals["temperature_most_likely_c"] = vals["temperature_upper_c"] = None
    if vals["surface_material"] != "Other":
        vals["surface_material_other"] = None
    if vals["confidence"] is not None:
        vals["confidence"] = int(vals["confidence"])
    ts = now()
    cols = ", ".join(OBJECT_ANSWER_FIELDS)
    qs = ", ".join("?" for _ in OBJECT_ANSWER_FIELDS)
    upd = ", ".join(f"{k}=excluded.{k}" for k in OBJECT_ANSWER_FIELDS)
    with connect(db_path) as c:
        c.execute(
            f"INSERT INTO object_annotations(expert_id, scene_id, object_id, source_row_index, object_name, "
            f"object_category, {cols}, is_complete, created_at, updated_at, completed_at) "
            f"VALUES(?,?,?,?,?,?,{qs},?,?,?,?) ON CONFLICT(expert_id, object_id) DO UPDATE SET {upd}, "
            f"is_complete=excluded.is_complete, updated_at=excluded.updated_at, "
            f"completed_at=CASE WHEN excluded.is_complete=1 THEN COALESCE(object_annotations.completed_at, excluded.updated_at) "
            f"ELSE object_annotations.completed_at END",
            (expert_id, obj["scene_id"], obj["object_id"], int(obj["source_row_index"]), obj["object_name"],
             obj["object_category"], *[vals[k] for k in OBJECT_ANSWER_FIELDS], int(is_complete), ts, ts,
             ts if is_complete else None))
        _log(c, expert_id, "object_annotation", obj["object_id"], "save", {**vals, "is_complete": int(is_complete)})


# ---------------------------------------------------------------------------
# edges
# ---------------------------------------------------------------------------
def list_edges(expert_id: str, scene_id: str, db_path=None) -> list[dict]:
    with connect(db_path) as c:
        rows = c.execute("SELECT * FROM edge_annotations WHERE expert_id=? AND scene_id=? AND deleted_at IS NULL "
                         "ORDER BY edge_seq", (expert_id, scene_id)).fetchall()
    return [dict(r) for r in rows]


def find_duplicate_edge(expert_id: str, scene_id: str, a: str, b: str, exclude_edge_id: str | None = None, db_path=None):
    for e in list_edges(expert_id, scene_id, db_path):
        if e["edge_id"] == exclude_edge_id:
            continue
        if {e["source_id"], e["target_id"]} == {a, b}:
            return e
    return None


def add_edge(expert_id: str, scene_id: str, edge: dict, db_path=None) -> str:
    if edge["source_id"] == edge["target_id"]:
        raise ValueError("Source and target must be different components.")
    if not config.ALLOW_DUPLICATE_EDGES and find_duplicate_edge(expert_id, scene_id, edge["source_id"], edge["target_id"], db_path=db_path):
        raise ValueError("This pair already has a relationship.")
    ts = now()
    with connect(db_path) as c:
        seq = c.execute("SELECT COALESCE(MAX(edge_seq), 0) + 1 FROM edge_annotations WHERE expert_id=? AND scene_id=?",
                        (expert_id, scene_id)).fetchone()[0]
        edge_id = f"{expert_id}_{scene_id}_e{seq:03d}"
        c.execute("INSERT INTO edge_annotations(edge_id, expert_id, scene_id, edge_seq, source_id, source_name, target_id, "
                  "target_name, transfer_mechanism, heat_flow_direction, strength, confidence, created_at, updated_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (edge_id, expert_id, scene_id, seq, edge["source_id"], edge["source_name"], edge["target_id"],
                   edge["target_name"], edge["transfer_mechanism"], edge["heat_flow_direction"], edge["strength"],
                   int(edge["confidence"]), ts, ts))
        _log(c, expert_id, "edge", edge_id, "create", edge)
    return edge_id


def update_edge(expert_id: str, edge_id: str, edge: dict, db_path=None):
    with connect(db_path) as c:
        row = c.execute("SELECT scene_id FROM edge_annotations WHERE edge_id=? AND expert_id=?", (edge_id, expert_id)).fetchone()
    if row is None:
        raise KeyError(edge_id)
    if edge["source_id"] == edge["target_id"]:
        raise ValueError("Source and target must be different components.")
    if not config.ALLOW_DUPLICATE_EDGES and find_duplicate_edge(expert_id, row["scene_id"], edge["source_id"], edge["target_id"], edge_id, db_path):
        raise ValueError("This pair already has a relationship.")
    with connect(db_path) as c:
        c.execute("UPDATE edge_annotations SET source_id=?, source_name=?, target_id=?, target_name=?, transfer_mechanism=?, "
                  "heat_flow_direction=?, strength=?, confidence=?, updated_at=? WHERE edge_id=? AND expert_id=?",
                  (edge["source_id"], edge["source_name"], edge["target_id"], edge["target_name"], edge["transfer_mechanism"],
                   edge["heat_flow_direction"], edge["strength"], int(edge["confidence"]), now(), edge_id, expert_id))
        _log(c, expert_id, "edge", edge_id, "update", edge)


def delete_edge(expert_id: str, edge_id: str, db_path=None):
    """Soft delete — the record and its history are kept."""
    with connect(db_path) as c:
        c.execute("UPDATE edge_annotations SET deleted_at=?, updated_at=? WHERE edge_id=? AND expert_id=?",
                  (now(), now(), edge_id, expert_id))
        _log(c, expert_id, "edge", edge_id, "delete")


def restore_edge(expert_id: str, edge_id: str, db_path=None):
    with connect(db_path) as c:
        row = c.execute("SELECT * FROM edge_annotations WHERE edge_id=? AND expert_id=?", (edge_id, expert_id)).fetchone()
    if row is None:
        return
    if not config.ALLOW_DUPLICATE_EDGES and find_duplicate_edge(expert_id, row["scene_id"], row["source_id"], row["target_id"], edge_id, db_path):
        raise ValueError("A relationship for this pair was added in the meantime.")
    with connect(db_path) as c:
        c.execute("UPDATE edge_annotations SET deleted_at=NULL, updated_at=? WHERE edge_id=? AND expert_id=?",
                  (now(), edge_id, expert_id))
        _log(c, expert_id, "edge", edge_id, "restore")


# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------
def scene_progress(expert_id: str, scene_id: str, db_path=None) -> dict:
    with connect(db_path) as c:
        n_obj = c.execute("SELECT COUNT(*) FROM expert_object_order WHERE expert_id=? AND scene_id=?", (expert_id, scene_id)).fetchone()[0]
        n_done = c.execute("SELECT COUNT(*) FROM object_annotations WHERE expert_id=? AND scene_id=? AND is_complete=1",
                           (expert_id, scene_id)).fetchone()[0]
        n_edges = c.execute("SELECT COUNT(*) FROM edge_annotations WHERE expert_id=? AND scene_id=? AND deleted_at IS NULL",
                            (expert_id, scene_id)).fetchone()[0]
        ctx = c.execute("SELECT is_complete, updated_at FROM scene_annotations WHERE expert_id=? AND scene_id=?", (expert_id, scene_id)).fetchone()
        so = c.execute("SELECT completed_at, updated_at FROM expert_scene_order WHERE expert_id=? AND scene_id=?", (expert_id, scene_id)).fetchone()
        last = c.execute("SELECT MAX(created_at) FROM annotation_history WHERE expert_id=? AND "
                         "((entity='scene_annotation' AND entity_id=?) OR (entity='object_annotation' AND entity_id LIKE ? ESCAPE '\\') "
                         "OR (entity='edge' AND entity_id LIKE ? ESCAPE '\\') OR (entity='scene' AND entity_id=?))",
                         (expert_id, scene_id, f"{scene_id}\\_%", f"{expert_id}\\_{scene_id}\\_e%", scene_id)).fetchone()[0]
    return dict(objects_total=n_obj, objects_done=n_done, edges=n_edges,
                context_done=bool(ctx and ctx["is_complete"]),
                completed=bool(so and so["completed_at"]), last_edited=last)


def overview(db_path=None) -> pd.DataFrame:
    with connect(db_path) as c:
        df = pd.read_sql_query(
            """
            SELECT e.expert_id, e.created_at, e.submitted_at, so.position + 1 AS scene_position, so.scene_id,
                   so.completed_at AS scene_completed_at,
                   COALESCE(sa.is_complete, 0) AS ambient_complete,
                   (SELECT COUNT(*) FROM expert_object_order oo WHERE oo.expert_id=e.expert_id AND oo.scene_id=so.scene_id) AS objects_total,
                   (SELECT COUNT(*) FROM object_annotations oa WHERE oa.expert_id=e.expert_id AND oa.scene_id=so.scene_id AND oa.is_complete=1) AS objects_complete,
                   (SELECT COUNT(*) FROM edge_annotations ea WHERE ea.expert_id=e.expert_id AND ea.scene_id=so.scene_id AND ea.deleted_at IS NULL) AS edges
            FROM experts e
            JOIN expert_scene_order so ON so.expert_id = e.expert_id
            LEFT JOIN scene_annotations sa ON sa.expert_id = e.expert_id AND sa.scene_id = so.scene_id
            ORDER BY e.expert_id, so.position
            """, c)
    return df


def count_annotations(db_path=None) -> int:
    with connect(db_path) as c:
        return c.execute("SELECT (SELECT COUNT(*) FROM object_annotations) + (SELECT COUNT(*) FROM scene_annotations) "
                         "+ (SELECT COUNT(*) FROM edge_annotations)").fetchone()[0]
