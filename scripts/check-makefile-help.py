#!/usr/bin/env python3
# CI check: every .PHONY target in the root Makefile has a help comment, and every help target is listed in .PHONY.
import re
import subprocess
import sys

MAKEFILE = "Makefile"
NAME = r"[A-Za-z0-9_.-]+"
RULE_RE = re.compile(r"^(" + NAME + r")(::?)(.*)$")
HELP_RE = re.compile(r"##(.*)$")
PHONY_RE = re.compile(r"^\.PHONY\s*:(.*)$")


def fail_not_found():
    print("Makefile: not found in git ls-files")
    sys.exit(1)


def check_tracked():
    try:
        result = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
    except OSError:
        fail_not_found()
    if result.returncode != 0 or MAKEFILE not in result.stdout.splitlines():
        fail_not_found()


def logical_lines(text):
    lines, buf = [], ""
    for raw in text.splitlines():
        if raw.endswith("\\"):
            buf += raw[:-1]
        else:
            lines.append(buf + raw)
            buf = ""
    if buf:
        lines.append(buf)
    return lines


def main():
    check_tracked()
    with open(MAKEFILE, encoding="utf-8") as fh:
        lines = logical_lines(fh.read())

    phony = set()
    helps = {}
    for line in lines:
        m = PHONY_RE.match(line)
        if m:
            for name in m.group(1).split("#", 1)[0].split():
                if "%" not in name:
                    phony.add(name)
            continue
        m = RULE_RE.match(line)
        if not m:
            continue
        name, _colons, rest = m.groups()
        if rest.startswith("="):  # := and ::= are variable assignments
            continue
        h = HELP_RE.search(rest)
        if not h or not h.group(1).strip():
            continue
        helps.setdefault(name, h.group(1).strip())

    problems = []
    for name in phony - set(helps):
        problems.append((name, f"phony target {name} has no help comment"))
    for name in set(helps) - phony:
        problems.append((name, f"help target {name} is not declared .PHONY"))

    if problems:
        for _name, msg in sorted(problems):
            print(f"{MAKEFILE}: {msg}")
        sys.exit(1)
    print("OK makefile-help")


if __name__ == "__main__":
    main()
