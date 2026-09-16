"""Step 2 of each scene: annotate the study objects one at a time."""
from __future__ import annotations

import streamlit as st

import config
import database as db
import study
import validation as val
from views import common as ui

# widget key suffix -> database field
FIELDS = {
    "role": "thermal_role", "state": "operating_state", "mat": "surface_material",
    "mat_other": "surface_material_other", "rel": "relative_temperature_to_ambient",
    "lo": "temperature_lower_c", "ml": "temperature_most_likely_c", "hi": "temperature_upper_c",
    "tcd": "temperature_cannot_determine", "evo": "thermal_evolution", "evots": "thermal_evolution_timescale",
    "act": "activation_thermal_response", "actts": "activation_timescale", "conf": "confidence",
    "flag": "object_label_issue",
}
BOOL_KEYS = {"tcd", "flag"}
ACT_KEYS = ("act", "actts")


def ns(eid, object_id):
    return f"obj|{eid}|{object_id}"


def _init(n: str, row: dict | None) -> None:
    """Load an object's saved answers into widget state.

    When a different object is opened (or after a browser refresh) every key is
    (re)loaded from the database, which always holds the latest autosave.
    """
    row = row or {}
    shadow = st.session_state.setdefault(f"{n}|shadow", {})
    fresh = st.session_state.get("obj_loaded") != n
    for suffix, field in FIELDS.items():
        k = f"{n}|{suffix}"
        if not fresh and not (suffix in ACT_KEYS and st.session_state.get(k) is None) and k in st.session_state:
            continue
        v = row.get(field)
        if suffix in ACT_KEYS and v is None:
            v = shadow.get(suffix)  # restore answers typed before the section was hidden
        if suffix in BOOL_KEYS:
            v = bool(v)
        elif suffix == "mat_other":
            v = v or ""
        st.session_state[k] = v
    st.session_state["obj_loaded"] = n


def collect(n: str) -> dict:
    g = st.session_state.get
    vals = {field: g(f"{n}|{suffix}") for suffix, field in FIELDS.items()}
    vals["temperature_cannot_determine"] = bool(vals["temperature_cannot_determine"])
    vals["object_label_issue"] = bool(vals["object_label_issue"])
    vals["activation_question_applicable"] = val.activation_applicable(vals["thermal_role"], vals["operating_state"])
    return vals


def autosave(eid: str, obj: dict) -> None:
    n = ns(eid, obj["object_id"])
    vals = collect(n)
    shadow = st.session_state.setdefault(f"{n}|shadow", {})
    if vals["activation_question_applicable"]:
        for s in ACT_KEYS:
            shadow[s] = st.session_state.get(f"{n}|{s}")
    complete = not val.missing_object_fields(vals)
    db.save_object_annotation(eid, obj, vals, complete)
    ui.mark_saved()


def _soft_note(vals: dict, amb: dict | None) -> str:
    rel, ml = vals["relative_temperature_to_ambient"], vals["temperature_most_likely_c"]
    if not amb or amb.get("ambient_temperature_cannot_determine") or vals["temperature_cannot_determine"] or ml is None or not rel:
        return ""
    aml = amb.get("ambient_temperature_most_likely_c")
    if aml is None:
        return ""
    if "colder" in rel and ml > aml:
        return f"You chose “{rel}”, but your most-likely value is above your ambient estimate ({ui.fmt_c(aml)} °C). Keep it if that's intended."
    if "warmer" in rel and ml < aml:
        return f"You chose “{rel}”, but your most-likely value is below your ambient estimate ({ui.fmt_c(aml)} °C). Keep it if that's intended."
    return ""


def _object_list(eid, scene_id, objs, answers, pos, reachable):
    done = sum(1 for o in objs if answers.get(o["object_id"], {}).get("is_complete"))
    with st.container(key="objlist"):
        pct = 100 * done / max(1, len(objs))
        st.markdown(f'<div class="s2t-status">Objects <b class="mono" style="color:var(--ink)">{done} / {len(objs)}</b></div>'
                    f'<div class="s2t-bar"><span style="width:{pct:.1f}%"></span></div>', unsafe_allow_html=True)
        cols = st.columns(2)
        for i, o in enumerate(objs):
            a = answers.get(o["object_id"], {})
            mark = "●" if a.get("is_complete") else ("◐" if a else "○")
            label = f"{i + 1:>2}  {mark}  {ui.cap(o['object_category'])}"
            with cols[i % 2]:
                if st.button(label, key=f"ol|{o['object_id']}", type="primary" if i == pos else "secondary",
                             disabled=i > reachable, width="stretch", help=o["object_id"]):
                    if i != pos:
                        ui.goto("objects", scene_id, i)


