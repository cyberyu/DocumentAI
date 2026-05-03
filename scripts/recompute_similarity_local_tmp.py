import os
import psycopg2
import numpy as np
from sentence_transformers import SentenceTransformer

QUERY = (
    "In MSFT_FY26Q1_10Q.docx, what was the change in the total dollar amount "
    "of common stock repurchased between the First Quarter of Fiscal Year 2025 "
    "and the First Quarter of Fiscal Year 2026? Return only the numeric change "
    "with sign and unit. Search the full document before answering (not only the first retrieved chunk). "
    "If the answer is not in the first retrieved chunk, continue retrieval silently until found. "
    "Do not mention tools, chunks, file-reading steps, or inability to access content. "
    "If multiple candidates appear, select the value explicitly tied to September 30, 2025. "
    "For amount-or-rate questions, return a numeric amount or percentage, not qualitative labels (e.g., not AAA). "
    "Report monetary values in the exact unit and scale used in the source document (e.g., USD millions). "
    "Do not round or restate values in a different scale (e.g., do not convert millions to billions). "
    "Return only one final value with unit and no extra prose."
)
CHUNK_IDS = [11572, 11449, 11596, 11564, 11518, 11440, 11534, 11491, 11511, 11497, 11530]


def main() -> None:
    db_ip = os.popen("docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' surfsense-db-1").read().strip()

    conn = psycopg2.connect(
        host=db_ip,
        port=5432,
        dbname="surfsense",
        user="surfsense",
        password="surfsense",
    )
    cur = conn.cursor()
    cur.execute("SELECT id, content FROM chunks WHERE id = ANY(%s)", (CHUNK_IDS,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    text_by_id = {cid: txt for cid, txt in rows}

    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    qv = model.encode([QUERY], normalize_embeddings=True)[0]

    out = []
    for cid in CHUNK_IDS:
        txt = text_by_id.get(cid, "")
        cv = model.encode([txt], normalize_embeddings=True)[0]
        cos = float(np.dot(qv, cv))
        out.append((cid, cos, txt.replace("\n", " ")[:140]))

    out.sort(key=lambda x: x[1], reverse=True)
    print("local_recomputed_similarity_cosine_top11")
    for i, (cid, cos, snip) in enumerate(out, 1):
        print(f"{i:2d}. id={cid} cos={cos:.6f} :: {snip}")

    a = next(x for x in out if x[0] == 11530)
    b = next(x for x in out if x[0] == 11497)
    print("focus_compare")
    print(f"chunk 11530 cos={a[1]:.6f}")
    print(f"chunk 11497 cos={b[1]:.6f}")
    print(f"delta(11497-11530)={b[1] - a[1]:.6f}")


if __name__ == "__main__":
    main()
