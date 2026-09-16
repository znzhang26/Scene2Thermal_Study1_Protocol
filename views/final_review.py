"""Final review, submission, and the post-submission screen."""
from __future__ import annotations

import streamlit as st

import database as db
import study
from views import common as ui


def scene_status(eid: str, row) -> dict:
    p = db.scene_progress(eid, row["scene_id"])
    p["ok"] = bool(row["completed_at"]) and p["context_done"] and p["objects_total"] > 0 \
        and p["objects_done"] == p["objects_total"]
    return p


def render(eid: str, order: list) -> None:
    stats = [(r, scene_status(eid, r)) for r in order]
    n_ok = sum(1 for _, s in stats if s["ok"])
    _, mid, _ = st.columns([0.12, 1, 0.12])
    with mid:
        st.markdown(f'<div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;margin:8px 0 6px">'
                    f'<span class="s2t-h1" style="font-size:20px">Review before submitting</span>'
                    f'<span class="mono" style="color:var(--ink-2)">{n_ok} / {len(order)} scenes completed</span></div>',
                    unsafe_allow_html=True)
        with st.container(key="panel"):
            widths = [0.5, 1.2, 1.1, 1.5, 0.9, 1.1, 1.3, 0.9]
            h = st.columns(widths)
            for c, t in zip(h, ["Order", "Scene", "Status", "Ambient (your estimate)", "Objects", "Relationships", "Last edited", ""]):
                c.markdown(f'<div class="s2t-th">{t}</div>', unsafe_allow_html=True)
            for r, s in stats:
                sa = db.get_scene_annotation(eid, r["scene_id"])
                rng, _ = ui.ambient_text(sa)
                c = st.columns(widths, vertical_alignment="center")
                c[0].markdown(f'<span class="mono">{r["position"] + 1}</span>', unsafe_allow_html=True)
                c[1].markdown(ui.esc(study.label(r["scene_id"])))
                if s["ok"]:
                    pill = '<span class="s2t-pill ok">Complete</span>'
                elif r["completed_at"]:
                    pill = '<span class="s2t-pill wip">Needs attention</span>'
                elif s["context_done"] or s["objects_done"] or s["edges"]:
                    pill = '<span class="s2t-pill wip">In progress</span>'
                else:
                    pill = '<span class="s2t-pill todo">Not started</span>'
                c[2].markdown(pill, unsafe_allow_html=True)
                c[3].markdown(f'<span class="mono">{ui.esc(rng)}</span>', unsafe_allow_html=True)
                c[4].markdown(f'<span class="mono">{s["objects_done"]} / {s["objects_total"]}</span>', unsafe_allow_html=True)
                c[5].markdown(f'<span class="mono">{s["edges"]}</span>', unsafe_allow_html=True)
                last = (s["last_edited"] or "")[:16].replace("T", " ")
                c[6].markdown(f'<span class="mono muted">{ui.esc(last)}</span>', unsafe_allow_html=True)
                if c[7].button("Reopen", key=f"reopen|{r['scene_id']}", width="stretch",
                               disabled=not (r["completed_at"] or s["context_done"])):
                    ui.goto("context", r["scene_id"])
            st.markdown('<div style="border-top:1px solid var(--line);margin-top:6px"></div>', unsafe_allow_html=True)
            a, b = st.columns([3, 1], vertical_alignment="center")
            a.markdown('<div class="s2t-status" style="padding:10px 0">Reopening a scene keeps all your answers. '
                       'After you submit, your session is locked.</div>', unsafe_allow_html=True)
            confirm = a.checkbox("I have reviewed my answers and want to submit", key="confirm_submit",
                                 disabled=n_ok < len(order))
            if b.button("Submit annotation", type="primary", width="stretch", disabled=n_ok < len(order) or not confirm):
                db.submit_session(eid)
                st.rerun()
            if n_ok < len(order):
                st.caption("All scenes must be complete before submitting.")


def render_submitted(eid: str) -> None:
    _, mid, _ = st.columns([1, 1.3, 1])
    with mid:
        st.markdown(f'<div style="margin-top:60px"><div class="s2t-eyebrow">SCENE2THERMAL · STUDY 1</div>'
                    f'<h3 style="margin:.2rem 0">Annotation submitted — thank you</h3>'
                    f'<p class="muted">Your answers for <span class="mono">{ui.esc(eid)}</span> are saved and locked. '
                    'If you need to change something, please contact the research team.</p></div>', unsafe_allow_html=True)
        if st.button("Back to start"):
            st.query_params.clear()
            st.session_state.clear()
            st.rerun()
