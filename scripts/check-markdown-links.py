#!/usr/bin/env python3
# Checks that every relative markdown link in a tracked .md file points to an existing file.
import os
import re
import subprocess
import sys

LINK_RE = re.compile(r"\]\(([^)]*)\)")
INLINE_CODE_RE = re.compile(r"`[^`]*`")


def main():
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"error: git ls-files failed: {exc}", file=sys.stderr)
        return 2
    if proc.returncode != 0:
        print(f"error: git ls-files failed: {proc.stderr.strip()}", file=sys.stderr)
        return 2

    paths = [p for p in proc.stdout.splitlines() if p.endswith(".md")]
    problems = 0

    for path in paths:
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            print(f"error: cannot read {path}: {exc}", file=sys.stderr)
            problems += 1
            continue

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            print(f"{path}: not valid UTF-8")
            problems += 1
            continue

        in_fence = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue

            scan = INLINE_CODE_RE.sub("", line)
            for match in LINK_RE.finditer(scan):
                target = match.group(1).strip()
                if target.startswith("<") and ">" in target:
                    target = target[1:target.index(">")]
                else:
                    parts = target.split()
                    target = parts[0] if parts else ""

                if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                    continue

                target = target.split("#", 1)[0]
                if not target:
                    continue

                if target.startswith("/"):
                    resolved = target[1:]
                else:
                    resolved = os.path.join(os.path.dirname(path), target)

                if not os.path.exists(resolved):
                    print(f"{path}:{lineno}: broken link: {target}")
                    problems += 1

    if problems:
        return 1
    print("OK markdown-links")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Not executed: this file was written without running it.
