"""Step 3 of each scene: heat-transfer relationships + scene review."""
from __future__ import annotations

import math

import streamlit as st

import config
import database as db
import study
from views import common as ui

DIR_TEXT = {"approximately_balanced": "Approximately balanced", "cannot_determine": "Cannot determine"}


def _k(eid, scene_id, s):
    return f"ht|{eid}|{scene_id}|{s}"


def _dir_label(code, src_short, tgt_short):
    if code == "source_to_target":
        return f"{src_short} → {tgt_short}"
    if code == "target_to_source":
        return f"{tgt_short} → {src_short}"
    return DIR_TEXT.get(code, code)


def _reset(eid, scene_id, keep_pair=True):
    for s in ("mech", "dir", "str", "conf"):
        st.session_state[_k(eid, scene_id, s)] = None
    st.session_state[_k(eid, scene_id, "edit")] = None
    if not keep_pair:
        st.session_state.pop(_k(eid, scene_id, "src"), None)
        st.session_state.pop(_k(eid, scene_id, "tgt"), None)


def _cb_swap(eid, scene_id):
    ks, kt, kd = (_k(eid, scene_id, s) for s in ("src", "tgt", "dir"))
    st.session_state[ks], st.session_state[kt] = st.session_state.get(kt), st.session_state.get(ks)
    d = st.session_state.get(kd)
    st.session_state[kd] = {"source_to_target": "target_to_source", "target_to_source": "source_to_target"}.get(d, d)


def _cb_submit(eid, scene_id, nodes):
    g = st.session_state.get
    by_id = {n["id"]: n for n in nodes}
    src, tgt = g(_k(eid, scene_id, "src")), g(_k(eid, scene_id, "tgt"))
    edge = dict(source_id=src, target_id=tgt, transfer_mechanism=g(_k(eid, scene_id, "mech")),
                heat_flow_direction=g(_k(eid, scene_id, "dir")), strength=g(_k(eid, scene_id, "str")),
                confidence=g(_k(eid, scene_id, "conf")))
    errk = _k(eid, scene_id, "err")
    if src == tgt:
        st.session_state[errk] = "Source and target must be different components."
        return
    miss = [lbl for f, lbl in (("transfer_mechanism", "mechanism"), ("heat_flow_direction", "direction"),
                               ("strength", "strength"), ("confidence", "confidence")) if edge[f] in (None, "")]
    if miss:
        st.session_state[errk] = "Choose " + ", ".join(miss) + "."
        return
    edge["source_name"], edge["target_name"] = by_id[src]["name"], by_id[tgt]["name"]
    editing = g(_k(eid, scene_id, "edit"))
    dup = db.find_duplicate_edge(eid, scene_id, src, tgt, editing)
    if dup and not config.ALLOW_DUPLICATE_EDGES:
        rows = [e["edge_id"] for e in db.list_edges(eid, scene_id)]
        st.session_state[errk] = f"This pair is already in row {rows.index(dup['edge_id']) + 1}. Edit that row instead."
        return
    try:
        if editing:
            db.update_edge(eid, editing, edge)
            st.session_state[_k(eid, scene_id, "hl")] = editing
            st.session_state["toast"] = "Relationship updated"
        else:
            st.session_state[_k(eid, scene_id, "hl")] = db.add_edge(eid, scene_id, edge)
            st.session_state["toast"] = "Relationship added"
    except ValueError as exc:
        st.session_state[errk] = str(exc)
        return
    st.session_state[errk] = ""
    _reset(eid, scene_id)
    ui.mark_saved()


def _cb_edit(eid, scene_id, e):
    for s, f in (("src", "source_id"), ("tgt", "target_id"), ("mech", "transfer_mechanism"),
                 ("dir", "heat_flow_direction"), ("str", "strength"), ("conf", "confidence")):
        st.session_state[_k(eid, scene_id, s)] = e[f]
    st.session_state[_k(eid, scene_id, "edit")] = e["edge_id"]
    st.session_state[_k(eid, scene_id, "err")] = ""


def _cb_delete(eid, scene_id, e):
    db.delete_edge(eid, e["edge_id"])
    if st.session_state.get(_k(eid, scene_id, "edit")) == e["edge_id"]:
        _reset(eid, scene_id)
    st.session_state[_k(eid, scene_id, "undo")] = e["edge_id"]
    ui.mark_saved()


