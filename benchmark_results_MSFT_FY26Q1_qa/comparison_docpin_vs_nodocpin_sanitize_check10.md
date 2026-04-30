# Side-by-Side Comparison: no-docpin+sanitize vs docpin+sanitize (10Q)

## Before Model Call
- no-docpin `document_title_contains`: `None`
- no-docpin `mentioned_document_ids`: `[]`
- docpin `document_title_contains`: `MSFT_FY26Q1_10Q`
- docpin `mentioned_document_ids`: `[4]`
- `asked_question` identical in `10/10` questions

## After Model Response (per question)
| ID | no-docpin overall/num/unit | docpin overall/num/unit | no-docpin pred (short) | docpin pred (short) |
|---|---|---|---|---|
| G1-001 | Y/Y/Y | N/Y/Y | The requested value is not present in the first chunk. I will now proceed to read the rema | The long-term accounts receivable, net of allowance for doubtful accounts as of September  |
| G1-002 | Y/Y/Y | N/N/N | $14.4 billion | I was not able to find the specific value for "other receivables related to activities to  |
| G1-003 | Y/Y/Y | N/N/N | The information regarding "financing receivables, net as of September 30, 2025" is located | Financing receivables, net as of September 30, 2025, is not available in the retrieved chu |
| G1-004 | N/N/N | N/N/N | The net loss from investments in OpenAI for the three months ended September 30, 2025, is  | The net loss from investments in OpenAI for the three months ended September 30, 2025, is  |
| G1-005 | Y/Y/Y | N/N/Y | $2.9 billion | Equity investments without readily determinable fair values measured at cost with adjustme |
| G1-006 | Y/Y/Y | N/N/N | As of September 30, 2025, equity investments measured using the equity method were $1.8 bi | The document is very large, and the initial read returned only a segment of the content. I |
| G1-007 | N/Y/Y | Y/Y/Y | $1.0 billion | The requested information is not present in the first retrieved document segment. I will a |
| G1-008 | N/N/N | N/N/N | I am unable to locate the file `MSFT_FY26Q1_10Q.docx` in the current document directory to | The specific figure for "Gross derivative assets and liabilities subject to legally enforc |
| G1-009 | Y/Y/Y | N/N/N | Depreciation expense was $7.1 billion for the three months ended September 30, 2025. | Depreciation expense as of September 30, 2025, was not found in the initial retrieval. Due |
| G1-010 | N/N/N | N/N/N | I do not have enough information to answer your question. The initial chunk index and the  | Intangible assets amortization expense as of September 30, 2025: $\text{Not found}$ |

## Summary
- no-docpin+sanitize: overall `6/10`, number `7/10`, unit `7/10`
- docpin+sanitize: overall `1/10`, number `2/10`, unit `3/10`
