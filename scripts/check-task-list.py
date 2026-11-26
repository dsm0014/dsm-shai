#!/usr/bin/env python3
# Lints .specter/tasklist.md: enforces the swarm task-list rules for [swarm] and [swarm-deploy] tasks.
import os
import re
import subprocess
import sys

TASKLIST = ".specter/tasklist.md"
OK_MSG = "OK check-task-list"

TASK_PREFIXES = ("- [ ] [swarm]", "- [ ] [swarm-deploy]")
FORBIDDEN_PREFIXES = (
    ".github/",
    "ci/",
    "deploy/secrets/",
    "deploy/hermes/jobs/swarm",
    "deploy/hermes/jobs/claude-haiku",
)
FORBIDDEN_SUFFIXES = (".sops.yaml",)
FORBIDDEN_EXACT = ("CLAUDE.md",)
NEEDS_OWNER = "[needs-owner]"
BAD_HEADING_PHRASES = (
    "needs you at the machine",
    "proposed",
    "not decided",
    "not planned",
)

TOKEN_RE = re.compile(r"`([^`]*)`")
EXT_RE = re.compile(r"\.[A-Za-z0-9]+$")
HEADING_RE = re.compile(r"^(#+)\s*(.*)$")


def is_tracked():
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", TASKLIST],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    return TASKLIST in result.stdout.splitlines()


def is_path_like(token):
    return "/" in token or EXT_RE.search(token) is not None


def main():
    if not is_tracked() or not os.path.isfile(TASKLIST):
        print(OK_MSG)
        return 0

    problems = []
    stack = []  # entries are (level, text)

    with open(TASKLIST, encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.rstrip("\r\n")

            if line.startswith("#"):
                m = HEADING_RE.match(line)
                level = len(m.group(1))
                text = m.group(2).strip()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, text))
                continue

            if not line.startswith(TASK_PREFIXES):
                continue

            def report(msg):
                problems.append(f"{TASKLIST}: line {lineno}: {msg}")

            # Rule 1: between one and three backticked repository path tokens.
            tokens = TOKEN_RE.findall(line)
            paths = [t for t in tokens if is_path_like(t)]
            if not 1 <= len(paths) <= 3:
                report(
                    "expected 1 to 3 repository path tokens in backticks, "
                    f"found {len(paths)}"
                )

            # Rule 2: forbidden path tokens.
            for p in paths:
                if (
                    p.startswith(FORBIDDEN_PREFIXES)
                    or p.endswith(FORBIDDEN_SUFFIXES)
                    or p in FORBIDDEN_EXACT
                ):
                    report(f"path `{p}` is not allowed in a swarm task")

            # Rule 3: [needs-owner] must not appear on the line.
            if NEEDS_OWNER in line:
                report("[swarm] task must not contain [needs-owner]")

            # Rule 4: no heading in the current stack may contain a blocked phrase.
            for _level, heading_text in stack:
                lowered = heading_text.lower()
                for phrase in BAD_HEADING_PHRASES:
                    if phrase in lowered:
                        report(
                            f"task sits under heading '{heading_text}' "
                            f"containing '{phrase}'"
                        )
                        break

    if problems:
        for p in problems:
            print(p)
        return 1

    print(OK_MSG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
