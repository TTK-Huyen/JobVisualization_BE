#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import numpy as np

from matching_cv.normalizer import load_skill_embedding_cache, load_job_normalizer_module

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None


def topk_sim(query_emb, skill_emb, topk=10):
    sims = np.dot(skill_emb, query_emb)
    idxs = np.argsort(-sims)[:topk]
    return idxs, sims[idxs]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--evidence", default="")
    parser.add_argument("--topk", type=int, default=10)
    parser.add_argument("--model", default="all-MiniLM-L6-v2")
    args = parser.parse_args()

    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers not installed in the environment")

    skill_emb, skill_id_to_idx, skill_id_to_name = load_skill_embedding_cache()
    skill_emb = np.asarray(skill_emb, dtype=float)
    norms = np.linalg.norm(skill_emb, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    skill_emb = skill_emb / norms

    # build list of skill names ordered by idx for easy lookup
    max_idx = max(skill_id_to_idx.values())
    idx_to_skill = [None] * (max_idx + 1)
    for sid, idx in skill_id_to_idx.items():
        idx_to_skill[idx] = (sid, skill_id_to_name.get(sid))

    # simple substring search
    q = args.query.strip()
    print(f"Checking skill map for occurrences of '{q}' (case-insensitive substring)")
    found = []
    for sid, name in skill_id_to_name.items():
        if q.lower() in str(name).lower():
            found.append((sid, name))
    if found:
        print("Substring matches in skill map:")
        for sid, name in found:
            print(f" - id={sid} name={name}")
    else:
        print("No substring matches found in skill map")

    # try variations: raw query, 'Apache '+query, query + ' (tool)', and with evidence context
    variants = [q, f"Apache {q}", f"{q} tool", f"{q} - {args.evidence}"] if args.evidence else [q, f"Apache {q}", f"{q} tool"]

    model = SentenceTransformer(args.model)

    for v in variants:
        emb = model.encode([v], normalize_embeddings=True)[0]
        idxs, scores = topk_sim(emb, skill_emb, topk=args.topk)
        print(f"\nVariant: '{v}' -> top {args.topk}")
        for rank, (idx, sc) in enumerate(zip(idxs, scores), start=1):
            entry = idx_to_skill[idx]
            sid = entry[0] if entry else None
            name = entry[1] if entry else "<unknown>"
            print(f" {rank:02d}. id={sid} name={name} score={float(sc):.6f}")


if __name__ == "__main__":
    main()
