"""Expert ID entry: start a new session or resume an existing one."""
from __future__ import annotations

import streamlit as st

import database as db
import study
from views.common import esc

NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


def _enter(expert_row, st_state) -> None:
    eid = expert_row["expert_id"]
    db.add_missing_scenes(eid, st_state.manifest, st_state.available)
    st.session_state["expert_id"] = eid
    st.query_params["s"] = expert_row["resume_token"]
    st.session_state.pop("nav", None)  # rebuilt from the stored location
    st.rerun()


def _session_summary(eid: str, st_state) -> str:
    order = db.scene_order(eid, st_state.available)
    done = sum(1 for r in order if r["completed_at"])
    exp = db.get_expert(eid)
    where = ""
    if exp["last_scene_id"]:
        p = db.scene_progress(eid, exp["last_scene_id"])
        where = f" · {study.label(exp['last_scene_id'])}: {p['objects_done']} / {p['objects_total']} objects"
    status = "submitted" if exp["submitted_at"] else f"{done} of {len(order)} scenes complete{where}"
    return f"{status} · last saved {exp['updated_at'][:16].replace('T', ' ')} UTC"


def render(st_state) -> None:
    n = len(st_state.available)
    _, mid, _ = st.columns([1, 1.25, 1])
    with mid:
        st.markdown('<div style="height:28px"></div><div class="s2t-eyebrow">SCENE2THERMAL · STUDY 1 · THERMAL SCENE INFERENCE</div>'
                    '<h2 style="margin:.1rem 0 .6rem;font-size:20px">Expert annotation</h2>', unsafe_allow_html=True)
        st.markdown(
            f"<p style='color:var(--ink-2)'>You will review {NUMBER_WORDS.get(n, n)} scenes and independently annotate their "
            "thermal properties and heat-transfer relationships. Please base your answers on the scene information shown "
            "rather than on how you think the system may have interpreted the scene.</p>"
            "<div style='font-size:12px;color:var(--ink-2)'>For each scene: "
            "<span class='s2t-tag'>Thermal context</span> › <span class='s2t-tag'>Objects</span> › "
            "<span class='s2t-tag'>Heat transfer</span> › <span class='s2t-tag'>Review</span></div>",
            unsafe_allow_html=True)

        raw = st.text_input("Expert ID", key="expert_id_input", placeholder="E01", max_chars=32)
        eid, err = None, ""
        if raw.strip():
            try:
                eid = db.normalize_expert_id(raw)
            except ValueError as exc:
                err = str(exc)
        existing = db.get_expert(eid) if eid else None

        c1, c2 = st.columns(2)
        start = c1.button("Start new session", type="primary", disabled=not eid or existing is not None, width="stretch")
        resume = c2.button("Resume existing session", disabled=existing is None, width="stretch")
        if err:
            st.error(err)
        if existing is not None:
            st.info(f"Saved session found for **{esc(eid)}** — {_session_summary(eid, st_state)}. "
                    "Resume to continue where you left off; previous answers are kept.")
        elif eid:
            st.caption(f"No saved session for {eid}. Start a new session to begin.")

        if start and eid and existing is None:
            row = db.create_expert(eid, st_state.manifest, st_state.available, st_state.manifest_sha)
            _enter(row, st_state)
        if resume and existing is not None:
            _enter(existing, st_state)

        st.markdown(
            "<div style='font-size:12px;color:var(--ink-3);border-top:1px solid var(--line);padding-top:12px;margin-top:10px;"
            "display:grid;grid-template-columns:auto 1fr;gap:3px 14px'>"
            "<span>Scene order</span><span>Fixed for your ID, and kept if you stop and resume</span>"
            "<span>Time</span><span>About 15–20 minutes per scene</span>"
            "<span>Saving</span><span>Answers are saved as you go. You can stop at any time and resume with your ID.</span></div>",
            unsafe_allow_html=True)
