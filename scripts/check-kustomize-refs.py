#!/usr/bin/env python3
# Check: every list item in a tracked kustomization.yaml that names a .yaml, .yml, .json, .sh, .py, .txt or .md file (as `name.ext` or `key=name.ext`) must resolve to an existing file relative to that kustomization's directory.
import os
import re
import subprocess
import sys

PATTERN = re.compile(
    r'^\s*-\s+(?:[^=\s]+=)?([^\s=]+\.(?:yaml|yml|json|sh|py|txt|md))\s*$'
)


def main():
    result = subprocess.run(
        ['git', 'ls-files', '-z'], capture_output=True, check=True
    )
    paths = [os.fsdecode(p) for p in result.stdout.split(b'\0') if p]

    problems = []
    for path in paths:
        if os.path.basename(path) != 'kustomization.yaml':
            continue
        directory = os.path.dirname(path)
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            for lineno, line in enumerate(fh, start=1):
                match = PATTERN.match(line)
                if not match:
                    continue
                name = match.group(1)
                if '://' in name:
                    continue
                target = os.path.join(directory, name)
                if not os.path.exists(target):
                    problems.append(
                        f'{path}: line {lineno}: referenced file does not exist: {name}'
                    )

    if problems:
        for problem in problems:
            print(problem)
        sys.exit(1)

    print('OK kustomize-refs')
    sys.exit(0)


if __name__ == '__main__':
    main()
