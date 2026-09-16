"""Researcher command line (same functions as the researcher screen).

    python manage.py preflight
    python manage.py manifest --preview          # print draft sample
    python manage.py manifest --write [--force]  # write study_manifest.csv
    python manage.py export [--include-incomplete]
"""
from __future__ import annotations

import argparse
import sys

import config
import database as db
import export
import manifest as mf
import validation as val


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preflight")
    m = sub.add_parser("manifest")
    m.add_argument("--preview", action="store_true")
    m.add_argument("--write", action="store_true")
    m.add_argument("--force", action="store_true", help="overwrite an existing manifest")
    e = sub.add_parser("export")
    e.add_argument("--include-incomplete", action="store_true")
    a = ap.parse_args(argv)
    db.init_db()

    if a.cmd == "preflight":
        checks = val.run_preflight()
        print(f"Data root: {config.DATA_ROOT}")
        for c in checks:
            mark = {"ok": "✓", "warn": "⚠", "error": "✕"}[c.status if c.available else "error"]
            print(f"\n{mark} {c.label}  ({c.folder})")
            for _, t in c.messages:
                print(f"    {t}")
        print(f"\nAvailable scenes: {sum(c.available for c in checks)} / {len(checks)}")
        return 0

    if a.cmd == "manifest":
        checks = val.run_preflight()
        df = mf.generate_manifest(checks)
        if a.preview or not a.write:
            print(df.drop(columns=["source_csv_sha256", "object_image_path"]).to_string(index=False))
        if a.write:
            if mf.manifest_exists() and not a.force:
                print(f"\n{config.MANIFEST_PATH} exists. Use --force to overwrite.", file=sys.stderr)
                return 1
            if a.force and db.count_annotations():
                print("Warning: annotations already exist for the current manifest.", file=sys.stderr)
            mf.write_manifest(df, overwrite=a.force)
            print(f"\nWrote {config.MANIFEST_PATH} ({len(df)} objects)")
        return 0

    if a.cmd == "export":
        for name, p in export.export_all(include_incomplete=a.include_incomplete).items():
            print(f"{name}: {p}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
