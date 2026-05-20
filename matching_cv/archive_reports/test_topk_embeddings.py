#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import numpy as np

from matching_cv.normalizer import load_skill_embedding_cache

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None


def cosine_sim(a: np.ndarray, b: np.ndarray):
    # assume normalized rows
    return np.dot(a, b.T)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to extracted.json")
    parser.add_argument("--job-index", type=int, default=0, help="0-based job index to inspect (default: 0)")
    parser.add_argument("--topk", type=int, default=5, help="Top-K nearest skills to return")
    parser.add_argument("--model", type=str, default="all-MiniLM-L6-v2")
    args = parser.parse_args()

    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers not installed in the environment")

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) == 0:
        raise SystemExit("Expected a non-empty JSON list in extracted.json")

    job = data[args.job_index]

    # load skill embedding cache
    skill_emb, skill_id_to_idx, skill_id_to_name = load_skill_embedding_cache()
    # normalize skill_emb rows
    skill_emb = np.asarray(skill_emb, dtype=float)
    norms = np.linalg.norm(skill_emb, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    skill_emb = skill_emb / norms

    model = SentenceTransformer(args.model)

    extracted = job.get("extracted_skills") or job.get("extracted_skills_raw") or []
    # normalize extracted list into strings
    queries = []
    for e in extracted:
        if isinstance(e, dict):
            q = e.get("skill") or e.get("skill_name") or e.get("name") or e.get("skill_text")
        else:
            q = str(e)
        if q:
            queries.append(q)

    if not queries:
        print("No extracted skills found in selected job")
        return

    q_emb = model.encode(queries, normalize_embeddings=True)

    for i, q in enumerate(queries):
        qe = q_emb[i]
        sims = cosine_sim(qe, skill_emb)  # (N_skills,)
        # get topk indices
        topk = int(min(args.topk, sims.shape[0]))
        idxs = np.argsort(-sims)[:topk]
        print(f"\nQuery[{i}]='{q}' -> top {topk} matches:")
        for rank, idx in enumerate(idxs, start=1):
            # find skill_id for idx
            skill_id = None
            for sid, sidx in skill_id_to_idx.items():
                if sidx == int(idx):
                    skill_id = sid
                    break
            skill_name = skill_id_to_name.get(skill_id, "<unknown>") if skill_id is not None else "<unknown>"
            print(f" {rank:02d}. id={skill_id} name={skill_name} score={float(sims[idx]):.6f}")


if __name__ == "__main__":
    main()
