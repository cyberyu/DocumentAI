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
CHUNK_IDS = [11572, 11449, 11596, 11564, 11518, 11440, 11534, 11491, 11511, 11497, 11530]
MODEL_ID = "ProsusAI/finbert"


def mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    summed = torch.sum(last_hidden_state * mask, dim=1)
    counts = torch.clamp(mask.sum(dim=1), min=1e-9)
    return summed / counts


def embed_texts(tokenizer, model, texts, device):
    encoded = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    ).to(device)
    with torch.no_grad():
        outputs = model(**encoded)
    pooled = mean_pool(outputs.last_hidden_state, encoded["attention_mask"])
    return F.normalize(pooled, p=2, dim=1)


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

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID).to(device)
    model.eval()

    texts = [QUERY] + [text_by_id.get(cid, "") for cid in CHUNK_IDS]
    embs = embed_texts(tokenizer, model, texts, device)

    q = embs[0]
    out = []
    for i, cid in enumerate(CHUNK_IDS, start=1):
        c = embs[i]
        cos = torch.dot(q, c).item()
        snip = text_by_id.get(cid, "").replace("\n", " ")[:140]
        out.append((cid, cos, snip))

    out.sort(key=lambda x: x[1], reverse=True)
    print(f"financial_embedding_model={MODEL_ID}")
    print("financial_embedding_similarity_cosine_top11")
    for rank, (cid, cos, snip) in enumerate(out, 1):
        print(f"{rank:2d}. id={cid} cos={cos:.6f} :: {snip}")

    c11530 = next(x for x in out if x[0] == 11530)
    c11497 = next(x for x in out if x[0] == 11497)
    print("focus_compare")
    print(f"chunk 11530 cos={c11530[1]:.6f}")
    print(f"chunk 11497 cos={c11497[1]:.6f}")
    print(f"delta(11497-11530)={c11497[1] - c11530[1]:.6f}")


if __name__ == "__main__":
    main()