def _header(obj, pos, total, n, locked):
    imgs = study.object_images(obj)
    c1, c2 = st.columns([0.27, 0.73], gap="medium")
    with c1:
        if imgs["iso"]:
            ui.show_image(imgs["iso"][0])
        elif imgs["context"]:
            ui.show_image(imgs["context"][0])
        else:
            st.markdown('<div class="s2t-noimg">No object image available — use the scene views</div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="s2t-count">Object {pos + 1} of {total}</div>'
                    f'<div class="s2t-h2">{ui.esc(ui.cap(obj["object_category"]))}</div>'
                    f'<dl class="s2t-ids"><dt>Object ID</dt><dd>{ui.esc(obj["object_id"])}</dd>'
                    f'<dt>Internal name</dt><dd>{ui.esc(obj["object_name"])}</dd></dl>', unsafe_allow_html=True)
        views = imgs["iso"] + imgs["context"]
        if views:
            with st.expander(f"All object views ({len(views)})"):
                for r in range(0, len(views), 4):
                    cc = st.columns(4)
                    for j, p in enumerate(views[r:r + 4]):
                        with cc[j]:
                            ui.show_image(p, caption=p.stem.split("_")[-1])
        st.checkbox("Label doesn't match the image?", key=f"{n}|flag", on_change=autosave, args=(st.session_state["expert_id"], obj),
                    disabled=locked, help="Flags this object for the research team. Keep annotating what you see.")


