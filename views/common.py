"""Shared UI pieces: styling, app bar, scene images, temperature entry."""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import config
import database as db
import study
import validation as val

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
:root{
  --ground:#F5F6F7; --surface:#FFFFFF; --sunken:#EEF0F2;
  --ink:#1A1D21; --ink-2:#4A515A; --ink-3:#7A828C;
  --line:#DCE0E4; --line-2:#E8EBEE;
  --accent:#2750B8; --accent-tint:#EBF0FB; --accent-line:#9DB2E6;
  --warn:#A8660B; --warn-tint:#FDF4E6; --err:#B4380F; --ok:#2F7A4B; --amb:#B9C0C8; --img-bg:#2E3136;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;
}
.stApp, .stApp p, .stApp button, .stApp input, .stApp label, .stApp li, .stApp h1, .stApp h2, .stApp h3 { font-family:"IBM Plex Sans",-apple-system,"Segoe UI",Roboto,sans-serif; }
.stApp [data-testid="stIconMaterial"]{font-family:"Material Symbols Rounded" !important}
.stApp p{font-size:14px}
.stApp [data-testid="stMarkdownContainer"]{margin-bottom:0 !important}
.stApp [data-testid="stMarkdownContainer"] p:last-child{margin-bottom:0}
div[data-testid="stButtonGroup"]{width:100%}
div[data-testid="stButtonGroup"] [role="radiogroup"]{flex-wrap:wrap}
[data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"]{display:none !important}
.block-container{padding-top:1rem !important; padding-bottom:2rem !important; max-width:1480px;}
header[data-testid="stHeader"]{background:transparent; height:2rem;}
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"]{display:none;}
.mono{font-family:var(--mono); font-variant-numeric:tabular-nums;}
.muted{color:var(--ink-3);}
div[data-testid="stVerticalBlock"]{gap:0.55rem;}

/* app bar */
.s2t-appbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 24px;padding:8px 2px 10px;border-bottom:1px solid var(--line);margin-bottom:2px}
.s2t-brand{font-weight:600;white-space:nowrap} .s2t-brand span{font-weight:400;color:var(--ink-3)}
.s2t-steps{display:flex;gap:4px;flex:1;min-width:0;flex-wrap:wrap}
.s2t-step{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--ink-3);white-space:nowrap;padding:3px 8px 3px 6px;border-radius:3px}
.s2t-step i{width:16px;height:16px;border-radius:50%;border:1px solid var(--line);display:grid;place-items:center;font-style:normal;font-size:10px;font-family:var(--mono)}
.s2t-step.done i{background:var(--ink-3);border-color:var(--ink-3);color:#fff}
.s2t-step.cur{color:var(--ink);background:var(--accent-tint)}
.s2t-step.cur i{border-color:var(--accent);color:var(--accent);font-weight:600}
.s2t-who{display:flex;gap:14px;align-items:center;font-size:12px;color:var(--ink-3);white-space:nowrap}
.s2t-saved::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--ok);margin-right:6px;vertical-align:1px}

/* sub navigation (buttons) */
.st-key-subnav{border-bottom:1px solid var(--line); padding-bottom:2px}
.st-key-subnav button{border:0 !important;background:transparent !important;border-radius:0 !important;border-bottom:2px solid transparent !important;color:var(--ink-3) !important;min-height:0;padding:4px 10px}
.st-key-subnav button[kind="primary"], .st-key-subnav button[data-testid="stBaseButton-primary"]{color:var(--ink) !important;border-bottom-color:var(--accent) !important}
.s2t-scn{font-weight:600}

/* scene pane */
.st-key-scenepane{position:sticky; top:2.2rem; z-index:1}
.st-key-scenegrid{background:var(--img-bg);padding:4px;border-radius:4px;gap:4px}
.st-key-scenegrid [data-testid="stImage"] img{border-radius:1px}
.st-key-scenegrid div[data-testid="stHorizontalBlock"]{gap:4px}
.s2t-h1{font-size:18px;font-weight:600;margin:0}
.s2t-meta{font-size:12px;color:var(--ink-3)}
.s2t-amb{display:flex;align-items:center;gap:12px;flex-wrap:wrap;border:1px solid var(--line);background:var(--surface);border-radius:4px;padding:7px 10px;font-size:12.5px}
.s2t-amb .lab{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-3)}
.s2t-amb b{font-family:var(--mono);font-weight:500}
.st-key-objlist{border:1px solid var(--line);border-radius:4px;background:var(--surface);padding:8px 10px}
.st-key-objlist button{justify-content:flex-start !important;text-align:left;min-height:0 !important;padding:3px 8px !important;border-color:transparent !important;font-size:12.5px}
.st-key-objlist button p{font-size:12.5px}
.st-key-objlist div[data-testid="stHorizontalBlock"]{gap:2px}
.st-key-objlist div[data-testid="stVerticalBlock"]{gap:1px}
.s2t-bar{height:4px;background:var(--sunken);border-radius:2px;overflow:hidden;margin:4px 0 6px}
.s2t-bar span{display:block;height:100%;background:var(--accent)}

