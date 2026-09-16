"""Render smoke tests with Streamlit's AppTest."""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

import config
import database as db
import manifest as mf
import validation as val

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _ensure_manifest():
    db.init_db()
    if not mf.manifest_exists():
        mf.write_manifest(mf.generate_manifest(val.run_preflight()))


def test_start_page_renders():
    _ensure_manifest()
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("three scenes" in m.value for m in at.markdown)


def test_researcher_page_renders_without_leaking_to_expert():
    _ensure_manifest()
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["mode"] = "researcher"
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Configured folder not found" in text


def test_expert_pages_never_show_predictions():
    _ensure_manifest()
    man = mf.load_manifest()
    av = [c.scene_id for c in val.run_preflight() if c.available]
    e = db.create_expert("SMOKE1", man, av, mf.manifest_sha256())
    for view in ("context", "objects"):
        db.set_location("SMOKE1", view, db.scene_order("SMOKE1", av)[0]["scene_id"], 0)
        db.save_scene_annotation("SMOKE1", db.scene_order("SMOKE1", av)[0]["scene_id"],
                                 dict(ambient_temperature_cannot_determine=True, ambient_temperature_confidence=2), True)
        at = AppTest.from_file(APP, default_timeout=30)
        at.query_params["s"] = e["resume_token"]
        at.run()
        assert not at.exception, at.exception
        blob = " ".join(str(x.value) for x in at.markdown) + " ".join(str(b.label) for b in at.button)
        for col in config.HIDDEN_PREDICTION_COLUMNS + ["123.4", "99.9", "steel"]:
            assert col not in blob