def render(eid: str, scene_id: str, pos: int | None, manifest, scene_pos: int, n_scenes: int, locked: bool) -> None:
    objs = db.object_order(eid, scene_id, manifest)
    if not objs:
        st.warning("This scene has no study objects. Please contact the research team.")
        return
    answers = db.object_annotations_for_scene(eid, scene_id)
    first_open = next((i for i, o in enumerate(objs) if not answers.get(o["object_id"], {}).get("is_complete")), len(objs))
    reachable = min(first_open, len(objs) - 1)
    if pos is None:
        pos = reachable
    pos = max(0, min(pos, reachable))
    obj = objs[pos]
    n = ns(eid, obj["object_id"])
    _init(n, answers.get(obj["object_id"]))
    sa = db.get_scene_annotation(eid, scene_id)
    args = (eid, obj)

    left, right = st.columns([1.02, 1], gap="large")
    with left:
        with st.container(key="scenepane"):
            ui.scene_grid(scene_id)
            a, b = st.columns([5, 1], vertical_alignment="center")
            with a:
                ui.ambient_pill(sa)
            if b.button("Edit", key="edit_amb", type="tertiary"):
                ui.goto("context", scene_id)
            _object_list(eid, scene_id, objs, answers, pos, reachable)

    with right:
        with st.container(key="objform"):
            _header(obj, pos, len(objs), n, locked)
            vals = collect(n)
            missing = set(val.missing_object_fields(vals))
            tried = st.session_state.get(f"{n}|tried", False)
            applicable = vals["activation_question_applicable"]
            num = iter(range(1, 20))

            def q(key_suffix, field, text, options):
                ui.q_head(next(num), text, field not in missing, tried and field in missing)
                ui.pills(f"{n}|{key_suffix}", options, autosave, args, label=text)

            ui.section("Interpretation")
            q("role", "thermal_role", "What is the primary thermal role of this object in the current scene?", config.THERMAL_ROLES)
            q("state", "operating_state", "What is the object's current operating state?", config.OPERATING_STATES)
            q("mat", "surface_material", "What is the dominant material of the surface that is thermally relevant to interaction?",
              config.MATERIALS)
            if vals["surface_material"] == "Other":
                _, oc = st.columns([0.04, 0.96])
                oc.text_input("Describe the material", key=f"{n}|mat_other", on_change=autosave, args=args,
                              placeholder="Describe the material", label_visibility="collapsed")

            ui.section("Current state", "at the moment depicted in the scene — not a later equilibrium", tag="t = 0")
            q("rel", "relative_temperature_to_ambient",
              "At the moment depicted, compared with the surrounding ambient environment, this object's surface is likely:",
              config.RELATIVE_TO_AMBIENT)
            rng, aml = ui.ambient_text(sa)
            st.markdown(f'<div class="s2t-hint">Your ambient estimate for this scene: {ui.esc(rng)}, most likely {ui.esc(aml)}</div>',
                        unsafe_allow_html=True)
            ui.q_head(next(num), "At the moment depicted, what is a plausible current surface-temperature range for this object?",
                      "temperature" not in missing, tried and "temperature" in missing)
            ui.temperature_block(n, autosave, args, amb=sa, show_key=True)
            note = _soft_note(vals, sa)
            if note:
                st.markdown(f'<div class="s2t-note">{ui.esc(note)}</div>', unsafe_allow_html=True)

            ui.section("Expected evolution", "if nothing in the scene changes")
            q("evo", "thermal_evolution",
              "If the scene remains in its depicted state, how would you expect this object's surface temperature to change over time?",
              config.THERMAL_EVOLUTION)
            q("evots", "thermal_evolution_timescale", "When would a meaningful change in surface temperature likely occur?",
              config.EVOLUTION_TIMESCALE)
            if vals["thermal_evolution"] == "Remain approximately stable" and not vals["thermal_evolution_timescale"]:
                st.markdown('<div class="s2t-hint">If you expect it to stay stable, “No meaningful change expected” is usually '
                            "the matching answer.</div>", unsafe_allow_html=True)

            if applicable:
                with st.container(key="actsec"):
                    state_txt = "on standby" if vals["operating_state"] == "Standby" else "currently off"
                    ui.section("If activated", f"shown because you marked this as an {vals['thermal_role'].lower()} that is {state_txt}",
                               cls="act")
                    q("act", "activation_thermal_response",
                      "If this object were activated, what thermal change would you expect at its thermally relevant surface?",
                      config.ACTIVATION_RESPONSE)
                    q("actts", "activation_timescale",
                      "How quickly would that thermal change begin to meaningfully affect the surface temperature?",
                      config.ACTIVATION_TIMESCALE)

            ui.section("Confidence")
            q("conf", "confidence", "How confident are you in your overall assessment of this object?", config.CONFIDENCE_LEVELS)
            st.markdown('<div class="s2t-hint">1 = very uncertain · 5 = very confident</div>', unsafe_allow_html=True)

            with st.container(key="objfoot"):
                total_q = 10 if applicable else 8
                labels = [val.OBJECT_QUESTION_LABELS[m] for m in val.missing_object_fields(vals)]
                s1, s2, s3 = st.columns([2.6, 0.9, 1.2], vertical_alignment="center")
                status = (f"All {total_q} answered · ready to save" if not labels
                          else f"{total_q - len(labels)} of {total_q} answered · <b>{', '.join(labels)}</b> remaining")
                status += " <span class='muted'>· " + ("includes “If activated”" if applicable else "“If activated” not needed") + "</span>"
                s1.markdown(f'<div class="s2t-status">{status}</div><div class="s2t-keys"><kbd>Tab</kbd> move · '
                            '<kbd>1</kbd>–<kbd>9</kbd> choose within a focused question · <kbd>⌘/Ctrl</kbd><kbd>↵</kbd> save &amp; next</div>',
                            unsafe_allow_html=True)
                prev = s2.button("Previous", disabled=pos == 0, width="stretch")
                nxt = s3.button("Save & Next", type="primary", width="stretch", disabled=locked)
    ui.keyboard_shortcuts()

    if prev and pos > 0:
        if not locked:
            autosave(eid, obj)
        ui.goto("objects", scene_id, pos - 1)
    if nxt:
        vals = collect(n)
        if val.missing_object_fields(vals):
            st.session_state[f"{n}|tried"] = True
            st.rerun()
        autosave(eid, obj)
        st.session_state["toast"] = f"Saved {ui.cap(obj['object_category'])} · {obj['object_id']}"
        if pos < len(objs) - 1:
            ui.goto("objects", scene_id, pos + 1)
        else:
            ui.goto("heat", scene_id)
