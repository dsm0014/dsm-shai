#!/usr/bin/env python3
# Enforces that every git-tracked file whose name ends in .py compiles (UTF-8 source, with or without a byte-order mark).
# Nothing is written to disk. Exit 1 with one line per problem (path: message), exit 0 with OK python-syntax when clean.
import subprocess
import sys

def main():
    listing = subprocess.run(
        ["git", "ls-files", "-z"], check=True, capture_output=True
    ).stdout
    problems = 0
    for raw in listing.split(b"\0"):
        if not raw.endswith(b".py"):
            continue
        path = raw.decode("utf-8", "surrogateescape")
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            source = data.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            print(f"{path}: {e}")
            problems += 1
            continue
        try:
            compile(source, path, "exec", dont_inherit=True)
        except SyntaxError as e:
            print(f"{path}: line {e.lineno}: {e.msg}")
            problems += 1
    if problems:
        sys.exit(1)
    print("OK python-syntax")
    sys.exit(0)

if __name__ == "__main__":
    main()
