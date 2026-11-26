#!/usr/bin/env python3
# Checks spec consistency between specs/NN-name.md files and the table in specs/00-index.md.
import os
import re
import subprocess
import sys

INDEX_PATH = "specs/00-index.md"
SPEC_RE = re.compile(r"^specs/(\d{2})-[^/]+\.md$")
STATUS_PREFIX = "**Status:**"


def tracked_files():
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        sys.stderr.write("git ls-files failed: " + result.stderr)
        sys.exit(2)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def first_word(text):
    words = text.strip().split()
    if not words:
        return ""
    return re.sub(r"[^A-Za-z]", "", words[0]).upper()


def status_group(word):
    if word in ("PARTIAL", "IN"):
        return "PARTIAL"
    return word


def parse_index(index_text):
    """Return a dict mapping NN -> raw status cell text for each index table row."""
    statuses = {}
    status_col = None
    prev_header = None
    for line in index_text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            prev_header = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if any(cells) and all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            # Separator row: the previous table line is the header.
            status_col = None
            if prev_header is not None:
                for i, h in enumerate(prev_header):
                    if "status" in h.lower():
                        status_col = i
                        break
            continue
        if not cells:
            continue
        key = re.sub(r"[*_`]", "", cells[0]).strip()
        prev_header = cells
        if re.fullmatch(r"\d{2}", key) and key not in statuses:
            col = status_col if status_col is not None else 1
            statuses[key] = cells[col] if col < len(cells) else ""
    return statuses


def main():
    files = tracked_files()
    specs = sorted(f for f in files if SPEC_RE.match(f) and f != INDEX_PATH)

    index_text = read_text(INDEX_PATH) if os.path.isfile(INDEX_PATH) else ""
    index_status = parse_index(index_text)

    problems = []
    for path in specs:
        nn = SPEC_RE.match(path).group(1)
        lines = read_text(path).splitlines()

        status_line = None
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith(STATUS_PREFIX):
                status_line = stripped
                break

        spec_word = None
        if status_line is None:
            problems.append((path, "missing '**Status:**' line"))
        else:
            spec_word = first_word(status_line[len(STATUS_PREFIX):])

        if nn not in index_status:
            problems.append((path, f"no row for {nn} in {INDEX_PATH}"))
        elif spec_word is not None:
            idx_word = first_word(index_status[nn])
            if status_group(spec_word) != status_group(idx_word):
                problems.append(
                    (
                        path,
                        f"status mismatch: spec '{spec_word}' vs index '{idx_word}'",
                    )
                )

        if spec_word == "DONE":
            for n, line in enumerate(lines, 1):
                if line.lstrip().startswith("- [ ]"):
                    problems.append(
                        (path, f"line {n}: unchecked acceptance box in DONE spec")
                    )

    if problems:
        for path, message in problems:
            print(f"WARN {path}: {message}")
        strict = os.environ.get("STRICT") == "1"
        sys.exit(1 if strict else 0)

    print("OK spec-consistency")
    sys.exit(0)


if __name__ == "__main__":
    main()
