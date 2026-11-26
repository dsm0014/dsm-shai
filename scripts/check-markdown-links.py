#!/usr/bin/env python3
# Enforces that every relative markdown link in a tracked .md file points to an existing file.
import os
import re
import subprocess
import sys


def main():
    result = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, check=True)
    md_files = [p for p in result.stdout.splitlines() if p.endswith('.md')]

    problems = 0
    for path in md_files:
        with open(path, 'rb') as fh:
            data = fh.read()
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            print(f'{path}: not valid UTF-8')
            problems += 1
            continue

        in_fence = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith('```') or stripped.startswith('~~~'):
                in_fence = not in_fence
                continue
            if in_fence:
                continue

            line = re.sub(r'`[^`]*`', '', line)
            for match in re.finditer(r'\]\(([^)\s]+)\)', line):
                target = match.group(1)
                if target.startswith(('http://', 'https://', 'mailto:', '#')):
                    continue
                target = target.split('#', 1)[0]
                if not target:
                    continue
                if target.startswith('/'):
                    resolved = os.path.join(os.getcwd(), target.lstrip('/'))
                else:
                    resolved = os.path.join(os.path.dirname(path), target)
                if not os.path.exists(resolved):
                    print(f'{path}:{lineno}: broken link: {target}')
                    problems += 1

    if problems:
        sys.exit(1)
    print('OK markdown-links')


if __name__ == '__main__':
    main()
