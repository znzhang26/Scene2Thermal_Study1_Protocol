"""End-to-end browser test (Playwright) for the expert workflow.

Not part of the pytest suite (needs a running server and Playwright):

    S2T_DB=/tmp/x.db S2T_MANIFEST=... streamlit run app.py --server.port 8501 &
    python tests/e2e_browser.py http://localhost:8501 /tmp/x.db

Walks one expert through a full scene and checks acceptance tests 2–10, 12.
"""
from __future__ import annotations

import sqlite3
import sys
import time

from playwright.sync_api import Page, sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501"
DB = sys.argv[2] if len(sys.argv) > 2 else "annotations.db"
SHOTS = sys.argv[3] if len(sys.argv) > 3 else "/tmp"
FORBIDDEN = ["Material_category", "Is_heat_source", "Heat_generation_rate", "Initially_on", "Heat_capacity",
             "Thermal_conductivity", "Initial_temperature", "ambient_temperature\":", "request_log", "scene_category"]
results: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)


def settle(pg: Page, extra=250):
    """Wait until Streamlit has finished rerunning (no running indicator, no stale elements)."""
    pg.wait_for_timeout(400)
    quiet = 0
    for _ in range(200):
        busy = pg.locator('[data-testid="stStatusWidget"]').count() + pg.locator('[data-stale="true"]').count()
        quiet = quiet + 1 if busy == 0 else 0
        if quiet >= 3:
            break
        pg.wait_for_timeout(100)
    pg.wait_for_timeout(extra)


def click(pg, name, exact=True):
    pg.get_by_role("button", name=name, exact=exact).first.click()
    settle(pg)


def groups(pg):
    return pg.locator('[data-testid="stButtonGroup"]')


def pick(pg, group_index, label):
    groups(pg).nth(group_index).get_by_role("radio", name=label, exact=True).click()
    settle(pg)


def fill_num(pg, label, value):
    box = pg.get_by_label(label, exact=True)
    box.fill(str(value))
    box.press("Enter")
    settle(pg)


def text(pg):
    return pg.locator("body").inner_text()


def selected(pg, group_index):
    g = groups(pg).nth(group_index)
    return [b.inner_text() for b in g.locator('[aria-checked="true"]').all()]


def answer_passive(pg):
    pick(pg, 0, "Passive thermal object")
    pick(pg, 1, "Not applicable")
    pick(pg, 2, "Wood")
    pick(pg, 3, "Approximately ambient")
    fill_num(pg, "Most likely (°C)", 20)
    pg.get_by_role("button", name="3", exact=True).click(); settle(pg)
    pick(pg, 4, "Remain approximately stable")
    pick(pg, 5, "No meaningful change expected")
    pick(pg, 6, "4")


