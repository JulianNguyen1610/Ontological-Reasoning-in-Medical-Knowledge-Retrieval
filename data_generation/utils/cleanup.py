"""Cleanup pass cho training data da sinh.
Loc entity-type/assertion ngoai schema, re-locate position, dedupe span trung.
"""
import json, sys, io
from pathlib import Path
from collections import Counter

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

VALID_TYPES = {"TRI\u1ec6U_CH\u1ee8NG", "T\u00caN_X\u00c9T_NGHI\u1ec6M", "K\u1ebeT_QU\u1ea2_X\u00c9T_NGHI\u1ec6M", "CH\u1ea8N_\u0110O\u00c1N", "THU\u1ed0C"}
VALID_ASSERTS = {"isNegated", "isFamily", "isHistorical"}


import string
def _strip_punct(span):
    return span.strip(string.punctuation + chr(9) + chr(10))


def _relocate(entities, text):
    used = []
    fixed = []
    for e in entities:
        target = e["text"]
        start, end = -1, -1
        for cand in (target, _strip_punct(target)):
            if not cand:
                continue
            idx = 0
            while True:
                pos = text.find(cand, idx)
                if pos < 0:
                    break
                eend = pos + len(cand)
                if not any(not (eend <= u[0] or pos >= u[1]) for u in used):
                    start, end = pos, eend
                    used.append((pos, eend))
                    break
                idx = pos + 1
            if start >= 0:
                break
        if start >= 0:
            ne = dict(e)
            ne["text"] = text[start:end]
            ne["position"] = [start, end]
            fixed.append(ne)
    return fixed


def _filter_schema(entities):
    out = []
    for e in entities:
        if e.get("type") not in VALID_TYPES:
            continue
        a = [x for x in e.get("assertions", []) if x in VALID_ASSERTS]
        ne = dict(e)
        ne["assertions"] = a
        out.append(ne)
    return out


def clean_sample(sample):
    text = sample.get("text", "")
    entities = sample.get("entities", [])
    entities = _filter_schema(entities)
    entities = _relocate(entities, text)
    seen = set()
    out = []
    for e in entities:
        key = (e["position"][0], e["position"][1], e["type"])
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return {"text": text, "entities": out, "scenario_id": sample.get("scenario_id", "")}


def clean_file(path):
    data = json.load(open(path, encoding="utf-8"))
    return [clean_sample(s) for s in data]


def coverage(samples):
    types = Counter()
    asserts = Counter()
    pos_bad = 0
    pos_total = 0
    empty = 0
    for s in samples:
        if not s["entities"]:
            empty += 1
        for e in s["entities"]:
            types[e["type"]] += 1
            pos_total += 1
            p = e.get("position", [0, 0])
            if not (len(p) == 2 and p[1] > p[0] and p[1] <= len(s["text"]) and s["text"][p[0]:p[1]] == e["text"]):
                pos_bad += 1
            for a in e.get("assertions", []):
                asserts[a] += 1
    return {"n_samples": len(samples), "empty_samples": empty, "entity_types": dict(types), "assertions": dict(asserts), "pos_bad": pos_bad, "pos_total": pos_total}


if __name__ == "__main__":
    out_dir = Path(__file__).parent.parent / "output"
    sources = ["training_data.json", "training_data_20260707_030445.json"]
    all_in = []
    for s in sources:
        p = out_dir / s
        if p.exists():
            all_in.extend(json.load(open(p, encoding="utf-8")))
    print("loaded raw:", len(all_in))
    cleaned = [clean_sample(x) for x in all_in]
    cleaned = [c for c in cleaned if c["entities"]]
    out = out_dir / "training_data_clean.json"
    json.dump(cleaned, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    out_jsonl = out_dir / "training_data_clean.jsonl"
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for c in cleaned:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print("cleaned:", len(cleaned), "->", out)
    print("coverage:", json.dumps(coverage(cleaned), ensure_ascii=False, indent=2))
