"""pull_hevy.py: every Hevy workout into data/gym.csv, in the layout of Hevy's own CSV export.

    python hevy/pull_hevy.py [--root R] [--out PATH]

Read-only toward Hevy. All or nothing: every page is fetched and the number of workouts is checked
against Hevy's own count before anything is written, and the file is replaced by a rename, so it is
never half written. Exit 0 on success; 1 on any failure, with the old file left as it was.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True          # no __pycache__ in the Drive folder (Google Drive syncs every file)

from hevy import rows as hrows                     # noqa: E402
from hevy.client import HevyClient, HevyError      # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def write_atomic(path: pathlib.Path, text: str) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def pull(client, out: pathlib.Path) -> str:
    """Fetch, check, write; returns a one-line summary. Raises HevyError, writing nothing, on any problem."""
    workouts = client.workouts()
    expected = client.workout_count()
    if len(workouts) != expected:
        raise HevyError(f"Hevy listed {len(workouts)} workouts but counts {expected}; nothing written.")
    table = hrows.all_rows(workouts)
    write_atomic(out, hrows.to_csv(table))
    return f"ok: {len(workouts)} workouts, {len(table)} sets -> {out}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pull every Hevy workout into data/gym.csv (read-only).")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out", default=None, help="output CSV (default: <root>/data/gym.csv)")
    args = ap.parse_args(argv)
    out = pathlib.Path(args.out) if args.out else pathlib.Path(args.root) / "data" / "gym.csv"
    try:
        print(pull(HevyClient.from_env(), out))
    except HevyError as e:
        print(f"HEVY PULL FAILED: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"HEVY PULL FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
