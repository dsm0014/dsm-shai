#!/usr/bin/env python3
# Enforces task-list lint rules for .specter/tasklist.md (swarm task lines).
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKLIST = REPO_ROOT / ".specter" / "tasklist.md"
TASK_PREFIXES = ("- [ ] [swarm]", "- [ ] [swarm-deploy]")
FORBIDDEN_PATH_PREFIXES = (
    ".github/",
    "ci/",
    "deploy/secrets/",
    "deploy/hermes/jobs/swarm",
    "deploy/hermes/jobs/claude-haiku",
)
FORBIDDEN_PATH_SUFFIXES = (".sops.yaml",)
FORBIDDEN_PATH_EXACT = ("CLAUDE.md",)
OWNER_ONLY_MARKER = "[owner-only]"
FORBIDDEN_HEADING_PHRASES = (
    "needs you at the machine",
    "proposed",
    "not decided",
    "not planned",
)
BACKTICK_TOKEN = re.compile(r"`([^`]*)`")
FILE_EXTENSION = re.compile(r"\.[A-Za-z0-9]+$")
HEADING = re.compile(r"^(#+) (.*)$")


def is_path_token(token):
    return "/" in token or FILE_EXTENSION.search(token) is not None


def main():
    try:
        with open(TASKLIST, encoding="utf-8", newline="") as fh:
            text = fh.read()
    except FileNotFoundError:
        print(".specter/tasklist.md: missing")
        return 1

    problems = []
    headings = []  # list of (level, title) currently in effect
    for lineno, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip("\r\n")

        m = HEADING.match(line)
        if m:
            level = len(m.group(1))
            headings = [h for h in headings if h[0] < level]
            headings.append((level, m.group(2)))
            continue

        if not line.startswith(TASK_PREFIXES):
            continue

        # (a) between one and three repository path tokens
        tokens = BACKTICK_TOKEN.findall(line)
        paths = [t for t in tokens if is_path_token(t)]
        if not 1 <= len(paths) <= 3:
            problems.append(
                (lineno, f"expected 1 to 3 repository path tokens, found {len(paths)}")
            )

        # (b) forbidden path tokens
        for tok in paths:
            if (
                tok.startswith(FORBIDDEN_PATH_PREFIXES)
                or tok.endswith(FORBIDDEN_PATH_SUFFIXES)
                or tok in FORBIDDEN_PATH_EXACT
            ):
                problems.append(
                    (lineno, f"path `{tok}` is not allowed in a [swarm] task")
                )

        # (c) owner-only marker in the tag before the bold title
        head = line.split("**", 1)[0]
        if OWNER_ONLY_MARKER in head.lower():
            problems.append(
                (lineno, "owner-only marker is not allowed in the task tag")
            )

        # (d) task under a forbidden heading
        for _level, title in headings:
            lowered = title.lower()
            if any(phrase in lowered for phrase in FORBIDDEN_HEADING_PHRASES):
                problems.append(
                    (lineno, f"task is under forbidden heading '{title}'")
                )
                break

    for lineno, message in problems:
        print(f".specter/tasklist.md:{lineno}: {message}")
    if problems:
        return 1

    print("OK task-list-lint")
    return 0


if __name__ == "__main__":
    sys.exit(main())
