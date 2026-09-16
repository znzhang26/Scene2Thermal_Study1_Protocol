"""Researcher-only utilities: preflight, duplicates, manifest, progress, export."""
from __future__ import annotations

import hmac

import pandas as pd
import streamlit as st

import config
import database as db
import export
import manifest as mf
import study
import validation as val
from views import common as ui

ICON = {val.OK: "✓", val.WARN: "⚠", val.ERROR: "✕"}
COLOR = {val.OK: "var(--ok)", val.WARN: "var(--warn)", val.ERROR: "var(--err)"}


def _auth() -> bool:
    if not config.RESEARCHER_PASSWORD:
        return True
    if st.session_state.get("researcher_ok"):
        return True
    pw = st.text_input("Researcher password", type="password")
    if pw and hmac.compare_digest(pw, config.RESEARCHER_PASSWORD):
        st.session_state["researcher_ok"] = True
        st.rerun()
    elif pw:
        st.error("Incorrect password.")
    return False


def _preflight_tab(checks):
    n_ok = sum(c.available for c in checks)
    left, right = st.columns([2.2, 1], gap="large")
    with left:
        for c in checks:
            msgs = "".join(f'<div style="color:{COLOR[l] if l != val.OK else "var(--ink-2)"}">{ui.esc(t)}</div>' for l, t in c.messages)
            status = c.status if c.available else val.ERROR
            right_txt = (f"<b>{c.n_rows}</b> source rows<br>{c.n_distinct_names} distinct names" if c.available
                         else '<b style="color:var(--err)">Skipped</b>')
            st.markdown(
                f'<div style="display:grid;grid-template-columns:24px 200px 1fr 140px;gap:10px;padding:10px 4px;'
                f'border-bottom:1px solid var(--line-2);font-size:12.5px">'
                f'<span style="color:{COLOR[status]};font-weight:600;font-size:14px">{ICON[status]}</span>'
                f'<span><b style="font-size:14px">{ui.esc(c.label)}</b><span class="s2t-sub">{ui.esc(c.folder)}</span></span>'
                f'<span>{msgs}</span><span style="text-align:right;color:var(--ink-3)">{right_txt}</span></div>',
                unsafe_allow_html=True)
    with right:
        st.metric("Available scenes", f"{n_ok} / {len(checks)}")
        st.caption(f"Data root: `{config.DATA_ROOT}`")
        allow = study.allow_partial()
        new = st.toggle("Continue with available scenes (development)", value=allow,
                        help="When off, experts cannot start unless every configured scene is available.")
        if new != allow:
            db.set_meta("allow_partial_dataset", "1" if new else "0")
            st.rerun()
        if n_ok < len(checks):
            st.warning("Some configured scenes are unavailable. Formal data collection should use a complete, frozen dataset.")
        if st.button("Re-run dataset check"):
            study.clear_caches()
            st.rerun()
        p = str(config.DB_PATH)
        if any(s in p for s in ("CloudStorage", "Google Drive", "GoogleDrive", "Dropbox", "OneDrive")):
            st.warning("The database is inside a cloud-synced folder. Avoid running the app on two computers at once; "
                       "set S2T_DB to a local path if possible.")


def _duplicates_tab(checks):
    rows = []
    for c in checks:
        if not c.available:
            continue
        rows.append(dict(scene=c.label, rows=c.n_rows, distinct_object_names=c.n_distinct_names,
                         repeated_names=c.repeated_names, rows_with_repeated_name=c.rows_with_repeated_name,
                         repeated_name_category_pairs=c.repeated_name_category,
                         names_with_multiple_categories=c.names_with_multiple_categories))
    st.markdown("Possible duplicate objects are **reported only** — no automatic deduplication is applied. "
                "Decide the duplicate rule before freezing the manifest.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    pick = st.selectbox("Inspect repeated names", [c.scene_id for c in checks if c.available and c.repeated_names],
                        format_func=study.label)
    if pick:
        chk = next(c for c in checks if c.scene_id == pick)
        o = chk.objects
        rep = o[o["object_name"].duplicated(keep=False)].sort_values(["object_name", "source_row_index"])
        st.dataframe(rep, hide_index=True, width="stretch")


