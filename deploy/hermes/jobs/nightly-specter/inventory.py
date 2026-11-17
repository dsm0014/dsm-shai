"""Inventory a repository for the model without loading it whole (spec 11).

  python3 inventory.py REPO_DIR   ->  JSON: files, skills, agents, specs, test_command

Also provides chunk(text, max_chars) so no prompt carries more than about 6K tokens (24000 characters) of repo text.
"""
import json, os, re, sys

SKIP = {".git", "node_modules", ".venv", "__pycache__"}
MAX_CHARS = 24000


def chunk(text, max_chars=MAX_CHARS):
    out, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 > max_chars and cur:
            out.append(cur)
            cur = ""
        while len(para) > max_chars:
            out.append(para[:max_chars])
            para = para[max_chars:]
        cur += para + "\n\n"
    if cur.strip():
        out.append(cur)
    return out


def test_command(root):
    if os.path.exists(os.path.join(root, "scripts", "validate.sh")):
        return "scripts/validate.sh"
    mk = os.path.join(root, "Makefile")
    if os.path.exists(mk) and re.search(r"^test:", open(mk).read(), re.M):
        return "make test"
    return ""


def inventory(root):
    files, skills, agents, specs = [], [], [], []
    for d, dirs, names in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP)
        for n in sorted(names):
            rel = os.path.relpath(os.path.join(d, n), root)
            files.append({"path": rel, "size": os.path.getsize(os.path.join(d, n))})
            if n == "SKILL.md":
                skills.append(os.path.dirname(rel) or ".")
            if "/agents/" in "/" + rel and rel.endswith(".md"):
                agents.append(rel)
            if re.fullmatch(r"specs/\d\d-.*\.md", rel) and not rel.endswith("00-index.md"):
                head = open(os.path.join(root, rel), errors="replace").read(600)
                m = re.search(r"^\*\*Status:\*\*\s*(\w+)", head, re.M)
                t = re.search(r"^# (.+)$", head, re.M)
                specs.append({"path": rel, "title": t.group(1) if t else rel, "status": m.group(1) if m else ""})
    return {"file_count": len(files), "files": files[:500], "skills": skills, "agents": agents, "specs": specs,
            "test_command": test_command(root)}


if __name__ == "__main__":
    print(json.dumps(inventory(sys.argv[1] if len(sys.argv) > 1 else "."), indent=1))
