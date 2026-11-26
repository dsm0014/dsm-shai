#!/usr/bin/env python3
# Check enforces consistency between specs/NN-name.md files and specs/00-index.md

import os
import re
import subprocess
import sys

def get_spec_files():
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        path for path in result.stdout.splitlines()
        if path.startswith("specs/") and path != "specs/00-index.md"
        and re.match(r"^specs/[0-9]{2}-.+\.md$", path)
    ]

def get_status_from_spec(path):
    with open(path, "r") as f:
        for line in f:
            if line.startswith("**Status:**"):
                status_text = line[len("**Status:**"):].strip()
                # Extract first word, strip markdown and punctuation
                first_word = re.sub(r"[^\w\s]", "", status_text.split()[0].strip("`*"))
                return first_word.upper()
    return None

def get_index_status(prefix):
    index_path = "specs/00-index.md"
    if not os.path.exists(index_path):
        return None

    with open(index_path, "r") as f:
        for line in f:
            if line.startswith(f"| {prefix} "):
                # Find the status cell (either under "Status" header or last non-empty cell)
                cells = [cell.strip() for cell in line.split("|")[1:]]
                status_cell = None
                for cell in cells:
                    if cell and not cell.startswith("---"):
                        status_cell = cell
                if not status_cell:
                    return None

                # Extract first word, strip markdown and punctuation
                first_word = re.sub(r"[^\w\s]", "", status_cell.split()[0].strip("`*"))
                return first_word.upper()
    return None

def normalize_status(status):
    if status == "IN":
        return "IN"
    elif status == "PARTIAL":
        return "PARTIAL"
    elif status.startswith("IN PROGRESS"):
        return "IN"
    else:
        return status

def check_spec_consistency():
    spec_files = get_spec_files()
    if not os.path.exists("specs/00-index.md"):
        print("WARN specs/00-index.md: Missing index file")
        return 1 if os.getenv("STRICT") == "1" else 0

    warnings = 0

    for spec_path in spec_files:
        prefix = spec_path.split("-")[0][5:]  # Extract NN from specs/NN-name.md
        spec_status = get_status_from_spec(spec_path)
        index_status = get_index_status(prefix)

        if spec_status is None:
            print(f"WARN {spec_path}: Missing **Status:** line")
            warnings += 1
            continue

        if index_status is None:
            print(f"WARN {spec_path}: No matching row in index for prefix {prefix}")
            warnings += 1
            continue

        spec_group = normalize_status(spec_status)
        index_group = normalize_status(index_status)

        if spec_group != index_group:
            print(f"WARN {spec_path}: Status mismatch (spec: {spec_status}, index: {index_status})")
            warnings += 1

        if spec_status == "DONE":
            with open(spec_path, "r") as f:
                for line in f:
                    if line.startswith("- [ ]"):
                        print(f"WARN {spec_path}: Unchecked acceptance box found in DONE spec")
                        warnings += 1
                        break

    if warnings == 0:
        print("OK spec-consistency")
        return 0
    else:
        return 1 if os.getenv("STRICT") == "1" else 0

if __name__ == "__main__":
    sys.exit(check_spec_consistency())
