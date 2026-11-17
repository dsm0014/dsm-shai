"""Drop improvement vectors that overlap existing specs or earlier nightly PRs (spec 11).

  python3 dedupe.py --vectors vectors.json --existing existing.json [--threshold 0.5]

vectors.json: [{"title": str, "keywords": [str]}]. existing.json: [str] (spec titles, open and closed nightly PR titles).
Prints the kept vectors as JSON. Overlap is Jaccard similarity of lower-cased word sets.
"""
import argparse, json, re

STOP = {"the", "a", "an", "of", "for", "to", "and", "in", "on", "with", "add", "support", "improve", "spec", "specs"}


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 2}


def similarity(a, b):
    a, b = words(a), words(b)
    return len(a & b) / len(a | b) if a and b else 0.0


def dedupe(vectors, existing, threshold=0.5):
    kept, seen = [], list(existing)
    for v in vectors:
        text = v.get("title", "") + " " + " ".join(v.get("keywords", []))
        if any(similarity(text, e) >= threshold for e in seen):
            continue
        kept.append(v)
        seen.append(text)  # also de-duplicate vectors against each other
    return kept


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vectors", required=True)
    ap.add_argument("--existing", required=True)
    ap.add_argument("--threshold", type=float, default=0.5)
    a = ap.parse_args()
    print(json.dumps(dedupe(json.load(open(a.vectors)), json.load(open(a.existing)), a.threshold), indent=1))
