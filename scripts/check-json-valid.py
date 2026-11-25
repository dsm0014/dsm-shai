#!/usr/bin/env python3
# Enforces that every git-tracked file whose name ends in .json parses as valid JSON.
import json
import os
import subprocess
import sys


def main():
    listing = subprocess.run(
        ["git", "ls-files", "-z"], check=True, capture_output=True
    ).stdout
    names = [
        os.fsdecode(raw)
        for raw in listing.split(b"\0")
        if raw
    ]
    status = 0
    for path in names:
        if not path.endswith(".json"):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                json.load(handle)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            print(f"{path}: {exc}")
            status = 1
    if status == 0:
        print("OK json-valid")
    return status


if __name__ == "__main__":
    sys.exit(main())
