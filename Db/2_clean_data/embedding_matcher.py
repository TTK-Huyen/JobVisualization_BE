"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                    EMBEDDING-BASED SKILL MATCHING                             ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Find canonical skills using vector embedding + FAISS (no LLM)       ║
║ WORKFLOW: embed(skill) → FAISS vector search → return top-1                  ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""

import json
import sys
import numpy as np
from pathlib import Path

# Ensure current venv is in path for subprocess
venv_site_packages = Path(__file__).parent.parent.parent / ".venv" / "Lib" / "site-packages"
if venv_site_packages.exists() and str(venv_site_packages) not in sys.path:
    sys.path.insert(0, str(venv_site_packages))

# Lazy imports: SentenceTransformer and FAISS are imported inside __init__ to avoid loading during module import
# This prevents delays when embedding_matcher is first imported


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                     EMBEDDING MODEL & VECTOR DB                             ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

class EmbeddingMatcher:
    """Find top 5 canonical skills using semantic embeddings + FAISS."""
    
    def __init__(self, canonical_skills, embedding_model="all-MiniLM-L6-v2"):
        """
        Initialize embedding matcher with canonical skills.
        Cache FAISS index to avoid rebuilding each run.
        
        Args:
            canonical_skills: List of canonical skill names (5648 skills)
            embedding_model: Sentence-Transformers model (default: fast 384-dim)
        """
        print(f"[*] ⏳ Loading embedding model: {embedding_model} (this may take 1-2 minutes on first run...)")
        
        # LAZY IMPORT: Load both SentenceTransformer and FAISS here, not at module level
        # This prevents delays during initial import
        try:
            from sentence_transformers import SentenceTransformer
            print(f"[✓] sentence_transformers imported successfully")
        except ImportError as e:
            print(f"[ERROR] Failed to import sentence_transformers: {e}")
            print(f"[DEBUG] Python: {sys.executable}")
            print(f"[DEBUG] sys.path: {sys.path[:2]}")
            raise
        
        try:
            import faiss
            print(f"[✓] faiss imported successfully")
        except ImportError as e:
            print(f"[ERROR] Failed to import faiss: {e}")
            raise
        
        self.model = SentenceTransformer(embedding_model)
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        
        self.canonical_skills = canonical_skills
        self.skill_to_idx = {skill: idx for idx, skill in enumerate(canonical_skills)}
        
        # Check for cached FAISS index
        cache_dir = Path(__file__).parent / "cache"
        cache_dir.mkdir(exist_ok=True)
        faiss_index_file = cache_dir / "faiss_index.bin"
        embeddings_file = cache_dir / "embeddings.npy"
        skills_file = cache_dir / "skills_list.json"
        
        # Try to load from cache
        if faiss_index_file.exists() and embeddings_file.exists() and skills_file.exists():
            try:
                print(f"[*] Loading cached FAISS index...")
                self.index = faiss.read_index(str(faiss_index_file))
                self.embeddings = np.load(str(embeddings_file))
                
                with open(skills_file, 'r', encoding='utf-8') as f:
                    cached_skills = json.load(f)
                
                # Verify cache matches current skills
                if len(cached_skills) == len(canonical_skills):
                    print(f"[+] FAISS index loaded from cache: {len(canonical_skills)} skills, {self.embedding_dim}-dim vectors")
                    return
                else:
                    print(f"[!] Cache mismatch ({len(cached_skills)} vs {len(canonical_skills)}), rebuilding...")
            except Exception as e:
                print(f"[!] Cache load error: {str(e)}, rebuilding...")
        
        # Build new FAISS index if cache doesn't exist
        print(f"[*] Building FAISS index for {len(canonical_skills)} skills...")
        self.index = faiss.IndexFlatL2(self.embedding_dim)
        
        # Embed all canonical skills
        print(f"[*] Embedding {len(canonical_skills)} canonical skills...")
        embeddings = self.model.encode(canonical_skills, convert_to_numpy=True)
        embeddings = embeddings.astype(np.float32)
        
        self.index.add(embeddings)
        self.embeddings = embeddings
        
        # Save to cache
        print(f"[*] Caching FAISS index...")
        faiss.write_index(self.index, str(faiss_index_file))
        np.save(str(embeddings_file), embeddings)
        with open(skills_file, 'w', encoding='utf-8') as f:
            json.dump(canonical_skills, f, ensure_ascii=False)
        
        print(f"[+] FAISS index ready: {len(canonical_skills)} skills, {self.embedding_dim}-dim vectors")
    
    def find_top_5(self, skill_name, k=5):
        """
        Find top k most similar canonical skills.
        
        Args:
            skill_name: Raw skill name to match
            k: Number of candidates to return (default: 5)
            
        Returns:
            List of (canonical_skill, distance) tuples
        """
        # Embed the query skill
        query_embedding = self.model.encode([skill_name], convert_to_numpy=True).astype(np.float32)
        
        # Search FAISS index
        distances, indices = self.index.search(query_embedding, k)
        
        # Convert to (skill, distance) tuples
        results = []
        for idx, distance in zip(indices[0], distances[0]):
            skill = self.canonical_skills[idx]
            results.append((skill, float(distance)))
        
        return results
    
    def get_embedding(self, skill_name):
        """Get embedding vector for a skill."""
        return self.model.encode([skill_name])[0]


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                    EMBEDDING-ONLY NORMALIZE FUNCTION                         ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def normalize_skill_embedding(
    raw_skill,
    matcher,
    cache=None,
    use_cache=True
):
    """
    Normalize skill using embedding (no LLM verification).
    
    Pipeline:
    1. Check cache
    2. Find top 5 using embedding
    3. Take top-1 as normalized skill
    4. Save to cache
    
    Args:
        raw_skill: Raw skill name
        matcher: EmbeddingMatcher instance
        cache: Normalized skill cache dict
        use_cache: Whether to use caching
        
    Returns:
        (normalized_skill, confidence, match_type)
    """
    if cache is None:
        cache = {}
    
    skill_lower = raw_skill.lower().strip()
    
    # Check cache
    if use_cache and skill_lower in cache:
        cached = cache[skill_lower]
        print(f"   💾 Cache hit: {raw_skill} → {cached[0]}")
        return tuple(cached)
    
    # Find top 5 candidates
    top_5 = matcher.find_top_5(raw_skill, k=5)
    
    print(f"   🔍 Top 5 for '{raw_skill}':")
    for skill, dist in top_5:
        print(f"      • {skill} (distance={dist:.3f})")
    
    # Use top-1 match
    best_match, distance = top_5[0]
    confidence = max(0, int(100 - distance * 50))  # Convert distance to confidence
    
    print(f"   ✅ Matched: {raw_skill} → {best_match} (conf={confidence}%)")
    result = (best_match, None, "embedding")
    
    # Cache result
    if use_cache:
        cache[skill_lower] = list(result)
    
    return result


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                          BATCH PROCESSING                                   ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def normalize_skills_batch(
    raw_skills,
    matcher,
    cache=None,
    use_cache=True
):
    """
    Normalize multiple skills using embedding only.
    
    Args:
        raw_skills: List of raw skill names
        matcher: EmbeddingMatcher instance
        cache: Normalized skill cache dict
        use_cache: Whether to use caching
        
    Returns:
        Dict of {raw_skill: (normalized, category, match_type)}
    """
    if cache is None:
        cache = {}
    
    results = {}
    for skill in raw_skills:
        normalized, category, match_type = normalize_skill_embedding(
            skill, matcher, cache, use_cache
        )
        results[skill] = (normalized, category, match_type)
    
    return results


if __name__ == "__main__":
    # Test
    print("[*] Testing embedding matcher...")
    
    # Mock canonical skills
    canonical = ["Python", "JavaScript", "React", "Node.js", "Docker", "Kubernetes"]
    
    # Initialize
    matcher = EmbeddingMatcher(canonical)
    
    # Test queries
    test_skills = ["pythondev", "node", "react native", "k8s"]
    
    for skill in test_skills:
        top_5 = matcher.find_top_5(skill)
        print(f"\n'{skill}' → Top 5:")
        for cand, dist in top_5:
            print(f"  {cand} (dist={dist:.3f})")
