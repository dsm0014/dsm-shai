"""Decide the night's mode without the model (spec 11).

  python3 select_mode.py --specs-dir DIR --open-prs-file FILE   ->  prints "A", "B <spec path>" or "HOLD <reason>"

--open-prs-file is JSON: a list of {"title","url","branch"} for open pull requests (orchestrate.py fetches it).
Mode B needs an unimplemented spec with `origin: nightly-improvement` and Status TODO or PARTIAL.
"""
import argparse, glob, json, os, re

STATUS = re.compile(r"^\*\*Status:\*\*\s*([A-Za-z ]+)", re.M)
ORIGIN = re.compile(r"^(?:\*\*Origin:\*\*|origin:)\s*nightly-improvement\b", re.M | re.I)
NUM = re.compile(r"^(\d+)-")


def parse_spec(path):
    head = "".join(open(path, encoding="utf-8", errors="replace").readlines()[:40])
    m = STATUS.search(head)
    status = (m.group(1).strip().split(" ")[0].upper() if m else "")
    return {"path": path, "number": int(NUM.match(os.path.basename(path)).group(1)), "status": status,
            "nightly": bool(ORIGIN.search(head))}


def specs(specs_dir):
    out = []
    for p in sorted(glob.glob(os.path.join(specs_dir, "[0-9][0-9]-*.md"))):
        if p.endswith("00-index.md"):
            continue
        out.append(parse_spec(p))
    return out


def select(specs_dir, open_prs):
    mine = [p for p in open_prs if str(p.get("branch", "")).startswith("nightly/")]
    if mine:
        return "HOLD", "previous PR still open: %s" % mine[0].get("url", "?")
    todo = [s for s in specs(specs_dir) if s["nightly"] and s["status"] in ("TODO", "PARTIAL")]
    if todo:
        return "B", min(todo, key=lambda s: s["number"])["path"]
    return "A", ""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs-dir", required=True)
    ap.add_argument("--open-prs-file", required=True)
    a = ap.parse_args()
    prs = json.load(open(a.open_prs_file))
    mode, extra = select(a.specs_dir, prs)
    print((mode + " " + extra).strip())
