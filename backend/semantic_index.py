import json
import os
import threading
from pathlib import Path
from typing import List, Dict, Tuple
import numpy as np
import ollama

_lock = threading.Lock()

def _index_dir(name: str) -> Path:
    workspace = Path(os.getenv("WORKSPACE_ROOT", "D:/Quill-Cowork/workspace")).resolve()
    safe = "".join(c for c in str(name) if c.isalnum() or c in "-_.").strip("-_.")
    return workspace / ".quill" / "codebases" / safe

def _get_client():
    return ollama.Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"))

def _embed(text: str) -> List[float]:
    client = _get_client()
    # Use nomic-embed-text which the user already has installed
    r = client.embed(model="nomic-embed-text", input=text)
    vecs = r.get("embeddings") if isinstance(r, dict) else getattr(r, "embeddings", None)
    if vecs:
        return list(vecs[0])
    raise RuntimeError("Failed to generate embedding")

def _chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
    """Split code into overlapping chunks."""
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        # Try to find a newline near the end to avoid cutting mid-line
        if end < len(text):
            last_nl = text.rfind('\n', start, end)
            if last_nl != -1 and last_nl > start + chunk_size - 400:
                end = last_nl + 1
        
        chunks.append(text[start:end])
        start = end - overlap
    return chunks

def build_index(name: str) -> str:
    """Reads the Rust files.jsonl and builds an embedding matrix."""
    idx = _index_dir(name)
    files_jsonl = idx / "files.jsonl"
    if not files_jsonl.exists():
        return f"no index for '{name}'"

    chunks_meta = []
    all_texts = []

    with files_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not rec.get("content"):
                continue
                
            text = rec["content"]
            file_chunks = _chunk_text(text)
            
            for i, chunk in enumerate(file_chunks):
                chunks_meta.append({
                    "path": rec["path"],
                    "chunk_idx": i,
                    "text": chunk
                })
                all_texts.append(chunk)

    if not all_texts:
        return "no text to embed"

    print(f"[semantic] Embedding {len(all_texts)} chunks for '{name}' (this may take a minute)...")
    matrix = []
    client = _get_client()
    
    # Batch processing for speed
    batch_size = 32
    for i in range(0, len(all_texts), batch_size):
        batch = all_texts[i:i+batch_size]
        try:
            r = client.embed(model="nomic-embed-text", input=batch)
            vecs = r.get("embeddings") if isinstance(r, dict) else getattr(r, "embeddings", None)
            if vecs:
                matrix.extend(vecs)
        except Exception as e:
            print(f"[semantic] Batch error: {e}")
            # Fallback to one-by-one if batch fails
            for t in batch:
                matrix.append(_embed(t))

    if not matrix:
        return "failed to generate embeddings"

    # Save matrix and metadata
    mat_np = np.array(matrix, dtype=np.float32)
    np.save(idx / "embeddings.npy", mat_np)
    
    meta_path = idx / "embeddings_meta.json"
    meta_path.write_text(json.dumps(chunks_meta), encoding="utf-8")
    
    return f"indexed {len(all_texts)} chunks"

def search(name: str, query: str, top_k: int = 5) -> str:
    """Semantic search using cosine similarity."""
    idx = _index_dir(name)
    mat_path = idx / "embeddings.npy"
    meta_path = idx / "embeddings_meta.json"
    
    if not mat_path.exists() or not meta_path.exists():
        return "semantic index not built yet. please run codebase_semantic_index first."
        
    try:
        matrix = np.load(mat_path)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"failed to load semantic index: {e}"

    q_vec = _embed(query)
    q = np.array(q_vec, dtype=np.float32)
    
    # Normalize for cosine similarity
    matrix_norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix_norms[matrix_norms == 0] = 1e-10
    matrix_norm = matrix / matrix_norms
    
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return "empty query"
    q_normed = q / q_norm
    
    sims = np.dot(matrix_norm, q_normed)
    top_indices = np.argsort(sims)[-top_k:][::-1]

    results = []
    for i in top_indices:
        sim = float(sims[i])
        if sim < 0.3:  # threshold
            continue
        m = meta[i]
        snippet = m["text"][:600].replace("\n", " ")
        results.append(f"[{sim:.2f}] {m['path']}\n    {snippet}...")
        
    if not results:
        return f"no semantic matches for '{query}'"
        
    return "\n\n".join(results)

def has_index(name: str) -> bool:
    idx = _index_dir(name)
    return (idx / "embeddings.npy").exists()