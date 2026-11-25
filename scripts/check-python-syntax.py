#!/usr/bin/env python3
# Check that every git-tracked file whose name ends in .py compiles without a SyntaxError.
import subprocess
import sys


def main():
    listing = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True)
    names = listing.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    paths = [name for name in names if name.endswith(".py")]

    problems = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"{path}: {exc}")
            continue
        try:
            compile(source, path, "exec", dont_inherit=True)
        except SyntaxError as exc:
            if exc.lineno is not None:
                problems.append(f"{path}:{exc.lineno}: {exc.msg}")
            else:
                problems.append(f"{path}: {exc.msg}")
        except ValueError as exc:
            problems.append(f"{path}: {exc}")

    if problems:
        for line in problems:
            print(line)
        return 1
    print("OK python-syntax")
    return 0


if __name__ == "__main__":
    sys.exit(main())
