"""Acceptance-level unit tests (run: pytest -q)."""
from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

import config
import data_loader as dl
import database as db
import export
import manifest as mf
import study
import validation as val
from conftest import DATA


@pytest.fixture(scope="module")
def checks():
    return val.run_preflight()


@pytest.fixture(scope="module")
def man(checks):
    df = mf.generate_manifest(checks)
    mf.write_manifest(df, overwrite=True)
    db.init_db()
    return mf.load_manifest()


def available(checks):
    return [c.scene_id for c in checks if c.available]


# T1 ------------------------------------------------------------------------
def test_missing_or_incomplete_scenes_are_skipped(checks):
    by = {c.scene_id: c for c in checks}
    assert not by["cube_kitchen"].available
    assert "Configured folder not found" in by["cube_kitchen"].messages[0][1]
    assert not by["winter"].available and "No usable scene images" in by["winter"].messages[-1][1]
    assert not by["gingerbread"].available and "Object_category" in by["gingerbread"].messages[0][1]
    assert available(checks) == ["kitchen", "cabin", "desert"]


def test_duplicates_are_reported_not_removed(checks):
    k = next(c for c in checks if c.scene_id == "kitchen")
    assert k.n_rows == 16 and k.n_distinct_names == 14
    assert k.repeated_names == 2 and k.names_with_multiple_categories == 1
    assert any("Possible duplicate objects" in t for _, t in k.messages)
    assert len(k.objects) == 16


# T5 ------------------------------------------------------------------------
def test_prediction_columns_are_never_loaded():
    df = dl.read_scene_objects(DATA / "request_log_kitchen" / config.SCENE_CSV_NAME)
    assert list(df.columns) == ["source_row_index", "object_name", "object_category"]
    assert not any(c in df.columns for c in config.HIDDEN_PREDICTION_COLUMNS)
    assert "123.4" not in df.to_csv() and "steel" not in df.to_csv()


def test_object_image_index_ignores_responses():
    objs = dl.read_scene_objects(DATA / "request_log_kitchen" / config.SCENE_CSV_NAME)
    idx = dl.build_object_image_index("kitchen", objs)
    assert idx.matched_rows == 16
    assert idx.by_row[8]["iso"][0].name != idx.by_row[7]["iso"][0].name  # k-th duplicate -> k-th request


# sampling ------------------------------------------------------------------
def test_sampling_is_category_balanced_and_reproducible(checks, man):
    k = man[man.scene_id == "kitchen"]
    assert k.object_category.nunique() == 12                      # every category once
    second = k[k.sampling_pass == 2]
    # repeated categories: mug (3 names), chair (2 names), lamp (2 rows, same name -> not eligible)
    assert set(second.object_category) == {"mug", "chair"} and len(k) == 14
    assert second.iloc[0].object_category in {"mug", "chair"}
    assert (k.object_id == [f"kitchen_{r:04d}" for r in k.source_row_index]).all()
    again = mf.generate_manifest(checks)
    assert again.equals(mf.generate_manifest(checks))
    many = man[man.scene_id == "desert"]
    assert len(many) == 15 and many.object_category.nunique() == 15   # >15 categories -> 15 distinct
    cabin = man[man.scene_id == "cabin"]
    assert len(cabin) == 8                                         # 4 categories -> at most 2 each


def test_sampling_rejects_thermal_columns():
    bad = pd.DataFrame({"source_row_index": [0], "object_name": ["a"], "object_category": ["b"], "Initially_on": [True]})
    with pytest.raises(AssertionError):
        mf.sample_scene(bad, "x")


def test_manifest_not_overwritten_without_flag(man):
    with pytest.raises(FileExistsError):
        mf.write_manifest(man)


# T2 / T3 --------------------------------------------------------------------
def test_expert_order_is_random_stable_and_persistent(checks, man):
    av = available(checks)
    e = db.create_expert("E01", man, av, "sha")
    again = db.create_expert("E01", man, av, "sha")          # repeated ID does not overwrite
    assert e["resume_token"] == again["resume_token"]
    order = [r["scene_id"] for r in db.scene_order("E01", av)]
    assert sorted(order) == sorted(av)
    objs = [o["object_id"] for o in db.object_order("E01", "kitchen", man)]
    assert sorted(objs) == sorted(man[man.scene_id == "kitchen"].object_id)
    # a different expert gets a different (but also stored) order
    db.create_expert("E02", man, av, "sha")
    objs2 = [o["object_id"] for o in db.object_order("E02", "kitchen", man)]
    assert objs2 != objs
    # reading again (e.g. after restart) returns the identical order
    assert [o["object_id"] for o in db.object_order("E01", "kitchen", man)] == objs


# T6 ------------------------------------------------------------------------
@pytest.mark.parametrize("lo,ml,hi,cd,ok", [
    (18, 20, 22, True, True), (18, 18, 18, False, True), (20, 18, 22, False, False),
    (18, 23, 22, False, False), (None, 20, 22, False, False), (None, None, None, True, True),
    (-5.5, -2.25, 0.0, False, True),
])
def test_temperature_ordering(lo, ml, hi, cd, ok):
    assert val.temperature_complete(lo, ml, hi, cd) is ok


def test_database_rejects_complete_invalid_range(man):
    obj = db.object_order("E01", "kitchen", man)[0]
    with pytest.raises(sqlite3.IntegrityError):
        db.save_object_annotation("E01", obj, dict(temperature_lower_c=30, temperature_most_likely_c=20,
                                                   temperature_upper_c=40), True)


