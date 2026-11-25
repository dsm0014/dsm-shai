#!/usr/bin/env python3
# Enforces that every tracked file whose name ends in .json parses as valid JSON.
import json
import subprocess
import sys


def main():
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    paths = [p for p in result.stdout.splitlines() if p.endswith(".json")]

    problems = []
    for path in paths:
        try:
            # utf-8-sig: a UTF-8 byte-order mark is allowed; json.load would reject it as text.
            with open(path, encoding="utf-8-sig") as fh:
                json.load(fh)
        except Exception as exc:
            problems.append((path, exc))

    if problems:
        for path, exc in problems:
            print(f"{path}: {exc}")
        return 1

    print("OK json-valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
