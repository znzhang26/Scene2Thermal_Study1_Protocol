"""Step 1 of each scene: the expert's ambient-temperature estimate."""
from __future__ import annotations

import streamlit as st

import config
import database as db
import study
import validation as val
from views import common as ui


def _prefix(eid, scene_id):
    return f"ctx|{eid}|{scene_id}"


def _init(eid, scene_id):
    p = _prefix(eid, scene_id)
    if st.session_state.get("ctx_loaded") == p and f"{p}|lo" in st.session_state:
        return
    st.session_state["ctx_loaded"] = p
    row = db.get_scene_annotation(eid, scene_id) or {}
    st.session_state[f"{p}|lo"] = row.get("ambient_temperature_lower_c")
    st.session_state[f"{p}|ml"] = row.get("ambient_temperature_most_likely_c")
    st.session_state[f"{p}|hi"] = row.get("ambient_temperature_upper_c")
    st.session_state[f"{p}|tcd"] = bool(row.get("ambient_temperature_cannot_determine"))
    st.session_state[f"{p}|conf"] = row.get("ambient_temperature_confidence")


def collect(eid, scene_id) -> dict:
    p = _prefix(eid, scene_id)
    g = st.session_state.get
    return {
        "ambient_temperature_lower_c": g(f"{p}|lo"),
        "ambient_temperature_most_likely_c": g(f"{p}|ml"),
        "ambient_temperature_upper_c": g(f"{p}|hi"),
        "ambient_temperature_cannot_determine": bool(g(f"{p}|tcd")),
        "ambient_temperature_confidence": g(f"{p}|conf"),
    }


def autosave(eid, scene_id):
    v = collect(eid, scene_id)
    db.save_scene_annotation(eid, scene_id, v, val.scene_context_complete(v))
    ui.mark_saved()


def render(eid: str, scene_id: str, scene_pos: int, n_scenes: int, locked: bool) -> None:
    _init(eid, scene_id)
    p = _prefix(eid, scene_id)
    left, right = st.columns([1.3, 1], gap="large")
    with left:
        with st.container(key="scenepane"):
            n_img = len(study.scene_images(scene_id))
            st.markdown(f'<div><span class="s2t-h1">{ui.esc(study.label(scene_id))}</span> '
                        f'<span class="s2t-meta">Scene {scene_pos} of {n_scenes} · {n_img} views of the same scene · '
                        f'use ⤢ on a view to enlarge</span></div>', unsafe_allow_html=True)
            ui.scene_grid(scene_id)
    with right:
        with st.container(key="panel"):
            st.markdown('<div class="s2t-panel-h"><div class="s2t-eyebrow">Step 1 of 3 · Scene thermal context</div>'
                        '<h2>Before looking at individual objects</h2>'
                        "<p>Estimate the thermal conditions of the scene as a whole. Your estimate stays visible while "
                        "you annotate this scene's objects.</p></div>", unsafe_allow_html=True)
            v = collect(eid, scene_id)
            tried = st.session_state.get(f"{p}|tried", False)
            t_ok = val.temperature_complete(v["ambient_temperature_lower_c"], v["ambient_temperature_most_likely_c"],
                                            v["ambient_temperature_upper_c"], v["ambient_temperature_cannot_determine"])
            ui.q_head(1, "What is a plausible ambient-temperature range for this scene?", t_ok, tried and not t_ok)
            st.markdown('<div class="s2t-hint">Air temperature around the objects. A wide range is fine when the scene '
                        "doesn't pin it down.</div>", unsafe_allow_html=True)
            ui.temperature_block(p, autosave, (eid, scene_id))
            c_ok = v["ambient_temperature_confidence"] is not None
            ui.q_head(2, "How confident are you in this ambient estimate?", c_ok, tried and not c_ok)
            with st.container(key="ctxq"):
                ui.pills(f"{p}|conf", config.CONFIDENCE_LEVELS, autosave, (eid, scene_id), label="Confidence in ambient estimate")
            st.markdown('<div class="s2t-hint">1 = very uncertain · 5 = very confident</div>', unsafe_allow_html=True)

            with st.container(key="ctxfoot"):
                a, b = st.columns([1.3, 1], vertical_alignment="center")
                missing = [n for n, ok in (("Ambient range", t_ok), ("Confidence", c_ok)) if not ok]
                a.markdown('<div class="s2t-status">' + (
                    "Both answered · you can change these later" if not missing
                    else f"<b>{', '.join(missing)}</b> remaining") + "</div>", unsafe_allow_html=True)
                if b.button("Continue to objects", type="primary", width="stretch", disabled=locked):
                    if missing:
                        st.session_state[f"{p}|tried"] = True
                        st.rerun()
                    autosave(eid, scene_id)
                    ui.goto("objects", scene_id, None)
