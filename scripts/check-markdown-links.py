#!/usr/bin/env python3
# Enforces that every relative markdown link in tracked .md files points to an existing file.
import os
import re
import subprocess
import sys

LINK_RE = re.compile(r'\]\(([^)]*)\)')
SKIP_PREFIXES = ('http://', 'https://', 'mailto:', '#')


def main():
    listed = subprocess.run(
        ['git', 'ls-files'], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    md_files = [p for p in listed if p.endswith('.md')]

    problem = False
    for path in md_files:
        with open(path, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
        for match in LINK_RE.finditer(text):
            target = match.group(1).strip()
            parts = target.split()
            target = parts[0] if parts else ''
            if target.startswith(SKIP_PREFIXES):
                continue
            target = target.split('#', 1)[0]
            if not target:
                continue
            resolved = os.path.normpath(os.path.join(os.path.dirname(path), target))
            if not os.path.exists(resolved):
                print(f'{path}: broken relative link {target}')
                problem = True

    if problem:
        return 1
    print('OK check-markdown-links')
    return 0


if __name__ == '__main__':
    sys.exit(main())
