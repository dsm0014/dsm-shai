"""Spec file helpers: next number, allowed paths, index rows, status edits (spec 11). Used by orchestrate.py."""
import glob, os, re


def next_number(specs_dir):
    nums = [int(re.match(r"(\d+)-", os.path.basename(p)).group(1)) for p in glob.glob(os.path.join(specs_dir, "[0-9][0-9]-*.md"))]
    return (max(nums) if nums else 0) + 1


def slugify(title):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", title.lower())).strip("-")[:48] or "improvement"


def allowed_paths(spec_text):
    """Paths named in the spec's Files section: backticked tokens under a heading or bold label starting 'Files'.
    A trailing slash allows a directory. Returns [] when the section is absent, which makes the spec BLOCKED."""
    out, on = [], False
    for line in spec_text.splitlines():
        if re.match(r"^(#{2,4}\s*|\*\*)Files?\b", line, re.I):
            on = True
            continue
        if on and (re.match(r"^#{1,4}\s", line) or re.match(r"^\*\*[^*]+\*\*\s*$", line)):
            on = False
        if on:
            for tok in re.findall(r"`([^`\s]+)`", line):
                if "/" in tok or re.search(r"\.\w+$", tok):
                    if not tok.startswith(("/", "..")) and ".." not in tok.split("/"):
                        out.append(tok)
    return sorted(set(out))


def normalize_files(text):
    """The model often lists Files as bare paths. Wrap a bare path in backticks so allowed_paths() can read it."""
    out, on = [], False
    for line in text.split("\n"):
        if re.match(r"^(#{2,4}\s*|\*\*)Files?\b", line, re.I):
            on = True
        elif on and re.match(r"^#{1,4}\s", line):
            on = False
        m = re.match(r"^(\s*[-*]\s+)([^\s`]+)\s*$", line)
        if on and m and ("/" in m.group(2) or re.search(r"\.\w+$", m.group(2))):
            line = "%s`%s`" % (m.group(1), m.group(2))
        out.append(line)
    return "\n".join(out)


def set_status(text, status, note=""):
    new = "**Status:** %s%s" % (status, (" (" + note + ")") if note else "")
    if re.search(r"^\*\*Status:\*\*.*$", text, re.M):
        return re.sub(r"^\*\*Status:\*\*.*$", lambda m: new, text, count=1, flags=re.M)
    return text


def ensure_origin(text, number, title=None):
    text = re.sub(r"^# Spec \d+", "# Spec %02d" % number, text, count=1, flags=re.M)
    if not re.search(r"^\*\*Origin:\*\*\s*nightly-improvement", text, re.M):
        text = re.sub(r"^(\*\*Status:\*\*.*)$", lambda m: m.group(1) + "\n\n**Origin:** nightly-improvement", text, count=1, flags=re.M)
    return text


def index_columns(index_text):
    """Number of cells in the index table header (the first line starting with '| #')."""
    for line in index_text.splitlines():
        if line.startswith("| #"):
            return line.strip().strip("|").count("|") + 1
    return 3


def index_add(index_text, number, title, filename):
    """Append a row that matches the table's own column count (3: # Spec Status; 4 adds an open-items cell)."""
    row = "| %02d | [%s](./%s) | TODO |" % (number, title, filename)
    if index_columns(index_text) >= 4:
        row += " origin: nightly-improvement |"
    lines = index_text.rstrip("\n").split("\n")
    last = max([i for i, l in enumerate(lines) if re.match(r"^\| \d\d \|", l)] or [len(lines) - 1])
    lines.insert(last + 1, row)
    return "\n".join(lines) + "\n"


def index_set_status(index_text, number, status):
    def fix(m):
        cells = m.group(0).split("|")
        cells[3] = " %s " % status
        return "|".join(cells)
    return re.sub(r"^\| %02d \|.*$" % number, fix, index_text, count=1, flags=re.M)