# T7 / T8 --------------------------------------------------------------------
@pytest.mark.parametrize("role,state,shown", [
    ("Active heat source", "Off / inactive", True), ("Active cooling source", "Standby", True),
    ("Active heat source", "On / active", False), ("Passive thermal object", "Off / inactive", False),
    ("Passive thermal object", "Not applicable", False), ("Active heat source", "Cannot determine", False),
    (None, None, False),
])
def test_activation_rule(role, state, shown):
    assert val.activation_applicable(role, state) is shown


def _full(**kw):
    a = dict(thermal_role="Passive thermal object", operating_state="Not applicable", surface_material="Wood",
             relative_temperature_to_ambient="Approximately ambient", temperature_lower_c=18,
             temperature_most_likely_c=20, temperature_upper_c=22, temperature_cannot_determine=False,
             thermal_evolution="Remain approximately stable", thermal_evolution_timescale="No meaningful change expected",
             confidence=4)
    a.update(kw)
    a["activation_question_applicable"] = val.activation_applicable(a["thermal_role"], a["operating_state"])
    return a


def test_activation_required_only_when_applicable_and_null_otherwise(man):
    a = _full(thermal_role="Active heat source", operating_state="Off / inactive")
    assert set(val.missing_object_fields(a)) == {"activation_thermal_response", "activation_timescale"}
    p = _full(activation_thermal_response="Heat slightly", activation_timescale="Within seconds")
    assert val.missing_object_fields(p) == []
    obj = db.object_order("E01", "kitchen", man)[1]
    db.save_object_annotation("E01", obj, p, True)
    row = db.get_object_annotation("E01", obj["object_id"])
    assert row["activation_question_applicable"] == 0
    assert row["activation_thermal_response"] is None and row["activation_timescale"] is None


# T9 ------------------------------------------------------------------------
def test_edge_create_edit_delete_persist(man):
    e = dict(source_id="kitchen_0000", source_name="Stove", target_id="env_ambient_air", target_name="Ambient air",
             transfer_mechanism="Convection", heat_flow_direction="source_to_target", strength="Strong", confidence=4)
    eid = db.add_edge("E01", "kitchen", e)
    with pytest.raises(ValueError):
        db.add_edge("E01", "kitchen", {**e, "source_id": "env_ambient_air", "target_id": "kitchen_0000"})
    with pytest.raises(ValueError):
        db.add_edge("E01", "kitchen", {**e, "target_id": "kitchen_0000"})
    db.update_edge("E01", eid, {**e, "strength": "Weak"})
    assert db.list_edges("E01", "kitchen")[0]["strength"] == "Weak"
    db.delete_edge("E01", eid)
    assert db.list_edges("E01", "kitchen") == []
    db.restore_edge("E01", eid)
    assert [x["edge_id"] for x in db.list_edges("E01", "kitchen")] == [eid]
    eid2 = db.add_edge("E01", "kitchen", {**e, "source_id": "kitchen_0001"})
    assert eid2 != eid  # edge ids are never reused


# T10 -----------------------------------------------------------------------
def test_synthetic_ground_hidden_when_study_has_ground_object():
    with_floor = [dict(object_id="k_1", object_category="floor", object_name="Floor", source_row_index=1)]
    no_floor = [dict(object_id="k_1", object_category="mug", object_name="m", source_row_index=1)]
    ids = lambda objs, s: [n["id"] for n in study.components(s, objs)]
    assert "env_ground" not in ids(with_floor, "kitchen")
    assert "env_ground" in ids(no_floor, "kitchen")
    assert "env_ambient_air" in ids(with_floor, "kitchen")
    assert "env_radiant" in ids(no_floor, "desert") and "env_radiant" not in ids(no_floor, "kitchen")
    terrain = [dict(object_id="d_1", object_category="terrain", object_name="floor", source_row_index=1)]
    assert "env_ground" not in ids(terrain, "desert")


# T11 -----------------------------------------------------------------------
def test_export_is_tidy(man):
    db.save_scene_annotation("E01", "kitchen", dict(ambient_temperature_lower_c=18, ambient_temperature_most_likely_c=20,
                             ambient_temperature_upper_c=22, ambient_temperature_cannot_determine=False,
                             ambient_temperature_confidence=4), True)
    paths = export.export_all()
    s = pd.read_csv(paths["scene_annotations"])
    o = pd.read_csv(paths["object_annotations"])
    e = pd.read_csv(paths["edge_annotations"])
    assert list(s.columns[:8]) == export.SCENE_COLUMNS
    assert list(o.columns[:len(export.OBJECT_COLUMNS)]) == export.OBJECT_COLUMNS
    assert list(e.columns) == export.EDGE_COLUMNS
    assert len(e) == 2 and e.edge_id.is_unique
    assert not o.duplicated(["expert_id", "object_id"]).any()
    assert not any(c in o.columns for c in config.HIDDEN_PREDICTION_COLUMNS)


# T12 -----------------------------------------------------------------------
def test_partial_answers_survive_and_resume(man):
    obj = db.object_order("E01", "kitchen", man)[2]
    db.save_object_annotation("E01", obj, dict(thermal_role="Active cooling source"), False)
    db.set_location("E01", "objects", "kitchen", 2)
    exp = db.get_expert_by_token(db.get_expert("E01")["resume_token"])
    assert (exp["last_view"], exp["last_scene_id"], exp["last_object_position"]) == ("objects", "kitchen", 2)
    row = db.get_object_annotation("E01", obj["object_id"])
    assert row["thermal_role"] == "Active cooling source" and row["is_complete"] == 0
    db.submit_session("E01")
    assert db.get_expert("E01")["submitted_at"]
    assert db.get_object_annotation("E01", obj["object_id"]) is not None  # submission keeps records


def test_expert_id_validation():
    assert db.normalize_expert_id(" e01 ") == "E01"
    with pytest.raises(ValueError):
        db.normalize_expert_id("E 01; drop")
