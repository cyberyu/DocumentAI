import csv
import os
import psycopg2
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel

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
MODEL_ID = "ProsusAI/finbert"
OUT_CSV = "/tmp/all_chunks_finbert_similarity_g3027.csv"


def mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    summed = torch.sum(last_hidden_state * mask, dim=1)
    counts = torch.clamp(mask.sum(dim=1), min=1e-9)
    return summed / counts


def embed_batch(tokenizer, model, texts, device):
    enc = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    ).to(device)
    with torch.no_grad():
        out = model(**enc)
    pooled = mean_pool(out.last_hidden_state, enc["attention_mask"])
    return F.normalize(pooled, p=2, dim=1).cpu()


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
    cur.execute(
        """
        SELECT c.id, c.content
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.search_space_id = 1
        ORDER BY c.id
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    ids = [r[0] for r in rows]
    texts = [r[1] for r in rows]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID).to(device)
    model.eval()

    q_vec = embed_batch(tokenizer, model, [QUERY], device)[0]

    batch_size = 32
    sims = []
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i + batch_size]
        batch_vecs = embed_batch(tokenizer, model, batch_texts, device)
        batch_sims = torch.mv(batch_vecs, q_vec)
        sims.extend(batch_sims.tolist())

    ranked = []
    for cid, txt, sim in zip(ids, texts, sims):
        ranked.append((cid, float(sim), txt.replace("\n", " ")[:200]))

    ranked.sort(key=lambda x: x[1], reverse=True)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "chunk_id", "cosine_similarity", "snippet"])
        for rank, (cid, sim, snip) in enumerate(ranked, start=1):
            w.writerow([rank, cid, f"{sim:.9f}", snip])

    target_rank = None
    target_sim = None
    for rank, (cid, sim, _) in enumerate(ranked, start=1):
        if cid == 11530:
            target_rank = rank
            target_sim = sim
            break

    print(f"model={MODEL_ID}")
    print(f"chunk_count={len(ranked)}")
    print(f"output_csv={OUT_CSV}")
    print(f"target_11530_rank={target_rank}")
    print(f"target_11530_similarity={target_sim:.9f}" if target_sim is not None else "target_11530_similarity=None")
    print("top10:")
    for rank, (cid, sim, snip) in list(enumerate(ranked, start=1))[:10]:
        print(f"{rank:2d}. id={cid} cos={sim:.9f} :: {snip}")


if __name__ == "__main__":
    main()
