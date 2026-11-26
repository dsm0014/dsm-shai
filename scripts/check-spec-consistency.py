#!/usr/bin/env python3
# Enforces spec/index status consistency: each specs/NN-name.md needs a **Status:** line and a matching row in specs/00-index.md with the same status group, and a DONE spec must have no unchecked acceptance box (- [ ]).
import os
import re
import subprocess
import sys

INDEX_PATH = "specs/00-index.md"
SPEC_RE = re.compile(r"^specs/(\d{2})-[A-Za-z0-9._-]+\.md$")
STATUS_PREFIX = "**Status:**"

warnings = []


def warn(path, message):
    warnings.append("WARN %s: %s" % (path, message))


def read_lines(path):
    # Decode leniently so non-UTF-8 bytes never raise UnicodeDecodeError.
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", errors="replace").splitlines()


def first_word(text):
    match = re.search(r"[A-Za-z]+", text)
    return match.group(0).upper() if match else ""


def group_of(word):
    if word in ("PARTIAL", "IN"):
        return "IN"
    return word


def parse_index(lines):
    """Return a dict mapping NN -> raw status cell text for each index row."""
    rows = {}
    status_col = None
    title_col = None
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells:
            continue
        lowered = [c.lower() for c in cells]
        if status_col is None and any("status" in c for c in lowered):
            status_col = next(i for i, c in enumerate(lowered) if "status" in c)
            title_col = next((i for i, c in enumerate(lowered) if "title" in c), None)
            continue
        match = re.match(r"\[?(\d{2})\b", cells[0])
        if not match:
            continue
        nn = match.group(1)
        if status_col is not None:
            idx = status_col
        else:
            idx = (title_col if title_col is not None else 1) + 1
        status_text = cells[idx] if idx < len(cells) else ""
        rows.setdefault(nn, status_text)
    return rows


def main():
    try:
        proc = subprocess.run(["git", "ls-files"], capture_output=True)
        if proc.returncode == 0:
            listing = proc.stdout.decode("utf-8", errors="replace").splitlines()
        else:
            listing = None
    except OSError:
        listing = None
    if listing is None:
        warn("git ls-files", "could not list repository files")
        listing = []

    index_lines = None
    if os.path.isfile(INDEX_PATH):
        try:
            index_lines = read_lines(INDEX_PATH)
        except OSError as exc:
            warn(INDEX_PATH, "cannot read index: %s" % exc)
    else:
        warn(INDEX_PATH, "index file is missing")

    index_rows = parse_index(index_lines) if index_lines is not None else None

    spec_files = sorted(
        p for p in listing if SPEC_RE.match(p) and p != INDEX_PATH
    )

    for path in spec_files:
        nn = SPEC_RE.match(path).group(1)
        try:
            lines = read_lines(path)
        except OSError as exc:
            warn(path, "cannot read spec: %s" % exc)
            continue

        spec_word = None
        for line in lines:
            if line.startswith(STATUS_PREFIX):
                spec_word = first_word(line[len(STATUS_PREFIX):])
                break

        spec_group = None
        if spec_word is None:
            warn(path, "no **Status:** line found")
        elif not spec_word:
            warn(path, "**Status:** line has no status word")
        else:
            spec_group = group_of(spec_word)

        if index_rows is not None:
            if nn not in index_rows:
                warn(path, "no row for %s in %s" % (nn, INDEX_PATH))
            else:
                index_word = first_word(index_rows[nn])
                if not index_word:
                    warn(path, "index status cell for %s is empty" % nn)
                elif spec_group is not None:
                    index_group = group_of(index_word)
                    if index_group != spec_group:
                        warn(
                            path,
                            "spec status %s does not match index status %s"
                            % (spec_word, index_word),
                        )

        if spec_group == "DONE":
            for num, line in enumerate(lines, 1):
                if line.startswith("- [ ]"):
                    warn(
                        path,
                        "DONE spec has unchecked acceptance box at line %d" % num,
                    )

    if warnings:
        for w in warnings:
            print(w)
        if os.environ.get("STRICT") == "1":
            return 1
        return 0

    print("OK spec-consistency")
    return 0


if __name__ == "__main__":
    sys.exit(main())