def db_rows(sql, *a):
    c = sqlite3.connect(DB)
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    ctx.route("**/fonts.googleapis.com/**", lambda r: r.abort())
    pg = ctx.new_page()
    pg.goto(URL); settle(pg, 1500)

    # ---- start E01 ----
    box = pg.get_by_label("Expert ID")
    box.fill("e01"); box.press("Enter"); settle(pg)
    click(pg, "Start new session")
    order1 = db_rows("SELECT scene_id FROM expert_scene_order WHERE expert_id='E01' ORDER BY position")
    oorder1 = db_rows("SELECT object_id FROM expert_object_order WHERE expert_id='E01' ORDER BY scene_id, position")
    check("T2 randomized order stored", len(order1) == 5 and len(oorder1) == 75, f"scenes={[r[0] for r in order1]}")
    token = pg.url.split("s=")[-1]
    first_scene = order1[0][0]

    # ---- context ----
    body = text(pg)
    check("T1 skipped scene not shown to expert", "Cube Kitchen" not in body and "Scene 1 of 5" in body)
    click(pg, "Continue to objects")
    check("context validation blocks empty answers", "Answer required" in text(pg))
    fill_num(pg, "Lower bound (°C)", 18)
    fill_num(pg, "Most likely (°C)", 21.5)
    fill_num(pg, "Upper bound (°C)", 24)
    pick(pg, 0, "3")
    pg.screenshot(path=f"{SHOTS}/e2e_context.png", full_page=True)
    click(pg, "Continue to objects")
    sa = db_rows("SELECT ambient_temperature_lower_c, ambient_temperature_most_likely_c, ambient_temperature_upper_c, "
                 "is_complete FROM scene_annotations WHERE expert_id='E01'")
    check("ambient saved", sa == [(18.0, 21.5, 24.0, 1)], str(sa))

    # ---- object 1: passive ----
    body = text(pg)
    check("object page shows Object 1 of 15", "Object 1 of 15" in body)
    check("T8 activation hidden for unanswered/passive", "If this object were activated" not in body)
    answer_passive(pg)
    check("T8 activation hidden for passive object", "If this object were activated" not in text(pg))
    pg.screenshot(path=f"{SHOTS}/e2e_object_passive.png", full_page=True)
    click(pg, "Save & Next")
    check("save & next advances", "Object 2 of 15" in text(pg))

    # ---- object 2: temperature validation + adaptive activation ----
    fill_num(pg, "Lower bound (°C)", 30)
    fill_num(pg, "Most likely (°C)", 20)
    check("T6 ordering error shown", "Lower bound must be ≤ most likely." in text(pg))
    pick(pg, 0, "Active heat source"); pick(pg, 1, "Off / inactive")
    body = text(pg)
    check("T7 activation shown for inactive heat source", "If activated" in body and
          "If this object were activated" in body)
    pg.screenshot(path=f"{SHOTS}/e2e_object_activation.png", full_page=True)
    pick(pg, 1, "On / active")
    check("T8 activation hidden for active object", "If this object were activated" not in text(pg))
    pick(pg, 1, "Standby")
    check("T7 activation shown for standby heat source", "If activated" in text(pg))
    pick(pg, 1, "Off / inactive")
    pick(pg, 2, "Metal"); pick(pg, 3, "Approximately ambient")
    pick(pg, 4, "Remain approximately stable"); pick(pg, 5, "No meaningful change expected")
    pick(pg, 6, "Heat substantially"); pick(pg, 7, "Within tens of seconds"); pick(pg, 8, "5")
    click(pg, "Save & Next")
    check("T6 invalid range blocks save", "Object 2 of 15" in text(pg) and "Answer required" in text(pg))
    row = db_rows("SELECT is_complete FROM object_annotations WHERE expert_id='E01' ORDER BY created_at")
    check("T6 invalid range not stored as complete", row[-1][0] == 0, str(row))
    fill_num(pg, "Lower bound (°C)", 18)
    fill_num(pg, "Upper bound (°C)", 23)
    click(pg, "Save & Next")
    check("fixed range saves", "Object 3 of 15" in text(pg))
    r = db_rows("SELECT activation_question_applicable, activation_thermal_response, activation_timescale, "
                "temperature_lower_c, temperature_most_likely_c, temperature_upper_c FROM object_annotations "
                "WHERE expert_id='E01' AND is_complete=1 ORDER BY completed_at")
    check("T7 activation answers stored", r[-1] == (1, "Heat substantially", "Within tens of seconds", 18.0, 20.0, 23.0), str(r[-1]))
    check("T8 passive stored with NULL activation", r[0][:3] == (0, None, None), str(r[0]))

    # ---- object 3: partially answered, then go back ----
    pick(pg, 0, "Active cooling source")
    click(pg, "Previous")
    body = text(pg)
    check("T4 previous shows object 2", "Object 2 of 15" in body)
    check("T4 saved answers restored", selected(pg, 0) == ["Active heat source"] and selected(pg, 6) == ["Heat substantially"],
          f"{selected(pg, 0)} {selected(pg, 6)}")
    check("T4 temperature restored", pg.get_by_label("Upper bound (°C)", exact=True).input_value() in ("23.0", "23"))
    click(pg, "Save & Next")
    check("T12 partial answer (draft) restored", selected(pg, 0) == ["Active cooling source"], str(selected(pg, 0)))

    # ---- refresh + new browser context (T3, T12) ----
    pg.reload(); settle(pg, 1500)
    check("T3 refresh keeps location", "Object 3 of 15" in text(pg) and selected(pg, 0) == ["Active cooling source"])
    ctx2 = browser.new_context(viewport={"width": 1440, "height": 1000})
    pg2 = ctx2.new_page(); pg2.goto(URL); settle(pg2, 1500)
    b2 = pg2.get_by_label("Expert ID"); b2.fill("E01"); b2.press("Enter"); settle(pg2)
    check("T12 existing session detected", "Saved session found" in text(pg2))
    start_btn = pg2.get_by_role("button", name="Start new session")
    check("repeated Expert ID cannot start a new session", start_btn.is_disabled())
    click(pg2, "Resume existing session")
    check("T12 resume lands on the same object", "Object 3 of 15" in text(pg2) and selected(pg2, 0) == ["Active cooling source"])
    order2 = db_rows("SELECT scene_id FROM expert_scene_order WHERE expert_id='E01' ORDER BY position")
    check("T3 order unchanged after resume", order1 == order2)
    ctx2.close()

    # ---- finish remaining objects ----
    pick(pg, 0, "Passive thermal object")
    for i in range(3, 16):
        if i > 3:
            pass
        if "Passive thermal object" not in selected(pg, 0):
            pick(pg, 0, "Passive thermal object")
        pick(pg, 1, "Not applicable"); pick(pg, 2, "Wood"); pick(pg, 3, "Approximately ambient")
        fill_num(pg, "Most likely (°C)", 20)
        pg.get_by_role("button", name="3", exact=True).click(); settle(pg)
        pick(pg, 4, "Remain approximately stable"); pick(pg, 5, "No meaningful change expected"); pick(pg, 6, "4")
        click(pg, "Save & Next")
        if i < 15 and f"Object {i + 1} of 15" not in text(pg):
            check(f"advance from object {i}", False, "stuck"); break
    body = text(pg)
    check("reached heat transfer after 15 objects", "Which components meaningfully exchange heat" in body)
    n_done = db_rows("SELECT COUNT(*) FROM object_annotations WHERE expert_id='E01' AND is_complete=1")[0][0]
    check("15 objects complete", n_done == 15, str(n_done))

    # ---- heat transfer ----
    import os
    os.environ["S2T_DB"] = DB
    ground_like = db_rows("SELECT COUNT(*) FROM expert_object_order oo WHERE expert_id='E01' AND scene_id=?", first_scene)
    src = pg.get_by_label("Source")
    src.click(); settle(pg, 300)
    options = pg.locator('[role="option"]').all_inner_texts()
    pg.keyboard.press("Escape"); settle(pg)
    has_synthetic_ground = any(o.startswith("Ground / supporting surface") for o in options)
    print("scene", first_scene, "options:", options)
    import re
    obj_ground = any(re.search(r"\b(ground|terrain|floors?)\b", o.split(" — ")[0], re.I) for o in options)
    check("T10 synthetic ground only when no ground-like study object", has_synthetic_ground != obj_ground,
          f"synthetic={has_synthetic_ground} object={obj_ground}")

    # add (group order on this page: mechanism, strength, direction, confidence)
    pg.get_by_role("button", name="Add relationship").click(); settle(pg)
    check("edge validation", "Choose mechanism" in text(pg))
    pick(pg, 0, "Convection"); pick(pg, 1, "Moderate")
    groups(pg).nth(2).get_by_role("radio").first.click(); settle(pg)   # source -> target
    pick(pg, 3, "4")
    click(pg, "Add relationship")
    edges = db_rows("SELECT edge_id, transfer_mechanism, heat_flow_direction, strength, confidence FROM edge_annotations "
                    "WHERE expert_id='E01' AND deleted_at IS NULL")
    check("T9 edge created", len(edges) == 1 and edges[0][1:] == ("Convection", "source_to_target", "Moderate", 4), str(edges))
    # duplicate (same pair, swapped)
    pg.get_by_role("button", name="⇄").click(); settle(pg)
    pick(pg, 0, "Conduction"); pick(pg, 1, "Weak"); groups(pg).nth(2).get_by_role("radio").first.click(); settle(pg); pick(pg, 3, "2")
    click(pg, "Add relationship")
    check("duplicate edge blocked", "already in row 1" in text(pg))
    n_edges = db_rows("SELECT COUNT(*) FROM edge_annotations WHERE expert_id='E01' AND deleted_at IS NULL")[0][0]
    check("duplicate not stored", n_edges == 1)
    # edit
    pg.get_by_role("button", name="Edit", exact=True).first.click(); settle(pg)
    check("edit loads row", "Editing row 1" in text(pg) and selected(pg, 0) == ["Convection"])
    pick(pg, 1, "Strong")
    click(pg, "Update relationship")
    e2 = db_rows("SELECT strength FROM edge_annotations WHERE expert_id='E01' AND deleted_at IS NULL")
    check("T9 edge edited", e2 == [("Strong",)], str(e2))
    pg.screenshot(path=f"{SHOTS}/e2e_heat.png", full_page=True)
    # delete + undo + delete
    pg.get_by_role("button", name="Delete", exact=True).first.click(); settle(pg)
    check("T9 edge deleted", db_rows("SELECT COUNT(*) FROM edge_annotations WHERE expert_id='E01' AND deleted_at IS NULL")[0][0] == 0)
    click(pg, "Undo delete")
    check("undo restores edge", db_rows("SELECT COUNT(*) FROM edge_annotations WHERE expert_id='E01' AND deleted_at IS NULL")[0][0] == 1)
    check("soft delete keeps history", db_rows("SELECT COUNT(*) FROM annotation_history WHERE entity='edge' AND action='delete'")[0][0] == 1)

    # ---- T5: no predictions visible on any expert page ----
    html_all = pg.content()
    check("T5 no prediction fields in expert page", not any(f in html_all for f in FORBIDDEN),
          str([f for f in FORBIDDEN if f in html_all]))

    # ---- complete scene ----
    click(pg, "Complete scene & continue")
    body = text(pg)
    check("next scene opens at context", "Scene 2 of 5" in body and "Before looking at individual objects" in body)
    pg.screenshot(path=f"{SHOTS}/e2e_scene2.png", full_page=True)
    # ---- fast-forward the remaining scenes through the database API, then final review ----
    import os
    os.environ["S2T_DB"] = DB
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import database as dbm, manifest as mfm
    man = mfm.load_manifest()
    for (sid,) in order1[1:]:
        dbm.save_scene_annotation("E01", sid, dict(ambient_temperature_lower_c=18, ambient_temperature_most_likely_c=21,
                                  ambient_temperature_upper_c=24, ambient_temperature_cannot_determine=False,
                                  ambient_temperature_confidence=4), True)
        for o in dbm.object_order("E01", sid, man):
            dbm.save_object_annotation("E01", o, dict(thermal_role="Passive thermal object", operating_state="Not applicable",
                                       surface_material="Other", surface_material_other="gingerbread dough",
                                       relative_temperature_to_ambient="Approximately ambient", temperature_lower_c=19,
                                       temperature_most_likely_c=21, temperature_upper_c=23, temperature_cannot_determine=False,
                                       thermal_evolution="Remain approximately stable",
                                       thermal_evolution_timescale="No meaningful change expected",
                                       activation_question_applicable=False, activation_thermal_response="Heat slightly",
                                       confidence=3), True)
        dbm.set_scene_completed("E01", sid, True)
    dbm.set_location("E01", "review", None, None)
    ctx3 = browser.new_context(viewport={"width": 1440, "height": 1000}); pg3 = ctx3.new_page()
    pg3.route("**/fonts.googleapis.com/**", lambda r: r.abort())
    pg3.goto(f"{URL}/?s={token}"); settle(pg3, 1500)
    pg3.get_by_role("button", name="Reopen").first.click(); settle(pg3)
    check("reopen goes to scene context", "Before looking at individual objects" in text(pg3))
    click(pg3, "Final review →")
    body = text(pg3)
    check("final review lists 5 complete scenes", "5 / 5 scenes completed" in body and body.count("Complete") >= 5)
    check("final review hides unavailable scene", "Cube Kitchen" not in body)
    pg3.screenshot(path=f"{SHOTS}/e2e_review.png", full_page=True)
    pg3.get_by_text("I have reviewed my answers and want to submit").click(); settle(pg3)
    click(pg3, "Submit annotation")
    check("submission locks session", "Annotation submitted" in text(pg3))
    sub = db_rows("SELECT submitted_at FROM experts WHERE expert_id='E01'")[0][0]
    check("submitted_at stored, records kept", sub is not None and db_rows("SELECT COUNT(*) FROM object_annotations")[0][0] == 75)
    na = db_rows("SELECT COUNT(*) FROM object_annotations WHERE activation_question_applicable=0 AND activation_thermal_response IS NOT NULL")[0][0]
    check("non-applicable activation never stored", na == 0)
    ctx3.close()
    print("TOKEN", token)
    browser.close()

fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)}/{len(results)} checks passed")
sys.exit(1 if fails else 0)
