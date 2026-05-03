import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Sequence

import numpy as np
import psycopg2
from sentence_transformers import SentenceTransformer

QUERY = (
    "In MSFT_FY26Q1_10Q.docx, what was the change in the total dollar amount "
    "of common stock repurchased between the First Quarter of Fiscal Year 2025 "
    "and the First Quarter of Fiscal Year 2026? Return only the numeric change "
    "with sign and unit."
)
TARGET_CHUNK_ID = 11530
COMPARE_CHUNK_ID = 11497
SEARCH_SPACE_ID = 1


@dataclass
class Result:
    name: str
    target_rank: int
    target_score: float
    compare_rank: int
    compare_score: float
    top5: List[int]


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def bm25_scores(query: str, docs: Sequence[str], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    tokenized_docs = [tokenize(d) for d in docs]
    query_terms = tokenize(query)

    n_docs = len(tokenized_docs)
    doc_lens = np.array([len(d) for d in tokenized_docs], dtype=np.float32)
    avgdl = float(np.mean(doc_lens)) if n_docs else 0.0

    df = Counter()
    tf = []
    for doc in tokenized_docs:
        counts = Counter(doc)
        tf.append(counts)
        for term in counts.keys():
            df[term] += 1

    idf = {}
    for term in query_terms:
        n_q = df.get(term, 0)
        idf[term] = math.log(1.0 + (n_docs - n_q + 0.5) / (n_q + 0.5))

    scores = np.zeros(n_docs, dtype=np.float32)
    for i, counts in enumerate(tf):
        dl = doc_lens[i]
        denom_norm = k1 * (1.0 - b + b * dl / avgdl) if avgdl > 0 else k1
        s = 0.0
        for term in query_terms:
            f = counts.get(term, 0)
            if f == 0:
                continue
            numer = f * (k1 + 1.0)
            denom = f + denom_norm
            s += idf[term] * (numer / denom)
        scores[i] = s
    return scores


def cosine_scores(model: SentenceTransformer, query: str, docs: Sequence[str], doc_prefix: str = "", query_prefix: str = "") -> np.ndarray:
    q = query_prefix + query
    prefixed_docs = [doc_prefix + d for d in docs]
    q_vec = model.encode([q], normalize_embeddings=True, show_progress_bar=False)
    d_vecs = model.encode(prefixed_docs, normalize_embeddings=True, show_progress_bar=False)
    scores = np.dot(d_vecs, q_vec[0])
    return scores.astype(np.float32)


def rank_result(name: str, ids: Sequence[int], scores: np.ndarray) -> Result:
    order = np.argsort(-scores)
    ranked_ids = [ids[i] for i in order]
    ranked_scores = [float(scores[i]) for i in order]

    target_idx = ranked_ids.index(TARGET_CHUNK_ID)
    compare_idx = ranked_ids.index(COMPARE_CHUNK_ID)

    return Result(
        name=name,
        target_rank=target_idx + 1,
        target_score=ranked_scores[target_idx],
        compare_rank=compare_idx + 1,
        compare_score=ranked_scores[compare_idx],
        top5=ranked_ids[:5],
    )


def fetch_chunks() -> tuple[List[int], List[str]]:
    db_ip = os.popen("docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' surfsense-db-1").read().strip()
    conn = psycopg2.connect(
        host=db_ip,
        port=5432,
        dbname="surfsense",
        user="surfsense",
        password="surfsense",
    )
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.content
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.search_space_id = %s
        ORDER BY c.id
        """,
        (SEARCH_SPACE_ID,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    ids = [int(r[0]) for r in rows]
    texts = [str(r[1]) for r in rows]
    return ids, texts


def main() -> None:
    ids, docs = fetch_chunks()

    results: List[Result] = []

    # Lexical baseline often helps exact table-row match queries.
    bm = bm25_scores(QUERY, docs)
    results.append(rank_result("bm25", ids, bm))

    model_specs: List[tuple[str, str, str, str]] = [
        ("all-MiniLM-L6-v2", "sentence-transformers/all-MiniLM-L6-v2", "", ""),
        ("bge-small-en-v1.5", "BAAI/bge-small-en-v1.5", "", ""),
        ("e5-small-v2", "intfloat/e5-small-v2", "passage: ", "query: "),
        ("gte-small", "thenlper/gte-small", "", ""),
    ]

    for name, model_id, doc_prefix, query_prefix in model_specs:
        try:
            model = SentenceTransformer(model_id)
            scores = cosine_scores(model, QUERY, docs, doc_prefix=doc_prefix, query_prefix=query_prefix)
            results.append(rank_result(name, ids, scores))
        except Exception as e:
            print(f"model_failed={name} error={type(e).__name__}: {e}")

    print(f"chunk_count={len(ids)}")
    print(f"target_chunk={TARGET_CHUNK_ID} compare_chunk={COMPARE_CHUNK_ID}")
    print("\n=== Retriever Comparison (lower rank is better) ===")
    for r in results:
        print(
            f"{r.name:20s} target_rank={r.target_rank:3d} target_score={r.target_score:.6f} "
            f"compare_rank={r.compare_rank:3d} compare_score={r.compare_score:.6f} top5={r.top5}"
        )


if __name__ == "__main__":
    main()
