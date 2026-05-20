import os
import re
import json
import csv
from collections import defaultdict

PDF_PATH = os.path.join(os.path.dirname(__file__), 'cv', 'CV_Business_Analyst.pdf')
MASTER_CSV = os.path.join(os.path.dirname(__file__), 'Master_IT_Job_Profiles.csv')
OUTPUT_JSON = os.path.join(os.path.dirname(__file__), 'final_insight_report_jobs.json')

# 1. Read PDF text (requires PyPDF2)
try:
    import PyPDF2
except Exception:
    PyPDF2 = None

def read_pdf_text(path):
    if PyPDF2 is None:
        raise RuntimeError('PyPDF2 not installed')
    text = []
    with open(path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        for p in reader.pages:
            try:
                text.append(p.extract_text() or '')
            except Exception:
                text.append('')
    return '\n'.join(text)

# 2. Load master skills set
def load_master_skills(master_csv):
    skills = set()
    rows = []
    with open(master_csv, encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for r in reader:
            name = (r.get('Skill_Name') or '').strip().lower()
            title = (r.get('Title') or '').strip()
            try:
                weight = float(r.get('Weight') or 0.0)
            except Exception:
                weight = 0.0
            cat = (r.get('Category') or '').strip().lower()
            skills.add(name)
            rows.append({'title': title, 'skill': name, 'weight': weight, 'category': cat})
    return skills, rows

# 3. Mock skill extraction: find SKILLS and EXPERIENCE sections and match master skills
def extract_skills_from_text(text, master_skills):
    skills_found = set()
    # naive section split: find the word 'SKILLS' or 'EXPERIENCE'
    # normalize
    txt = text.replace('\r', '\n')
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    # find indices
    idxs = [i for i,l in enumerate(lines) if re.match(r'^(skills|technical skills|experience|work experience)$', l.strip().lower())]
    # collect following 20 lines after SKILLS and EXPERIENCE occurrences
    for i in idxs:
        for j in range(i+1, min(i+1+20, len(lines))):
            line = lines[j].lower()
            # split by common delimiters
            tokens = re.split(r'[;,|•–\\-]', line)
            for t in tokens:
                t = t.strip()
                if not t:
                    continue
                # match full master skill names
                for ms in master_skills:
                    if ms in t or t in ms:
                        skills_found.add(ms)
                # also capture multi-word tokens that look like tools (letters+digits or dots)
                if re.search(r'[a-z]+', t) and len(t.split())<=4:
                    # if token contains common tech indicators
                    if any(k in t for k in ('sql','python','java','docker','git','react','aws','azure','excel','powerpoint','django','html','css','javascript','r ')):
                        skills_found.add(t)
    # fallback: search whole doc for master skills
    if not skills_found:
        lowered = text.lower()
        for ms in master_skills:
            if ms in lowered:
                skills_found.add(ms)
    # fuzzy / synonym mapping: map common synonyms to master skills
    from difflib import get_close_matches
    synonyms = {
        'power bi': ['power bi','data visualization','data visualization (power bi'],
        'team leader': ['management of personnel resources','management of personnel'],
        'team lead': ['management of personnel resources','management of personnel'],
        'process improvement': ['operations analysis','quality control analysis','process improvement'],
        'agile': ['agile','scrum','endeavour agile alm','coordination','operations analysis'],
        'scrum': ['scrum','agile','coordination'],
        'kanban': ['kanban','coordination'],
        'leadership': ['management of personnel resources','management of personnel resources'],
        'project management': ['project management','time management','coordination']
    }

    expanded = set(skills_found)
    # consider tokens from the document for fuzzy mapping
    lowered = text.lower()
    # try direct synonyms
    for key, targets in synonyms.items():
        if key in lowered:
            for tgt in targets:
                # prefer exact master skill match
                for ms in master_skills:
                    if tgt in ms:
                        expanded.add(ms)
    # try fuzzy close matches for individual tokens found
    for token in list(skills_found):
        # look for close master skill names
        matches = get_close_matches(token, list(master_skills), n=3, cutoff=0.75)
        for m in matches:
            expanded.add(m)

    return sorted(list(expanded))

# 4. Embeddings and matching

def build_embeddings(skill_list, model):
    # return list of embeddings in same order
    return model.encode(skill_list, convert_to_tensor=False)

def weighted_job_vector(job_title, master_rows, model):
    skills = [r for r in master_rows if r['title']==job_title]
    if not skills:
        return None, []
    skill_names = [s['skill'] for s in skills]
    weights = [s['weight'] for s in skills]
    embeddings = build_embeddings(skill_names, model)
    # weighted average
    import numpy as np
    vec = np.zeros_like(embeddings[0])
    total_w = 0.0
    for e,w in zip(embeddings, weights):
        vec += e * w
        total_w += w
    if total_w>0:
        vec = vec / total_w
    return vec, [{'skill':n,'weight':w} for n,w in zip(skill_names,weights)]

def cosine_sim(a,b):
    import numpy as np
    na = (a*a).sum()**0.5
    nb = (b*b).sum()**0.5
    if na==0 or nb==0:
        return 0.0
    return float((a*b).sum()/(na*nb))


def main():
    if not os.path.exists(PDF_PATH):
        raise FileNotFoundError(PDF_PATH)
    text = read_pdf_text(PDF_PATH)
    master_skills, master_rows = load_master_skills(MASTER_CSV)
    cv_skills = extract_skills_from_text(text, master_skills)

    # normalize tokens
    cv_skills = [s.strip().lower() for s in cv_skills if s and len(s)>1]

    # install and load sentence-transformers
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as e:
        raise RuntimeError('sentence-transformers not installed. Please run pip install sentence-transformers')

    model = SentenceTransformer('all-MiniLM-L6-v2')

    # user vector: average embeddings of skills
    import numpy as np
    if cv_skills:
        emb = model.encode(cv_skills, convert_to_tensor=False)
        user_vec = np.mean(np.array(emb), axis=0)
    else:
        user_vec = np.zeros(model.get_sentence_embedding_dimension())

    # target job titles (requested). We'll map requested names to available titles in master via fuzzy matching
    requested = ['Computer Systems Analysts','Business Intelligence Analysts','Management Analysts']
    # collect available titles
    available_titles = sorted(set([r['title'] for r in master_rows if r.get('title')]))
    # helper to match requested -> available
    from difflib import get_close_matches
    mapped = []
    for req in requested:
        if req in available_titles:
            mapped.append((req, req))
            continue
        m = get_close_matches(req, available_titles, n=1, cutoff=0.6)
        if m:
            mapped.append((req, m[0]))
            continue
        found = None
        for a in available_titles:
            al = a.lower()
            if 'management' in req.lower() and 'management' in al:
                found = a
                break
            if 'analyst' in req.lower() and 'analyst' in al:
                found = a
                break
        if found:
            mapped.append((req, found))
        else:
            mapped.append((req, None))

    results = {}
    def build_synthetic_vector(keywords, master_rows, model):
        # collect rows whose skill contains any keyword
        candidates = [r for r in master_rows if any(k in r['skill'] for k in keywords)]
        if not candidates:
            return None, []
        names = [c['skill'] for c in candidates]
        weights = [c['weight'] for c in candidates]
        emb = build_embeddings(names, model)
        import numpy as np
        vec = np.zeros_like(emb[0])
        total = 0.0
        for e,w in zip(emb, weights):
            vec += e * w
            total += w
        if total>0:
            vec = vec/total
        return vec, [{'skill':n,'weight':w} for n,w in zip(names,weights)]

    for req, mapped_title in mapped:
        # if we mapped to None or the requested is 'Management' category, build synthetic
        if (mapped_title is None) or ('management' in req.lower() and (not mapped_title or 'management' not in mapped_title.lower())):
            # keywords that represent management analyst profile
            keywords = ['operations analysis','quality control analysis','management of personnel resources','coordination','time management','judgment and decision making','project management','process']
            vec, skills_info = build_synthetic_vector(keywords, master_rows, model)
            used_title = 'Synthetic Management Analysts'
        else:
            vec, skills_info = weighted_job_vector(mapped_title, master_rows, model)
            used_title = mapped_title

        if vec is None:
            sim = 0.0
        else:
            sim = cosine_sim(user_vec, vec)
        # also get generate_match_report output (use mapped/used title when available)
        try:
            from matching_engine import generate_match_report
            # pass used_title when synthetic or mapped, fallback to req
            rep_title = used_title if used_title else req
            rep = generate_match_report(cv_skills, rep_title, master_csv=MASTER_CSV)
        except Exception:
            rep = {}
        results[req] = {
            'mapped_title': used_title,
            'similarity': round(sim,6),
            'similarity_percent': round(sim*100,3),
            'report': rep,
            'job_skill_count': len(skills_info)
        }

    out = {
        'cv_skills_extracted': cv_skills,
        'results': results
    }
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('Wrote', OUTPUT_JSON)

if __name__=='__main__':
    main()