def _manifest_tab(checks, state):
    man, sha, err = study.manifest()
    n_ann = db.count_annotations()
    if man is not None:
        by_scene = man[man["included"] == 1].groupby("scene_id").size().rename("study_objects").reset_index()
        st.success(f"Frozen manifest in use: `{config.MANIFEST_PATH.name}` · {len(man)} rows · sha256 {sha[:12]}…")
        st.dataframe(by_scene, hide_index=True)
        issues = mf.validate_manifest_against_data(man, checks)
        for lvl, text in issues:
            (st.error if lvl == "error" else st.warning)(text)
        if not issues:
            st.caption("Manifest rows match the current source CSVs.")
        experts_sha = {r["manifest_sha256"] for r in _experts()}
        if experts_sha and experts_sha != {sha}:
            st.warning("Some experts started with a different manifest version than the current file.")
        with st.expander("Manifest rows"):
            st.dataframe(man, hide_index=True, width="stretch")
    elif err.startswith("invalid"):
        st.error(f"study_manifest.csv could not be loaded: {err}")
    else:
        st.info("No study manifest yet. Generate a draft, review it, then write it.")

    st.markdown("#### Generate manifest")
    st.caption(f"{config.OBJECTS_PER_SCENE} objects per available scene · seed `{config.SAMPLING_SEED}` · "
               "uses only Object_category, Object_name, source row and scene.")
    if st.button("Generate preview"):
        st.session_state["manifest_preview"] = mf.generate_manifest(checks)
    prev = st.session_state.get("manifest_preview")
    if prev is not None:
        summary = prev.groupby("scene_id").agg(objects=("object_id", "size"),
                                                 first_pass=("sampling_pass", lambda s: int((s == 1).sum())),
                                                 second_pass=("sampling_pass", lambda s: int((s == 2).sum())),
                                                 with_image=("object_image_path", lambda s: int((s != "").sum())))
        st.dataframe(summary, width="stretch")
        st.dataframe(prev, hide_index=True, width="stretch", height=320)
        exists = mf.manifest_exists()
        ok = True
        if exists:
            ok = st.checkbox("Overwrite the existing study_manifest.csv")
            if n_ann:
                ok = ok and st.checkbox(f"I understand that {n_ann} saved annotation record(s) refer to the current manifest "
                                        "and experts' stored object orders will not change")
        if st.button("Write study_manifest.csv", type="primary", disabled=not ok):
            mf.write_manifest(prev, overwrite=exists)
            db.set_meta("manifest_written_at", db.now())
            db.set_meta("manifest_sha256", mf.manifest_sha256())
            st.session_state.pop("manifest_preview", None)
            study.clear_caches()
            st.success("Manifest written.")
            st.rerun()


def _experts():
    with db.connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM experts ORDER BY expert_id").fetchall()]


def _progress_tab():
    ov = db.overview()
    if ov.empty:
        st.info("No expert sessions yet.")
        return
    ov["scene"] = ov["scene_id"].map(study.label)
    st.dataframe(ov[["expert_id", "scene_position", "scene", "ambient_complete", "objects_complete", "objects_total",
                     "edges", "scene_completed_at", "submitted_at"]], hide_index=True, width="stretch")
    subs = [e["expert_id"] for e in _experts() if e["submitted_at"]]
    if subs:
        c1, c2 = st.columns([1, 2])
        who = c1.selectbox("Unlock a submitted session", subs)
        if c2.button("Unlock for editing"):
            db.unlock_session(who)
            st.success(f"{who} unlocked.")


def _export_tab():
    incl = st.checkbox("Include incomplete (draft) rows", value=False,
                       help="By default only completed scene and object annotations are exported.")
    if st.button("Export CSV files", type="primary"):
        paths = export.export_all(include_incomplete=incl)
        st.session_state["export_paths"] = {k: str(v) for k, v in paths.items()}
    paths = st.session_state.get("export_paths")
    if paths:
        st.success(f"Exported to `{config.EXPORT_DIR}`")
        for name, p in paths.items():
            df = pd.read_csv(p)
            with st.expander(f"{name}.csv · {len(df)} rows"):
                st.dataframe(df, hide_index=True, width="stretch")
                with open(p, "rb") as fh:
                    st.download_button(f"Download {name}.csv", fh.read(), file_name=f"{name}.csv", mime="text/csv",
                                       key=f"dl_{name}")


def render() -> None:
    st.markdown('<div class="s2t-researcher"><b>Researcher view</b> · experts never see this screen, file paths, '
                'predictions or diagnostics.</div>', unsafe_allow_html=True)
    st.markdown('<h2 style="font-size:20px;margin:.6rem 0 .2rem">Study dataset check</h2>', unsafe_allow_html=True)
    if not _auth():
        return
    checks = study.checks()
    state = study.state()
    tabs = st.tabs(["Dataset check", "Duplicates", "Manifest", "Progress", "Export"])
    with tabs[0]:
        _preflight_tab(checks)
    with tabs[1]:
        _duplicates_tab(checks)
    with tabs[2]:
        _manifest_tab(checks, state)
    with tabs[3]:
        _progress_tab()
    with tabs[4]:
        _export_tab()
    st.caption("Expert view: open the app without `?mode=researcher`.")
