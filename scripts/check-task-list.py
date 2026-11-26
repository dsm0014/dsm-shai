#!/usr/bin/env python3
# Enforces the task list rules in .specter/tasklist.md: each swarm task line names 1 to 3 repository paths and avoids protected paths, the owner-only marker in the tag, and headings that mark a task as not yet approved.
import os
import re
import sys

REL_PATH = ".specter/tasklist.md"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKLIST = os.path.join(ROOT, ".specter", "tasklist.md")

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
CHECKED_PREFIXES = ("- [ ] [swarm]", "- [ ] [swarm-deploy]")
PROTECTED_PREFIXES = (
    ".github/",
    "ci/",
    "deploy/secrets/",
    "deploy/hermes/jobs/swarm",
    "deploy/hermes/jobs/claude-haiku",
)
PROTECTED_SUFFIXES = (".sops.yaml",)
PROTECTED_EXACT = ("CLAUDE.md",)
PATH_EXT_RE = re.compile(r"\.[A-Za-z0-9]+$")
BLOCKED_PHRASES_CS = ("needs you at the machine", "proposed, not decided")
BLOCKED_PHRASES_CI = ("not planned",)


def is_path(token):
    return "/" in token or PATH_EXT_RE.search(token) is not None


def blocked_phrase(stack):
    for _, text in stack:
        for phrase in BLOCKED_PHRASES_CS:
            if phrase in text:
                return phrase
        for phrase in BLOCKED_PHRASES_CI:
            if phrase in text.lower():
                return phrase
    return None


def main():
    if not os.path.isfile(TASKLIST):
        print(f"{REL_PATH}: missing")
        return 1

    with open(TASKLIST, encoding="utf-8") as fh:
        lines = fh.read().split("\n")

    problems = []
    stack = []

    for lineno, line in enumerate(lines, 1):
        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading.group(2).strip()))
            continue

        if not line.startswith(CHECKED_PREFIXES):
            continue

        # (a) backticked tokens and repository path count
        parts = line.split("`")
        tokens = [parts[i] for i in range(1, len(parts) - 1, 2)]
        paths = [t for t in tokens if is_path(t)]
        if not 1 <= len(paths) <= 3:
            problems.append(
                (lineno, f"expected 1 to 3 repository paths in backticks, found {len(paths)}")
            )

        # (b) protected paths
        for token in paths:
            if (
                token.startswith(PROTECTED_PREFIXES)
                or token.endswith(PROTECTED_SUFFIXES)
                or token in PROTECTED_EXACT
            ):
                problems.append((lineno, f"protected path: {token}"))

        # (c) owner-only marker in the tag (text before the first bold title)
        tag = line.split("**", 1)[0]
        if "[owner" in tag.lower() or "owner-only" in tag.lower():
            problems.append((lineno, "owner-only marker in tag"))

        # (d) blocked heading
        phrase = blocked_phrase(stack)
        if phrase is not None:
            problems.append((lineno, f"task is under heading containing: {phrase}"))

    if problems:
        for lineno, message in problems:
            print(f"{REL_PATH}:{lineno}: {message}")
        return 1

    print("OK task-list-lint")
    return 0


if __name__ == "__main__":
    sys.exit(main())