def _cb_undo(eid, scene_id):
    edge_id = st.session_state.pop(_k(eid, scene_id, "undo"), None)
    if edge_id:
        try:
            db.restore_edge(eid, edge_id)
            st.session_state[_k(eid, scene_id, "hl")] = edge_id
        except ValueError as exc:
            st.session_state[_k(eid, scene_id, "err")] = str(exc)


def _network_svg(edges, nodes) -> str:
    by_id = {n["id"]: n for n in nodes}
    ids = list(dict.fromkeys([x for e in edges for x in (e["source_id"], e["target_id"])]))
    if not ids:
        return ""
    cx, cy, r = 130, 108, 72
    pos = {i: (cx + r * math.cos(-math.pi / 2 + k * 2 * math.pi / len(ids)),
               cy + r * math.sin(-math.pi / 2 + k * 2 * math.pi / len(ids))) for k, i in enumerate(ids)}
    dash = {"Conduction": "", "Convection": "6 3", "Radiation": "1.5 3", "Mixed": "8 2 2 2", config.CANNOT: "2 2"}
    width = {"Weak": 1.2, "Moderate": 2.2, "Strong": 3.4}
    out = ['<svg viewBox="0 0 260 230" width="100%" role="img" aria-label="Relationship overview">'
           '<defs><marker id="s2tah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" '
           'orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 z" fill="#4A515A"/></marker></defs>']
    for e in edges:
        a, b = pos[e["source_id"]], pos[e["target_id"]]
        if e["heat_flow_direction"] == "target_to_source":
            a, b = b, a
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1
        ux, uy = dx / L, dy / L
        arrow = 'marker-end="url(#s2tah)"' if e["heat_flow_direction"] in ("source_to_target", "target_to_source") else ""
        out.append(f'<line x1="{a[0] + ux * 9:.1f}" y1="{a[1] + uy * 9:.1f}" x2="{b[0] - ux * 11:.1f}" y2="{b[1] - uy * 11:.1f}" '
                   f'stroke="#4A515A" stroke-width="{width.get(e["strength"], 1.2)}" '
                   f'stroke-dasharray="{dash.get(e["transfer_mechanism"], "")}" fill="none" {arrow}/>')
    for i in ids:
        x, y = pos[i]
        env = by_id.get(i, {}).get("env", False)
        anchor = "end" if x < cx - 10 else ("start" if x > cx + 10 else "middle")
        ox = -11 if anchor == "end" else (11 if anchor == "start" else 0)
        oy = (-12 if y < cy else 19) if anchor == "middle" else 4
        fill, stroke = ("#FFFFFF", "#7A828C") if env else ("#2750B8", "#2750B8")
        dash_attr = 'stroke-dasharray="2 2"' if env else ""
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="{fill}" stroke="{stroke}" stroke-width="1.5" '
                   f'{dash_attr}/>'
                   f'<text x="{x + ox:.1f}" y="{y + oy:.1f}" text-anchor="{anchor}" font-size="9.5" fill="#4A515A">'
                   f'{ui.esc(by_id.get(i, {}).get("short", i))}</text>')
    out.append("</svg>")
    return "".join(out)


