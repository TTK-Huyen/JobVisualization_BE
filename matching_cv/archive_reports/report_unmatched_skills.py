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


def topk_sim(query_emb, skill_emb, topk=5):
    sims = np.dot(skill_emb, query_emb)
    idxs = np.argsort(-sims)[:topk]
    return idxs, sims[idxs]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--topk', type=int, default=5)
    parser.add_argument('--model', default='all-MiniLM-L6-v2')
    args = parser.parse_args()

    if SentenceTransformer is None:
        raise RuntimeError('sentence-transformers not installed')

    inp = Path(args.input)
    outp = Path(args.out)
    data = json.loads(inp.read_text(encoding='utf-8'))

    skill_emb, skill_id_to_idx, skill_id_to_name = load_skill_embedding_cache()
    skill_emb = np.asarray(skill_emb, dtype=float)
    norms = np.linalg.norm(skill_emb, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    skill_emb = skill_emb / norms

    # build list of skill names ordered by idx
    max_idx = max(skill_id_to_idx.values())
    idx_to_skill = [None] * (max_idx + 1)
    for sid, idx in skill_id_to_idx.items():
        idx_to_skill[idx] = (sid, skill_id_to_name.get(sid))

    model = SentenceTransformer(args.model)

    report = []
    for j_idx, job in enumerate(data):
        extracted = job.get('extracted_skills') or []
        for s in extracted:
            if isinstance(s, dict):
                name = s.get('skill_name') or s.get('skill') or s.get('name')
                evidence = s.get('evidence_text') or s.get('evidence') or ''
            else:
                name = str(s)
                evidence = ''

            if not name:
                continue

            # substring match
            substr_matches = []
            for sid, sname in skill_id_to_name.items():
                if name.lower() in str(sname).lower():
                    substr_matches.append({'skill_id': sid, 'skill_name': sname})

            # compute embedding for combined context
            query = name if not evidence else f"{name} - {evidence}"
            q_emb = model.encode([query], normalize_embeddings=True)[0]
            idxs, scores = topk_sim(q_emb, skill_emb, topk=args.topk)
            topk = []
            for idx, sc in zip(idxs, scores):
                entry = idx_to_skill[idx]
                sid = entry[0] if entry else None
                sname = entry[1] if entry else None
                topk.append({'skill_id': sid, 'skill_name': sname, 'score': float(sc)})

            report.append({
                'job_index': j_idx,
                'skill_name': name,
                'evidence_text': evidence,
                'substring_matches': substr_matches,
                'topk': topk,
            })

    outp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Wrote report: {outp}')


if __name__ == '__main__':
    main()
