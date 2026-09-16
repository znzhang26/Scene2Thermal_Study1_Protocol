"""Builds a small synthetic Scene2Thermal dataset and points the app at it."""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="s2t_test_"))
DATA = ROOT / "data"
os.environ["S2T_DATA_ROOT"] = str(DATA)
os.environ["S2T_DB"] = str(ROOT / "annotations.db")
os.environ["S2T_MANIFEST"] = str(ROOT / "study_manifest.csv")
os.environ["S2T_EXPORT_DIR"] = str(ROOT / "exports")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HEADER = ["Object_name", "Object_category", "Material_category", "Is_heat_source", "Heat_generation_rate",
          "Initially_on", "Heat_capacity", "Thermal_conductivity", "Mass", "Initial_temperature"]
JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c"
    "20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f00000105010101010101000000"
    "00000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1"
    "082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a7374"
    "75767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1"
    "e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbd3ffd9")


def make_scene(folder: str, rows: list[tuple[str, str]], n_images: int = 4, request_log: bool = True,
               columns=HEADER):
    d = DATA / folder
    (d / "request_images" / "scene_inference").mkdir(parents=True, exist_ok=True)
    (d / "request_images" / "object_inference").mkdir(parents=True, exist_ok=True)
    with open(d / "postprocess_scene_scan_results.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(columns)
        for name, cat in rows:
            w.writerow([name, cat, "steel", "True", "2000", "True", "0.5", "15", "50000", "123.4"][:len(columns)])
    for i in range(n_images):
        (d / "request_images" / "scene_inference" / f"20260101T000000Z_abcdef12_{i + 1}_scene{i + 1}.jpg").write_bytes(JPEG)
    if request_log:
        with open(d / "request_log.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["request-type", "request content", "response content"])
            w.writerow(["scene inference", json.dumps({"jsonText": json.dumps({"name": folder}), "images": []}),
                        json.dumps({"ambient_temperature": 99.9})])
            for k, (name, _) in enumerate(rows):
                img = f"20260101T0000{k:02d}Z_{k:08x}_9_iso1.jpg"
                (d / "request_images" / "object_inference" / img).write_bytes(JPEG)
                w.writerow(["object inference", json.dumps({"jsonText": json.dumps({"name": name, "ambient_temperature": 99.9}),
                                                            "images": [f"request_images\\object_inference\\{img}"]}),
                            json.dumps({"Initial_temperature": 123.4})])


KITCHEN = [("stove_a", "stove"), ("pan", "frying pan"), ("Floor", "floor"), ("mug1", "mug"), ("mug2", "mug"),
           ("mug3", "mug"), ("fridge", "refrigerator"), ("lamp", "lamp"), ("lamp", "lamp"), ("cup", "cup"),
           ("chair1", "chair"), ("chair2", "chair"), ("table", "table"), ("sink", "sink"), ("egrdg", "microwave"),
           ("egrdg", "room")]
MANY = [(f"obj{i}", f"cat{i % 20}") for i in range(60)]
CABIN = [(f"thing{i}", f"kind{i % 4}") for i in range(12)]

make_scene("request_log_kitchen", KITCHEN)
make_scene("request_log_desert", MANY)
make_scene("request_log_cabin", CABIN)
make_scene("request_log_winter", KITCHEN, n_images=0)                    # no scene images -> skipped
make_scene("request_log_gingerbread", KITCHEN, columns=["Object_name", "Mass"])  # missing Object_category
make_scene("request_log_cute_kitchen", KITCHEN)                          # must NOT be used for cube_kitchen
