"""Scene2Thermal Study 1 — expert annotation tool.

Run:  streamlit run app.py
Researcher tools:  http://localhost:8501/?mode=researcher
"""
from __future__ import annotations

import streamlit as st

import database as db
import study
from views import common as ui
from views import expert_start, final_review, heat_transfer, object_annotation, researcher, scene_context

st.set_page_config(page_title="Scene2Thermal Study 1", page_icon="🌡️", layout="wide",
                   initial_sidebar_state="collapsed")
db.init_db()
ui.inject_css()

if msg := st.session_state.pop("toast", None):
    st.toast(msg)


def _first_open_scene(order):
    return next((r["scene_id"] for r in order if not r["completed_at"]), None)


def expert_app() -> None:
    state = study.state()
    token = st.query_params.get("s")
    exp = db.get_expert_by_token(token) if token else None
    if exp is None:
        st.session_state.pop("expert_id", None)
        if not state.ready:
            ui.not_ready_screen()
            return
        expert_start.render(state)
        return

    eid = exp["expert_id"]
    st.session_state["expert_id"] = eid
    if exp["submitted_at"]:
        final_review.render_submitted(eid)
        return
    if state.manifest is None or not state.available:
        ui.not_ready_screen()
        return

    order = db.scene_order(eid, state.available)
    if not order:
        ui.not_ready_screen()
        return
    scene_ids = [r["scene_id"] for r in order]
    first_open = _first_open_scene(order)

    nav = ui.nav()
    if not nav:  # fresh browser session: restore the stored location
        nav.update(view=exp["last_view"] or "context", scene_id=exp["last_scene_id"], pos=exp["last_object_position"])
    view, scene_id = nav.get("view"), nav.get("scene_id")

    # Guard the location: only completed scenes and the first open scene are reachable.
    reachable = {r["scene_id"] for r in order if r["completed_at"]} | ({first_open} if first_open else set())
    if view == "review":
        if first_open is not None and not any(r["completed_at"] for r in order):
            view, scene_id = "context", first_open
    elif scene_id not in scene_ids or scene_id not in reachable:
        if first_open is None:
            view, scene_id = "review", None
        else:
            view, scene_id = "context", first_open
    nav.update(view=view, scene_id=scene_id)

    ui.appbar(eid, order, scene_id if view != "review" else None)
    if view == "review":
        final_review.render(eid, order)
        return

    prog = db.scene_progress(eid, scene_id)
    can_objects = prog["context_done"] or prog["objects_done"] > 0
    can_heat = prog["objects_total"] > 0 and prog["objects_done"] == prog["objects_total"]
    if view == "objects" and not can_objects:
        view = "context"
    if view == "heat" and not can_heat:
        view = "objects" if can_objects else "context"
    nav["view"] = view
    ui.subnav(scene_id, view, prog, can_objects, can_heat, can_review=first_open is None)
    scene_pos = scene_ids.index(scene_id) + 1

    if view == "context":
        scene_context.render(eid, scene_id, scene_pos, len(order), locked=False)
    elif view == "objects":
        object_annotation.render(eid, scene_id, nav.get("pos"), state.manifest, scene_pos, len(order), locked=False)
    else:
        nxt = next((r["scene_id"] for r in order if not r["completed_at"] and r["scene_id"] != scene_id), None)
        heat_transfer.render(eid, scene_id, state.manifest, scene_pos, len(order), locked=False,
                             next_target=("context", nxt) if nxt else ("review", None))


if st.query_params.get("mode") == "researcher":
    researcher.render()
else:
    expert_app()