def render(eid: str, scene_id: str, manifest, scene_pos: int, n_scenes: int, locked: bool,
           next_target: tuple[str, str | None]) -> None:
    objs = db.object_order(eid, scene_id, manifest)
    nodes = study.components(scene_id, objs)
    by_id = {n["id"]: n for n in nodes}
    ids = [n["id"] for n in nodes]
    ks, kt = _k(eid, scene_id, "src"), _k(eid, scene_id, "tgt")
    if st.session_state.get(ks) not in by_id:
        st.session_state[ks] = objs[0]["object_id"] if objs else ids[0]
    if st.session_state.get(kt) not in by_id:
        st.session_state[kt] = ids[0]
    for s in ("mech", "dir", "str", "conf", "edit"):
        st.session_state.setdefault(_k(eid, scene_id, s), None)
    edges = db.list_edges(eid, scene_id)
    prog = db.scene_progress(eid, scene_id)
    sa = db.get_scene_annotation(eid, scene_id)

    left, right = st.columns([0.62, 1.38], gap="large")
    with left:
        with st.container(key="scenepane"):
            ui.scene_grid(scene_id)
            ui.ambient_pill(sa)
            items = "".join(
                f'<li style="display:flex;justify-content:space-between;gap:6px"><span>{ui.esc(n["short"])}</span>'
                f'<span class="mono muted" style="font-size:11px">{"env" if n["env"] else ui.esc(n["id"].rsplit("_", 1)[-1])}</span></li>'
                for n in nodes)
            n_env = sum(1 for n in nodes if n["env"])
            st.markdown(f'<div style="border:1px solid var(--line);border-radius:4px;background:var(--surface);font-size:12px">'
                        f'<div class="s2t-th" style="padding:7px 10px;border-bottom:1px solid var(--line-2)">Components · '
                        f'{len(objs)} study objects + {n_env} environment</div>'
                        f'<ul style="list-style:none;margin:0;padding:6px 10px;columns:2;column-gap:14px">{items}</ul></div>',
                        unsafe_allow_html=True)

    with right:
        with st.container(key="panel"):
            st.markdown('<div class="s2t-panel-h"><div class="s2t-eyebrow">Step 3 of 3 · Heat transfer relationships</div>'
                        '<h2>Which components meaningfully exchange heat under the current conditions?</h2>'
                        f'<p>Add only exchanges that would noticeably affect perceived or simulated temperatures over an '
                        f'interaction timescale. Choose from the {len(objs)} objects you annotated and the environment. '
                        "You don't need to list every possible radiative exchange.</p></div>", unsafe_allow_html=True)
            editing = st.session_state.get(_k(eid, scene_id, "edit"))
            fmt = lambda i: (by_id[i]["name"] if by_id[i]["env"] else f"{by_id[i]['short']} — {i}")
            c = st.columns([1, 0.16, 1], vertical_alignment="bottom")
            c[0].selectbox("Source", ids, key=ks, format_func=fmt)
            c[1].button("⇄", key=_k(eid, scene_id, "swapbtn"), on_click=_cb_swap, args=(eid, scene_id), help="Swap source and target")
            c[2].selectbox("Target", ids, key=kt, format_func=fmt)
            src_s, tgt_s = by_id[st.session_state[ks]]["short"], by_id[st.session_state[kt]]["short"]
            c1, c2 = st.columns(2)
            with c1:
                st.markdown('<div class="s2t-th">Mechanism</div>', unsafe_allow_html=True)
                st.pills("Mechanism", config.TRANSFER_MECHANISMS, key=_k(eid, scene_id, "mech"), label_visibility="collapsed")
                st.markdown('<div class="s2t-th">Strength</div>', unsafe_allow_html=True)
                st.pills("Strength", config.STRENGTHS, key=_k(eid, scene_id, "str"), label_visibility="collapsed")
            with c2:
                st.markdown('<div class="s2t-th">Net heat-flow direction</div>', unsafe_allow_html=True)
                st.pills("Direction", config.FLOW_DIRECTIONS, key=_k(eid, scene_id, "dir"), label_visibility="collapsed",
                         format_func=lambda d: _dir_label(d, src_s, tgt_s))
                st.markdown('<div class="s2t-th">Confidence (1 very uncertain – 5 very confident)</div>', unsafe_allow_html=True)
                st.pills("Confidence", config.CONFIDENCE_LEVELS, key=_k(eid, scene_id, "conf"), label_visibility="collapsed")
            a = st.columns([1.2, 0.9, 3], vertical_alignment="center")
            a[0].button("Update relationship" if editing else "Add relationship", type="primary", width="stretch",
                        on_click=_cb_submit, args=(eid, scene_id, nodes), disabled=locked)
            if editing:
                a[1].button("Cancel edit", on_click=_reset, args=(eid, scene_id), width="stretch")
            err = st.session_state.get(_k(eid, scene_id, "err"))
            note = f'<span class="s2t-err" style="margin:0">{ui.esc(err)}</span>' if err else ""
            if editing:
                rows = [e["edge_id"] for e in edges]
                note = f'<span style="color:var(--accent);font-size:12px">Editing row {rows.index(editing) + 1 if editing in rows else "?"}</span> ' + note
            a[2].markdown(note, unsafe_allow_html=True)

            if st.session_state.get(_k(eid, scene_id, "undo")):
                u = st.columns([3, 1], vertical_alignment="center")
                u[0].markdown('<span class="s2t-status">Relationship deleted.</span>', unsafe_allow_html=True)
                u[1].button("Undo delete", on_click=_cb_undo, args=(eid, scene_id), width="stretch")

            st.markdown('<div style="border-top:1px solid var(--line);margin:6px 0 0"></div>', unsafe_allow_html=True)
            with st.container(key="edgetable"):
                widths = [1.25, 1.25, 1.0, 1.6, 0.85, 0.4, 0.55, 0.7]
                h = st.columns(widths)
                for col, t in zip(h, ["Source", "Target", "Mechanism", "Net flow", "Strength", "Conf", "", ""]):
                    col.markdown(f'<div class="s2t-th">{t}</div>', unsafe_allow_html=True)
                if not edges:
                    st.markdown('<div class="muted" style="padding:12px 0">No relationships yet. Start with the exchanges that '
                                "matter most.</div>", unsafe_allow_html=True)
                hl = st.session_state.get(_k(eid, scene_id, "hl"))
                for e in edges:
                    s, t = by_id.get(e["source_id"]), by_id.get(e["target_id"])
                    s_short = s["short"] if s else e["source_name"]
                    t_short = t["short"] if t else e["target_name"]
                    row = st.columns(widths, vertical_alignment="center")
                    mark = "background:var(--accent-tint);" if e["edge_id"] in (hl, editing) else ""
                    sub = lambda n, i: "environment" if (n and n["env"]) else i
                    row[0].markdown(f'<div style="{mark}">{ui.esc(s_short)}<span class="s2t-sub">{ui.esc(sub(s, e["source_id"]))}</span></div>', unsafe_allow_html=True)
                    row[1].markdown(f'<div style="{mark}">{ui.esc(t_short)}<span class="s2t-sub">{ui.esc(sub(t, e["target_id"]))}</span></div>', unsafe_allow_html=True)
                    row[2].markdown(ui.esc(e["transfer_mechanism"]))
                    row[3].markdown(ui.esc(_dir_label(e["heat_flow_direction"], s_short, t_short)))
                    row[4].markdown(ui.esc(e["strength"]))
                    row[5].markdown(f'<span class="mono">{e["confidence"]}</span>', unsafe_allow_html=True)
                    row[6].button("Edit", key=f"ed|{e['edge_id']}", on_click=_cb_edit, args=(eid, scene_id, e), disabled=locked)
                    row[7].button("Delete", key=f"dl|{e['edge_id']}", on_click=_cb_delete, args=(eid, scene_id, e), disabled=locked)
            svg = _network_svg(edges, nodes)
            if svg:
                with st.expander("Overview (secondary — the table above is the record)", expanded=True):
                    oc = st.columns([1, 1.2], vertical_alignment="center")
                    oc[0].markdown(f'<div class="s2t-net">{svg}</div>', unsafe_allow_html=True)
                    oc[1].markdown('<div class="muted" style="font-size:12px">Solid line = conduction · dashed = convection · '
                                   'dotted = radiation · dash-dot = mixed.<br>Line weight = strength · arrow = net heat flow · '
                                   'dashed circle = environment node.</div>', unsafe_allow_html=True)

            # ---- scene review ----
            st.markdown('<div style="border-top:1px solid var(--line);margin:10px 0 0"></div>', unsafe_allow_html=True)
            rng, _ = ui.ambient_text(sa)
            ok = lambda b: '<span style="color:var(--ok)">✓</span>' if b else '<span style="color:var(--warn)">●</span>'
            all_obj = prog["objects_done"] == prog["objects_total"] and prog["objects_total"] > 0
            st.markdown(f'<div class="s2t-th">Scene review · {ui.esc(study.label(scene_id))}</div>'
                        f'<div style="display:flex;gap:6px 26px;flex-wrap:wrap;font-size:13px">'
                        f'<span>{ok(prog["context_done"])} Ambient annotation {"complete" if prog["context_done"] else "incomplete"} '
                        f'<b class="mono">{ui.esc(rng)}</b></span>'
                        f'<span>{ok(all_obj)} <b class="mono">{prog["objects_done"]} / {prog["objects_total"]}</b> objects complete</span>'
                        f'<span><b class="mono">{len(edges)}</b> heat-transfer relationships added</span></div><div class="s2t-gap"></div>',
                        unsafe_allow_html=True)
            r = st.columns([1, 1, 1.6, 1.6], vertical_alignment="center")
            if r[0].button("Review ambient", width="stretch"):
                ui.goto("context", scene_id)
            if r[1].button("Review objects", width="stretch"):
                ui.goto("objects", scene_id, 0)
            can_complete = prog["context_done"] and all_obj and not locked
            if r[3].button("Complete scene & continue", type="primary", width="stretch", disabled=not can_complete):
                db.set_scene_completed(eid, scene_id, True)
                st.session_state["toast"] = f"{study.label(scene_id)} complete"
                ui.goto(*next_target)
            if not can_complete and not locked:
                r[2].markdown('<span class="s2t-status">Finish the ambient estimate and all objects to complete this scene.</span>',
                              unsafe_allow_html=True)
