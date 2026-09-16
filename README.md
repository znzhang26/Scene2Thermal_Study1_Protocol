# Scene2Thermal · Study 1 expert annotation tool

This is a local Streamlit app that experts use to annotate the Scene2Thermal scenes independently. **SQLite** is the source of truth for all answers and study state. CSV files are used for three things only: reading the source data, reading and writing the frozen study manifest, and exporting the results.

## Install

Python 3.11 or newer is required.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

| Who | URL |
|---|---|
| Experts | http://localhost:8501 |
| Researcher | http://localhost:8501/?mode=researcher |

To password-protect the researcher view, set `S2T_RESEARCHER_PASSWORD=...` before launching the app.

### Where things live

| What | Default | Override (env var) |
|---|---|---|
| Source data | `./data`, or else `../data` | `S2T_DATA_ROOT` |
| Study manifest | `./study_manifest.csv` | `S2T_MANIFEST` |
| Annotation database | `./annotations.db` | `S2T_DB` |
| Exports | `./exports/` | `S2T_EXPORT_DIR` |

Example: `S2T_DB=~/s2t/annotations.db streamlit run app.py`

> If the app folder is inside Google Drive, Dropbox, or OneDrive, run the app on **one computer at a time**. Better still, keep the database on a local disk by setting `S2T_DB`. The database uses SQLite's `DELETE` journal mode, which is the safest mode for synced folders.

## Researcher workflow

1. **Dataset check.** Open `?mode=researcher`. The app checks every scene in `config.SCENES` exactly as named and never substitutes a similar folder. A scene is skipped, with a warning, if any of the following is missing:
   - the scene folder
   - `postprocess_scene_scan_results.csv`
   - a readable CSV that contains `Object_name` and `Object_category`
   - at least one scene image

   Object images and `request_log.csv` are optional. The **Continue with available scenes** toggle lets experts start while some scenes are missing (for development only).
2. **Duplicates.** Repeated `Object_name` values and repeated name + category pairs are reported only. Nothing is removed automatically.
3. **Manifest.** Click **Generate preview**, review the sample, then click **Write study_manifest.csv**.
   - Sampling picks up to 15 objects per scene: one random instance per category first, then second instances from the most repeated categories.
   - A second instance must have a different `Object_name` from the first pick.
   - Sampling uses only the category, name, source row and scene. It never looks at thermal columns.
   - The seed is `config.SAMPLING_SEED`.
   - Object IDs have the form `<scene>_<source row>`, e.g. `winter_0119`, where the source row is the 0-based data row in the CSV.
   - Once the manifest file exists, the app always uses it. Overwriting it requires explicit confirmation.
4. **Progress.** Shows each expert's status per scene. You can also unlock a submitted session here.
5. **Export.** Writes these files to `exports/`:
   - `scene_annotations.csv`
   - `object_annotations.csv`
   - `edge_annotations.csv`
   - `expert_sessions.csv` (the presentation orders)

   By default, only completed annotations are exported.

The same tasks are available from the command line:

```bash
python manage.py preflight
python manage.py manifest --preview
python manage.py manifest --write            # add --force to overwrite
python manage.py export                      # add --include-incomplete to include drafts
```

## Expert workflow

1. The expert enters an Expert ID and chooses **Start new session** or **Resume existing session**. Starting a new session with an existing ID is blocked, so previous answers are never overwritten.
2. The app randomizes the scene order, and the object order within each scene, once per expert and stores both in SQLite. Presentation order is separate from sampling.
3. Each scene has three steps:
   - **Thermal context:** the expert's ambient temperature range and confidence.
   - **Objects:** 8 questions per object, or 10 when the "If activated" section applies. That section appears only when the expert's *own* answers are role = active heat or cooling source **and** state = off / inactive or standby.
   - **Heat transfer:** relationships among the study objects plus the environment nodes, followed by the scene review.
4. **Final review:** the expert can reopen any scene, then submit. Submitting locks the session but deletes nothing.

Every answer is saved as soon as it changes. **Save & Next** validates the answers before moving on, including lower ≤ most likely ≤ upper for temperature ranges. The URL carries a private resume token, so a browser refresh or an app restart returns the expert to the same place.

Keyboard shortcuts: Tab moves between fields, 1–9 selects an option within the focused question, and ⌘/Ctrl + Enter runs **Save & Next**.

### Heat-transfer nodes
- **Ambient air** is always included.
- **Ground / supporting surface** is included only if no sampled object's category matches ground, terrain or floor (`config.GROUND_EQUIVALENT_PATTERN`).
- **Radiant environment / sun** is included only for the scenes in `config.RADIANT_NODE_SCENES`, which by default are desert and winter.

In `edge_annotations.csv`:
- `heat_flow_direction` is one of `source_to_target`, `target_to_source`, `approximately_balanced` or `cannot_determine`.
- Deleted edges are soft-deleted and never exported.

## Data model (SQLite)

| Table | Contents |
|---|---|
| `experts` | Resume token, presentation seed, manifest hash, last location, submission time |
| `expert_scene_order`, `expert_object_order` | The stored presentation orders |
| `scene_annotations`, `object_annotations`, `edge_annotations` | One row per observation |
| `annotation_history` | Append-only log of every save, edit, delete and submit |
| `study_metadata` | Schema version, development flags, manifest hash |

`object_annotations.csv` contains the specified columns followed by three additional ones: `object_label_issue`, `presentation_index` and `is_complete`. When the activation question does not apply, `activation_question_applicable` is FALSE and the two activation fields are empty.

Option labels are stored verbatim, exactly as they appear in the UI.

## Tests

```bash
pytest -q        # unit and acceptance tests on a synthetic dataset (no real data needed)
```

`tests/e2e_browser.py` is a Playwright walkthrough of the full expert flow. It needs a running server; see its docstring for how to run it.

## Configuration

Everything configurable is in `config.py`: scenes and labels, sampling seed, objects per scene, pinned scene-image runs (`SCENE_IMAGE_RUN`), environment-node rules, and answer options.

The thermal prediction columns listed in `HIDDEN_PREDICTION_COLUMNS` are never read. The CSV reader loads only `Object_name` and `Object_category`, and from `request_log.csv` only the request side is parsed (object name and image paths).
