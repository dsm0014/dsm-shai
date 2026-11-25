#!/usr/bin/env python3
# CI check: every git-tracked file whose name ends in .json must parse as valid JSON.
import json
import os
import subprocess
import sys

CHECK_NAME = "json-valid"


def main():
    listing = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=False)
    if listing.returncode != 0:
        print(f"git ls-files failed: {listing.stderr.decode(errors='replace').strip()}")
        return 1
    names = [os.fsdecode(p) for p in listing.stdout.split(b"\0") if p]
    failed = False
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(name, "r", encoding="utf-8") as handle:
                json.load(handle)
        except (OSError, ValueError) as err:
            print(f"{name}: {err}")
            failed = True
    if failed:
        return 1
    print(f"OK {CHECK_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