/* form */
.st-key-objform, .st-key-panel{background:var(--surface);border:1px solid var(--line);border-radius:4px;padding:14px 16px 0}
.s2t-count{font-size:12px;color:var(--ink-3)}
.s2t-h2{font-size:21px;font-weight:600;margin:1px 0 4px}
.s2t-ids{display:grid;grid-template-columns:auto 1fr;gap:1px 10px;font-size:12px;margin:0}
.s2t-ids dt{color:var(--ink-3)} .s2t-ids dd{margin:0;font-family:var(--mono);color:var(--ink-2)}
.s2t-noimg{aspect-ratio:1;background:var(--img-bg);border-radius:3px;display:grid;place-items:center;color:#aaa;font-size:11px;text-align:center;padding:8px}
.s2t-sec{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin:14px 0 0;padding-top:10px;border-top:1px solid var(--line)}
.s2t-sec .h{font-size:11px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-2)}
.s2t-sec.act .h{color:var(--accent)}
.s2t-sec .t0{font:500 11px var(--mono);color:var(--accent);border:1px solid var(--accent-line);border-radius:2px;padding:0 5px}
.s2t-sec .s{font-size:12px;color:var(--ink-3)}
.s2t-q{display:flex;gap:8px;align-items:flex-start;font-weight:500;font-size:13.5px;margin:8px 0 -2px;line-height:1.35}
.s2t-q .mk{flex:none;width:14px;height:14px;border-radius:50%;border:1.5px solid var(--line);margin-top:3px;display:grid;place-items:center}
.s2t-q.ok .mk{background:var(--accent);border-color:var(--accent)}
.s2t-q.ok .mk::after{content:"";width:5px;height:3px;border:solid #fff;border-width:0 0 1.5px 1.5px;transform:rotate(-45deg) translate(0,-1px)}
.s2t-q.miss .mk{border-color:var(--warn)}
.s2t-q small{font-weight:400;color:var(--warn);font-size:12px;margin-left:6px}
.s2t-hint{font-size:12px;color:var(--ink-3);margin:-2px 0 0 22px}
.s2t-note{font-size:12px;color:var(--ink-2);background:var(--sunken);border-radius:3px;padding:4px 8px;margin-left:22px;display:inline-block}
.s2t-err{font-size:12px;color:var(--err);margin-left:22px}
.st-key-actsec{background:color-mix(in srgb,var(--accent-tint) 35%,transparent);border-radius:3px;padding:0 8px 8px}
div[data-testid="stButtonGroup"] > label[data-testid="stWidgetLabel"]{display:none}
.st-key-objform div[data-testid="stButtonGroup"], .st-key-panel .st-key-ctxq div[data-testid="stButtonGroup"]{margin-left:22px;width:calc(100% - 22px)}
.st-key-objlist button > div{justify-content:flex-start;width:100%}
.st-key-objlist button p{text-align:left}
.st-key-objlist button[data-testid="stBaseButton-primary"]{background:var(--accent-tint) !important;color:var(--ink) !important;border-color:var(--accent-line) !important}
.st-key-objlist button[data-testid="stBaseButton-secondary"]{background:transparent !important}
.st-key-edgetable p{font-size:13px}
.st-key-edgetable button{padding:1px 8px !important;min-height:0 !important}
.st-key-edgetable button p{font-size:12px;white-space:nowrap}
div[class*="st-key-tempopts"]{gap:6px;align-items:center}
div[class*="st-key-tempopts"] button{padding:1px 8px !important;min-height:0 !important}
div[class*="st-key-tempopts"] button p{font-family:var(--mono);font-size:12px}
.s2t-gap{height:6px}
.s2t-net svg{max-width:300px}
div[class*="st-key-tempopts"] [data-testid="stCheckbox"]{margin-left:18px}
div[data-testid="stButtonGroup"] button{border-radius:3px !important}
.st-key-objform div[data-testid="stNumberInput"] input{font-family:var(--mono)}
.st-key-objfoot, .st-key-ctxfoot{position:sticky;bottom:0;z-index:5;background:var(--surface);border-top:1px solid var(--line);padding:10px 0 12px;margin-top:10px}
.s2t-status{font-size:12.5px;color:var(--ink-2)}
.s2t-status b{font-weight:500;color:var(--warn)}
.s2t-keys{font-size:11px;color:var(--ink-3)}
.s2t-keys kbd{font:10px var(--mono);border:1px solid var(--line);border-radius:2px;padding:0 3px;background:var(--sunken)}

/* temperature scale */
.s2t-scale{position:relative;height:36px;margin:0 4px 0 26px}
.s2t-scale .axis{position:absolute;left:0;right:0;top:10px;height:4px;background:var(--line);border-radius:2px}
.s2t-scale .amb{position:absolute;top:6px;height:12px;background:repeating-linear-gradient(135deg,var(--amb) 0 2px,transparent 2px 5px);border:1px solid var(--amb);border-radius:2px}
.s2t-scale .band{position:absolute;top:8px;height:8px;background:var(--accent-line);border-radius:2px}
.s2t-scale .dot{position:absolute;top:5px;width:3px;height:14px;background:var(--accent);margin-left:-1.5px}
.s2t-scale .tick{position:absolute;top:19px;font:10px var(--mono);color:var(--ink-3);transform:translateX(-50%);white-space:nowrap}
.s2t-scale .tick::before{content:"";position:absolute;left:50%;top:-6px;width:1px;height:5px;background:var(--ink-3)}
.s2t-key{font-size:11px;color:var(--ink-3);display:flex;gap:14px;margin-left:26px}
.s2t-key i{display:inline-block;width:18px;height:8px;margin-right:5px}
.s2t-key .k1{background:var(--accent-line)}
.s2t-key .k2{background:repeating-linear-gradient(135deg,var(--amb) 0 2px,transparent 2px 5px);border:1px solid var(--amb)}

/* tables & misc */
.s2t-th{font-size:11px;font-weight:500;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.s2t-sub{display:block;font-size:11px;color:var(--ink-3);font-family:var(--mono)}
.s2t-tag{font-size:12px;border:1px solid var(--line);border-radius:2px;padding:1px 6px;color:var(--ink-2)}
.s2t-eyebrow{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-3)}
.s2t-panel-h h2{font-size:16px;font-weight:600;margin:2px 0 0}
.s2t-panel-h p{margin:4px 0 0;color:var(--ink-2);font-size:12.5px;max-width:78ch}
.s2t-pill{font-size:12px;padding:1px 8px;border-radius:10px;border:1px solid currentColor}
.s2t-pill.ok{color:var(--ok)} .s2t-pill.wip{color:var(--warn)} .s2t-pill.todo{color:var(--ink-3)}
.s2t-researcher{border:1px dashed var(--ink-3);border-radius:4px;padding:6px 10px;font-size:12px;color:var(--ink-2)}
.s2t-researcher b{letter-spacing:.05em;text-transform:uppercase;font-size:11px}
.s2t-row{border-bottom:1px solid var(--line-2);padding:4px 0}
</style>
"""

KEYS_JS = """
<script>
(function(){
  const doc = window.parent.document;
  if (doc.__s2tKeys) return; doc.__s2tKeys = true;
  const KEYS = '123456789abcdef';
  doc.addEventListener('keydown', function(e){
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      const b = Array.from(doc.querySelectorAll('button')).find(x => x.innerText.trim().startsWith('Save & Next') && !x.disabled);
      if (b) { e.preventDefault(); b.click(); }
      return;
    }
    const a = doc.activeElement;
    if (!a || e.metaKey || e.ctrlKey || e.altKey) return;
    const group = a.closest && a.closest('[data-testid="stButtonGroup"]');
    if (!group) return;
    const i = KEYS.indexOf(e.key.toLowerCase());
    const btns = group.querySelectorAll('button');
    if (i >= 0 && i < btns.length) { e.preventDefault(); btns[i].click(); }
  }, true);
})();
</script>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def keyboard_shortcuts() -> None:
    components.html(KEYS_JS, height=0)


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def fmt_c(v) -> str:
    if v is None:
        return "—"
    s = f"{float(v):g}"
    return s.replace("-", "−")


def cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def show_image(path: Path | str, **kw) -> None:
    try:
        st.image(str(path), width="stretch", **kw)
    except TypeError:
        st.image(str(path), use_container_width=True, **kw)
    except Exception:
        st.markdown('<div class="s2t-noimg">Image could not be displayed</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# navigation
# ---------------------------------------------------------------------------
def nav() -> dict:
    return st.session_state.setdefault("nav", {})


def goto(view: str, scene_id: str | None = None, pos: int | None = None, *, rerun: bool = True) -> None:
    n = nav()
    st.session_state.pop("obj_loaded", None)  # force answers to reload from the database
    st.session_state.pop("ctx_loaded", None)
    n["view"] = view
    if scene_id is not None:
        n["scene_id"] = scene_id
    n["pos"] = pos  # None = let the view choose (objects: first unfinished)
    eid = st.session_state.get("expert_id")
    if eid:
        db.set_location(eid, view, n.get("scene_id"), n.get("pos"))
    if rerun:
        st.rerun()


def mark_saved() -> None:
    st.session_state["saved_at"] = db.now()


def appbar(expert_id: str, order: list, current_scene: str | None) -> None:
    steps = []
    for i, r in enumerate(order):
        sid = r["scene_id"]
        cls = "cur" if sid == current_scene else ("done" if r["completed_at"] else "")
        mark = "✓" if (r["completed_at"] and sid != current_scene) else str(i + 1)
        steps.append(f'<div class="s2t-step {cls}"><i>{mark}</i><span>{esc(study.label(sid))}</span></div>')
    saved = "Saved" if st.session_state.get("saved_at") else "Progress is saved automatically"
    st.markdown(
        f'<div class="s2t-appbar"><div class="s2t-brand">Scene2Thermal <span>· Study 1</span></div>'
        f'<div class="s2t-steps">{"".join(steps)}</div>'
        f'<div class="s2t-who"><span class="s2t-saved">{saved}</span><span class="mono">{esc(expert_id)}</span></div></div>',
        unsafe_allow_html=True)


def subnav(scene_id: str, view: str, progress: dict, can_objects: bool, can_heat: bool, can_review: bool = False) -> None:
    with st.container(key="subnav"):
        c = st.columns([0.9, 1.3, 1.3, 1.3, 2.8, 1.2], vertical_alignment="center")
        if can_review and c[5].button("Final review →", key="sn_review"):
            goto("review")
        c[0].markdown(f'<div class="s2t-scn">{esc(study.label(scene_id))}</div>', unsafe_allow_html=True)
        ctx_lbl = ("✓ " if progress["context_done"] else "") + "Thermal context"
        obj_lbl = ("✓ " if progress["objects_done"] == progress["objects_total"] and progress["objects_total"] else "") + \
            f"Objects {progress['objects_done']} / {progress['objects_total']}"
        if c[1].button(ctx_lbl, key="sn_ctx", type="primary" if view == "context" else "secondary"):
            goto("context", scene_id)
        if c[2].button(obj_lbl, key="sn_obj", type="primary" if view == "objects" else "secondary", disabled=not can_objects):
            goto("objects", scene_id, None)
        if c[3].button("Heat transfer", key="sn_heat", type="primary" if view == "heat" else "secondary", disabled=not can_heat):
            goto("heat", scene_id)


def scene_grid(scene_id: str, key: str = "scenegrid") -> None:
    imgs = study.scene_images(scene_id)
    with st.container(key=key):
        for row in range(0, len(imgs), 2):
            cols = st.columns(2)
            for j, p in enumerate(imgs[row:row + 2]):
                with cols[j]:
                    show_image(p)


def ambient_text(sa: dict | None) -> tuple[str, str]:
    if not sa:
        return "not entered", "—"
    if sa.get("ambient_temperature_cannot_determine"):
        return "Cannot determine", "—"
    lo, ml, hi = (sa.get(k) for k in ("ambient_temperature_lower_c", "ambient_temperature_most_likely_c", "ambient_temperature_upper_c"))
    rng = f"{fmt_c(lo)} to {fmt_c(hi)} °C" if lo is not None and hi is not None else "incomplete"
    return rng, (f"{fmt_c(ml)} °C" if ml is not None else "—")


def ambient_pill(sa: dict | None) -> None:
    rng, ml = ambient_text(sa)
    st.markdown(f'<div class="s2t-amb"><span class="lab">Your ambient estimate</span>'
                f'<span><b>{esc(rng)}</b> · most likely <b>{esc(ml)}</b></span></div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# questions
# ---------------------------------------------------------------------------
def q_head(num, text: str, answered: bool, missing: bool) -> None:
    cls = "ok" if answered else ("miss" if missing else "")
    extra = "<small>Answer required</small>" if missing else ""
    st.markdown(f'<div class="s2t-q {cls}"><span class="mk"></span><span>{num}. {esc(text)}{extra}</span></div>',
                unsafe_allow_html=True)


def section(title: str, sub: str = "", tag: str = "", cls: str = "") -> None:
    st.markdown(f'<div class="s2t-sec {cls}"><span class="h">{esc(title)}</span>'
                + (f'<span class="t0">{esc(tag)}</span>' if tag else "")
                + (f'<span class="s">{esc(sub)}</span>' if sub else "") + "</div>", unsafe_allow_html=True)


def pills(key: str, options: list, on_change, args=(), format_func=None, label: str = "Answer") -> None:
    kw = {"format_func": format_func} if format_func else {}
    st.pills(label, options, selection_mode="single", key=key, on_change=on_change, args=args,
             label_visibility="collapsed", **kw)


def scale_html(lo, ml, hi, cd: bool, amb: dict | None = None, show_key: bool = False) -> str:
    mn, mx = config.SCALE_MIN_C, config.SCALE_MAX_C

    def p(v):
        return max(0.0, min(100.0, (float(v) - mn) / (mx - mn) * 100))

    h = '<div class="s2t-scale"><div class="axis"></div>'
    if amb and not amb.get("ambient_temperature_cannot_determine"):
        alo, ahi = amb.get("ambient_temperature_lower_c"), amb.get("ambient_temperature_upper_c")
        if alo is not None and ahi is not None and alo <= ahi:
            h += f'<div class="amb" style="left:{p(alo):.2f}%;width:{max(0.6, p(ahi) - p(alo)):.2f}%"></div>'
    h += "".join(f'<span class="tick" style="left:{p(v):.2f}%">{esc(t)}</span>' for v, t in config.SCALE_TICKS)
    if not cd:
        if lo is not None and hi is not None and lo <= hi:
            h += f'<div class="band" style="left:{p(lo):.2f}%;width:{max(0.6, p(hi) - p(lo)):.2f}%"></div>'
        if ml is not None:
            h += f'<div class="dot" style="left:{p(ml):.2f}%"></div>'
    h += "</div>"
    if show_key:
        h += '<div class="s2t-key"><span><i class="k1"></i>this object</span><span><i class="k2"></i>your ambient estimate</span></div>'
    return h


def temperature_block(prefix: str, on_change, args=(), amb: dict | None = None, show_key: bool = False) -> str:
    """Lower / most likely / upper inputs + spread buttons + cannot-determine.

    Keys: {prefix}|lo, |ml, |hi, |tcd. Returns the validation error ('' if none).
    """
    lo_k, ml_k, hi_k, cd_k = (f"{prefix}|{s}" for s in ("lo", "ml", "hi", "tcd"))
    cd = bool(st.session_state.get(cd_k))

    def spread(d):
        ml = st.session_state.get(ml_k)
        if ml is None:
            st.session_state[f"{prefix}|msg"] = "Enter the most likely value first."
            return
        st.session_state[lo_k] = round(ml - d, 2)
        st.session_state[hi_k] = round(ml + d, 2)
        on_change(*args)

    cols = st.columns([0.06, 1, 1, 1], vertical_alignment="bottom")
    common = dict(value=None, step=0.5, format="%.1f", disabled=cd, on_change=on_change, args=args)
    cols[1].number_input("Lower bound (°C)", key=lo_k, **common)
    cols[2].number_input("Most likely (°C)", key=ml_k, **common)
    cols[3].number_input("Upper bound (°C)", key=hi_k, **common)
    _, row = st.columns([0.06, 3.9])
    with row:
        with st.container(key=f"tempopts_{prefix.replace('|', '_')}", horizontal=True):
            st.markdown('<span class="s2t-status">Bounds ±</span>', unsafe_allow_html=True)
            for d in (1, 3, 10):
                st.button(str(d), key=f"{prefix}|sp{d}", on_click=spread, args=(d,), disabled=cd,
                          help=f"Set lower/upper to most likely ± {d} °C")
            st.checkbox("Cannot determine", key=cd_k, on_change=on_change, args=args)

    msg = st.session_state.pop(f"{prefix}|msg", "")
    err = val.temperature_error(st.session_state.get(lo_k), st.session_state.get(ml_k), st.session_state.get(hi_k), cd)
    if err or msg:
        st.markdown(f'<div class="s2t-err">{esc(err or msg)}</div>', unsafe_allow_html=True)
    st.markdown(scale_html(st.session_state.get(lo_k), st.session_state.get(ml_k), st.session_state.get(hi_k), cd, amb, show_key),
                unsafe_allow_html=True)
    return err


def not_ready_screen() -> None:
    st.markdown('<div style="max-width:480px;margin:60px auto"><div class="s2t-eyebrow">SCENE2THERMAL · STUDY 1</div>'
                '<h3 style="margin:.2rem 0">The study is not ready yet</h3>'
                '<p class="muted">Please contact the research team.</p></div>', unsafe_allow_html=True)
