# MSFT FY26Q1 10-Q Benchmark QAs

Total pairs: 100

vllm serve google/gemma-4-E4B-it   --port 8000   --max-model-len 61072   --limit-mm-per-prompt '{"image": 0, "audio": 0}'   --gpu-memory-utilization 0.78   --enable-auto-tool-choice   --tool-call-parser gemma4

Benchmark complete
  overall_correct: 26 / 100 (26.00%)
  normalized_exact: 1 / 100 (1.00%)
  number_match: 46 / 100 (46.00%)
  unit_match: 67 / 100 (67.00%)
  mean_token_f1: 0.1173
  request_failures: 0
  context_overflow_failures: 0
  output_json: benchmark_results_MSFT_FY26Q1_qa/full100_live.json
  output_md: benchmark_results_MSFT_FY26Q1_qa/full100_live.md

## Counts

- Group1 (paragraph-direct): 30
- Group2 (table row/column lookup): 40
- Group3 (multi-step inference): 30

## Group1

### G1-001
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "As of September 30, 2025 and June 30, 2025, long-term accounts receivable, net of allowance for doubtful accounts, was $5.0 billion and $5.2 billion, respectively, and is included in other long-term assets in our consolidated balance sheets."?
A: $5.0 billion USD
Evidence: {'text': 'As of September 30, 2025 and June 30, 2025, long-term accounts receivable, net of allowance for doubtful accounts, was $5.0 billion and $5.2 billion, respectively, and is included in other long-term assets in our consolidated balance sheets.', 'page_number': 12, 'line_number': 234, 'start_offset': 119, 'end_offset': 123, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-002
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "As of September 30, 2025 and June 30, 2025, other receivables related to activities to facilitate the purchase of server components were $14.4 billion and $8.2 billion, respectively, and are included in other current assets in our consolidated balance sheets."?
A: $14.4 billion USD
Evidence: {'text': 'As of September 30, 2025 and June 30, 2025, other receivables related to activities to facilitate the purchase of server components were $14.4 billion and $8.2 billion, respectively, and are included in other current assets in our consolidated balance sheets.', 'page_number': 12, 'line_number': 235, 'start_offset': 137, 'end_offset': 142, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-003
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "As of September 30, 2025 and June 30, 2025, our financing receivables, net were $3.9 billion and $4.3 billion, respectively, for short-term and long-term financing receivables, which are included in other current assets and other long-term assets in our consolidated balance sheets."?
A: $3.9 billion USD
Evidence: {'text': 'As of September 30, 2025 and June 30, 2025, our financing receivables, net were $3.9 billion and $4.3 billion, respectively, for short-term and long-term financing receivables, which are included in other current assets and other long-term assets in our consolidated balance sheets.', 'page_number': 12, 'line_number': 236, 'start_offset': 80, 'end_offset': 84, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-004
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "For the three months ended September 30, 2025 and 2024, other income (expense), net included $4.1 billion and $688 million, respectively, of net losses from investments in OpenAI, primarily net recognized losses on our equity method investment reflected in other, net."?
A: $4.1 billion USD
Evidence: {'text': 'For the three months ended September 30, 2025 and 2024, other income (expense), net included $4.1 billion and $688 million, respectively, of net losses from investments in OpenAI, primarily net recognized losses on our equity method investment reflected in other, net.', 'page_number': 13, 'line_number': 267, 'start_offset': 93, 'end_offset': 97, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-005
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "As of both September 30, 2025 and June 30, 2025, equity investments without readily determinable fair values measured at cost with adjustments for observable changes in price or impairments were $2.9 billion."?
A: $2.9 billion USD
Evidence: {'text': 'As of both September 30, 2025 and June 30, 2025, equity investments without readily determinable fair values measured at cost with adjustments for observable changes in price or impairments were $2.9 billion.', 'page_number': 14, 'line_number': 329, 'start_offset': 195, 'end_offset': 199, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-006
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "As of September 30, 2025 and June 30, 2025, equity investments measured using the equity method were $1.8 billion and $6.0 billion, respectively."?
A: $1.8 billion USD
Evidence: {'text': 'As of September 30, 2025 and June 30, 2025, equity investments measured using the equity method were $1.8 billion and $6.0 billion, respectively.', 'page_number': 14, 'line_number': 329, 'start_offset': 101, 'end_offset': 105, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-007
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "As of September 30, 2025, our long-term unsecured debt rating was AAA, and cash investments were in excess of $1.0 billion."?
A: $1.0 billion USD
Evidence: {'text': 'As of September 30, 2025, our long-term unsecured debt rating was AAA, and cash investments were in excess of $1.0 billion.', 'page_number': 15, 'line_number': 374, 'start_offset': 110, 'end_offset': 114, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-008
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "Gross derivative assets and liabilities subject to legally enforceable master netting agreements for which we have elected to offset were $376 million and $802 million, respectively, as of September 30, 2025, and $452 million and $1.8 billion, respectively, as of June 30, 2025."?
A: $376 million USD
Evidence: {'text': 'Gross derivative assets and liabilities subject to legally enforceable master netting agreements for which we have elected to offset were $376 million and $802 million, respectively, as of September 30, 2025, and $452 million and $1.8 billion, respectively, as of June 30, 2025.', 'page_number': 16, 'line_number': 411, 'start_offset': 138, 'end_offset': 142, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-009
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "Depreciation expense was $7.1 billion and $4.7 billion for the three months ended September 30, 2025 and 2024, respectively."?
A: $7.1 billion USD
Evidence: {'text': 'Depreciation expense was $7.1 billion and $4.7 billion for the three months ended September 30, 2025 and 2024, respectively.', 'page_number': 17, 'line_number': 452, 'start_offset': 25, 'end_offset': 29, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-010
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "Intangible assets amortization expense was $1.5 billion and $1.4 billion for the three months ended September 30, 2025 and 2024, respectively."?
A: $1.5 billion USD
Evidence: {'text': 'Intangible assets amortization expense was $1.5 billion and $1.4 billion for the three months ended September 30, 2025 and 2024, respectively.', 'page_number': 18, 'line_number': 472, 'start_offset': 43, 'end_offset': 47, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-011
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "Our effective tax rate was 19% for both the three months ended September 30, 2025 and 2024."?
A: 19%
Evidence: {'text': 'Our effective tax rate was 19% for both the three months ended September 30, 2025 and 2024.', 'page_number': 19, 'line_number': 521, 'start_offset': 27, 'end_offset': 30, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-012
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "As of September 30, 2025 and June 30, 2025, unrecognized tax benefits and other income tax liabilities were $28.0 billion and $27.4 billion, respectively, and are included in long-term income taxes in our consolidated balance sheets."?
A: $28.0 billion USD
Evidence: {'text': 'As of September 30, 2025 and June 30, 2025, unrecognized tax benefits and other income tax liabilities were $28.0 billion and $27.4 billion, respectively, and are included in long-term income taxes in our consolidated balance sheets.', 'page_number': 20, 'line_number': 524, 'start_offset': 108, 'end_offset': 113, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-013
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "In the NOPAs, the IRS is seeking an additional tax payment of $28.9 billion plus penalties and interest."?
A: $28.9 billion USD
Evidence: {'text': 'In the NOPAs, the IRS is seeking an additional tax payment of $28.9 billion plus penalties and interest.', 'page_number': 20, 'line_number': 525, 'start_offset': 62, 'end_offset': 67, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-014
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "Revenue allocated to remaining performance obligations, which includes unearned revenue and amounts that will be invoiced and recognized as revenue in future periods, was $398 billion as of September 30, 2025, of which $392 billion is related to the commercial portion of revenue."?
A: $398 billion USD
Evidence: {'text': 'Revenue allocated to remaining performance obligations, which includes unearned revenue and amounts that will be invoiced and recognized as revenue in future periods, was $398 billion as of September 30, 2025, of which $392 billion is related to the commercial portion of revenue.', 'page_number': 20, 'line_number': 542, 'start_offset': 171, 'end_offset': 175, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-015
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "We expect to recognize approximately 40% of our total company remaining performance obligation revenue over the next 12 months and the remainder thereafter."?
A: 40%
Evidence: {'text': 'We expect to recognize approximately 40% of our total company remaining performance obligation revenue over the next 12 months and the remainder thereafter.', 'page_number': 20, 'line_number': 542, 'start_offset': 37, 'end_offset': 40, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-016
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "As of September 30, 2025, we accrued aggregate legal liabilities of $530 million."?
A: $530 million USD
Evidence: {'text': 'As of September 30, 2025, we accrued aggregate legal liabilities of $530 million.', 'page_number': 22, 'line_number': 602, 'start_offset': 68, 'end_offset': 72, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-017
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "The above table excludes shares repurchased to settle employee tax withholding related to the vesting of stock awards of $1.7 billion and $1.3 billion for the three months ended September 30, 2025 and 2024, respectively."?
A: $1.7 billion USD
Evidence: {'text': 'The above table excludes shares repurchased to settle employee tax withholding related to the vesting of stock awards of $1.7 billion and $1.3 billion for the three months ended September 30, 2025 and 2024, respectively.', 'page_number': 23, 'line_number': 611, 'start_offset': 121, 'end_offset': 125, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-018
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "No sales to an individual customer or country other than the United States accounted for more than 10% of revenue for the three months ended September 30, 2025 or 2024."?
A: 10%
Evidence: {'text': 'No sales to an individual customer or country other than the United States accounted for more than 10% of revenue for the three months ended September 30, 2025 or 2024.', 'page_number': 26, 'line_number': 688, 'start_offset': 99, 'end_offset': 102, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-019
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "Our Microsoft Cloud revenue, which includes Microsoft 365 Commercial cloud, Azure and other cloud services, the commercial portion of LinkedIn, and Dynamics 365, was $49.1 billion and $38.9 billion for the three months ended September 30, 2025 and 2024, respectively."?
A: $49.1 billion USD
Evidence: {'text': 'Our Microsoft Cloud revenue, which includes Microsoft 365 Commercial cloud, Azure and other cloud services, the commercial portion of LinkedIn, and Dynamics 365, was $49.1 billion and $38.9 billion for the three months ended September 30, 2025 and 2024, respectively.', 'page_number': 27, 'line_number': 709, 'start_offset': 166, 'end_offset': 171, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-020
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "Under the new agreement, OpenAI has contracted to purchase an incremental $250 billion of Azure services, and Microsoft will no longer have a right of first refusal to be OpenAI's compute provider."?
A: $250 billion USD
Evidence: {'text': "Under the new agreement, OpenAI has contracted to purchase an incremental $250 billion of Azure services, and Microsoft will no longer have a right of first refusal to be OpenAI's compute provider.", 'page_number': 27, 'line_number': 712, 'start_offset': 74, 'end_offset': 78, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-021
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "•Microsoft Cloud revenue increased 26% to $49.1 billion."?
A: 26%
Evidence: {'text': '•Microsoft Cloud revenue increased 26% to $49.1 billion.', 'page_number': 30, 'line_number': 733, 'start_offset': 35, 'end_offset': 38, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-022
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "•Commercial remaining performance obligation increased 51% to $392 billion."?
A: 51%
Evidence: {'text': '•Commercial remaining performance obligation increased 51% to $392 billion.', 'page_number': 30, 'line_number': 734, 'start_offset': 55, 'end_offset': 58, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-023
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "•Microsoft 365 Commercial cloud revenue increased 17%."?
A: 17%
Evidence: {'text': '•Microsoft 365 Commercial cloud revenue increased 17%.', 'page_number': 30, 'line_number': 735, 'start_offset': 50, 'end_offset': 53, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-024
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "•Microsoft 365 Consumer cloud revenue increased 26%."?
A: 26%
Evidence: {'text': '•Microsoft 365 Consumer cloud revenue increased 26%.', 'page_number': 30, 'line_number': 736, 'start_offset': 48, 'end_offset': 51, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-025
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "•Dynamics 365 revenue increased 18%."?
A: 18%
Evidence: {'text': '•Dynamics 365 revenue increased 18%.', 'page_number': 30, 'line_number': 738, 'start_offset': 32, 'end_offset': 35, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-026
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "•Azure and other cloud services revenue increased 40%."?
A: 40%
Evidence: {'text': '•Azure and other cloud services revenue increased 40%.', 'page_number': 30, 'line_number': 739, 'start_offset': 50, 'end_offset': 53, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-027
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "•Windows OEM and Devices revenue increased 6%."?
A: 6%
Evidence: {'text': '•Windows OEM and Devices revenue increased 6%.', 'page_number': 30, 'line_number': 740, 'start_offset': 43, 'end_offset': 45, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-028
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "•Xbox content and services revenue increased 1%."?
A: 1%
Evidence: {'text': '•Xbox content and services revenue increased 1%.', 'page_number': 30, 'line_number': 741, 'start_offset': 45, 'end_offset': 47, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-029
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "•Search and news advertising revenue excluding traffic acquisition costs increased 16%."?
A: 16%
Evidence: {'text': '•Search and news advertising revenue excluding traffic acquisition costs increased 16%.', 'page_number': 30, 'line_number': 742, 'start_offset': 83, 'end_offset': 86, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G1-030
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported amount or rate in this sentence: "Revenue increased $12.1 billion or 18% with growth across each of our segments."?
A: $12.1 billion USD
Evidence: {'text': 'Revenue increased $12.1 billion or 18% with growth across each of our segments.', 'page_number': 33, 'line_number': 791, 'start_offset': 18, 'end_offset': 23, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

## Group2

### G2-001
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Common Stock, $0.00000625 par value per share' under 'column 4'?
A: 7,432,377,655 shares
Evidence: {'text': 'Common Stock, $0.00000625 par value per share | | | 7,432,377,655 shares | |', 'page_number': 1, 'line_number': 32, 'start_offset': 52, 'end_offset': 72, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-002
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Product' under 'column 4'?
A: 15,922 USD
Evidence: {'text': 'Product | | $ | 15,922 | | | $ | 15,272 |', 'page_number': 3, 'line_number': 63, 'start_offset': 16, 'end_offset': 22, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-003
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Service and other' under 'column 4'?
A: 61,751 USD million
Evidence: {'text': 'Service and other | | | 61,751 | | | | 50,313 |', 'page_number': 3, 'line_number': 64, 'start_offset': 24, 'end_offset': 30, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-004
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Total revenue' under 'column 4'?
A: 77,673 USD million
Evidence: {'text': 'Total revenue | | | 77,673 | | | | 65,585 |', 'page_number': 3, 'line_number': 65, 'start_offset': 20, 'end_offset': 26, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-005
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Product' under 'column 4'?
A: 2,922 USD million
Evidence: {'text': 'Product | | | 2,922 | | | | 3,294 |', 'page_number': 3, 'line_number': 67, 'start_offset': 14, 'end_offset': 19, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-006
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Service and other' under 'column 4'?
A: 21,121 USD million
Evidence: {'text': 'Service and other | | | 21,121 | | | | 16,805 |', 'page_number': 3, 'line_number': 68, 'start_offset': 24, 'end_offset': 30, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-007
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Total cost of revenue' under 'column 4'?
A: 24,043 USD million
Evidence: {'text': 'Total cost of revenue | | | 24,043 | | | | 20,099 |', 'page_number': 3, 'line_number': 69, 'start_offset': 28, 'end_offset': 34, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-008
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Gross margin' under 'column 4'?
A: 53,630 USD million
Evidence: {'text': 'Gross margin | | | 53,630 | | | | 45,486 |', 'page_number': 3, 'line_number': 70, 'start_offset': 19, 'end_offset': 25, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-009
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Research and development' under 'column 4'?
A: 8,146 USD million
Evidence: {'text': 'Research and development | | | 8,146 | | | | 7,544 |', 'page_number': 3, 'line_number': 71, 'start_offset': 31, 'end_offset': 36, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-010
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Sales and marketing' under 'column 4'?
A: 5,717 USD million
Evidence: {'text': 'Sales and marketing | | | 5,717 | | | | 5,717 |', 'page_number': 3, 'line_number': 72, 'start_offset': 26, 'end_offset': 31, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-011
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'General and administrative' under 'column 4'?
A: 1,806 USD million
Evidence: {'text': 'General and administrative | | | 1,806 | | | | 1,673 |', 'page_number': 3, 'line_number': 73, 'start_offset': 33, 'end_offset': 38, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-012
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Operating income' under 'column 4'?
A: 37,961 USD million
Evidence: {'text': 'Operating income | | | 37,961 | | | | 30,552 |', 'page_number': 3, 'line_number': 74, 'start_offset': 23, 'end_offset': 29, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-013
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Income before income taxes' under 'column 4'?
A: 34,301 USD million
Evidence: {'text': 'Income before income taxes | | | 34,301 | | | | 30,269 |', 'page_number': 3, 'line_number': 76, 'start_offset': 33, 'end_offset': 39, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-014
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Provision for income taxes' under 'column 4'?
A: 6,554 USD million
Evidence: {'text': 'Provision for income taxes | | | 6,554 | | | | 5,602 |', 'page_number': 3, 'line_number': 77, 'start_offset': 33, 'end_offset': 38, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-015
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Net income' under 'column 4'?
A: 27,747 USD
Evidence: {'text': 'Net income | | $ | 27,747 | | | $ | 24,667 |', 'page_number': 3, 'line_number': 78, 'start_offset': 19, 'end_offset': 25, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-016
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Basic' under 'column 4'?
A: 3.73 USD
Evidence: {'text': 'Basic | | $ | 3.73 | | | $ | 3.32 |', 'page_number': 3, 'line_number': 80, 'start_offset': 14, 'end_offset': 18, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-017
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Diluted' under 'column 4'?
A: 3.72 USD
Evidence: {'text': 'Diluted | | $ | 3.72 | | | $ | 3.30 |', 'page_number': 3, 'line_number': 81, 'start_offset': 16, 'end_offset': 20, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-018
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Basic' under 'column 4'?
A: 7,433 USD million
Evidence: {'text': 'Basic | | | 7,433 | | | | 7,433 |', 'page_number': 3, 'line_number': 83, 'start_offset': 12, 'end_offset': 17, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-019
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Diluted' under 'column 4'?
A: 7,466 USD million
Evidence: {'text': 'Diluted | | | 7,466 | | | | 7,470 |', 'page_number': 3, 'line_number': 84, 'start_offset': 14, 'end_offset': 19, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-020
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Net change related to investments' under 'column 4'?
A: 687 USD million
Evidence: {'text': 'Net change related to investments | | | 687 | | | | 1,114 |', 'page_number': 5, 'line_number': 92, 'start_offset': 40, 'end_offset': 43, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-021
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Other comprehensive income' under 'column 4'?
A: 586 USD million
Evidence: {'text': 'Other comprehensive income | | | 586 | | | | 1,408 |', 'page_number': 5, 'line_number': 94, 'start_offset': 33, 'end_offset': 36, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-022
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Comprehensive income' under 'column 4'?
A: 28,333 USD
Evidence: {'text': 'Comprehensive income | | $ | 28,333 | | | $ | 26,075 |', 'page_number': 5, 'line_number': 95, 'start_offset': 29, 'end_offset': 35, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-023
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Cash and cash equivalents' under 'column 4'?
A: 28,849 USD
Evidence: {'text': 'Cash and cash equivalents | | $ | 28,849 | | | $ | 30,242 |', 'page_number': 6, 'line_number': 102, 'start_offset': 34, 'end_offset': 40, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-024
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Short-term investments' under 'column 4'?
A: 73,163 USD million
Evidence: {'text': 'Short-term investments | | | 73,163 | | | | 64,323 |', 'page_number': 6, 'line_number': 103, 'start_offset': 29, 'end_offset': 35, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-025
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Total cash, cash equivalents, and short-term investments' under 'column 4'?
A: 102,012 USD million
Evidence: {'text': 'Total cash, cash equivalents, and short-term investments | | | 102,012 | | | | 94,565 |', 'page_number': 6, 'line_number': 104, 'start_offset': 63, 'end_offset': 70, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-026
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Accounts receivable, net of allowance for doubtful accounts of $687 and $944' under 'column 4'?
A: 52,894 USD
Evidence: {'text': 'Accounts receivable, net of allowance for doubtful accounts of $687 and $944 | | | 52,894 | | | | 69,905 |', 'page_number': 6, 'line_number': 105, 'start_offset': 83, 'end_offset': 89, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-027
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Inventories' under 'column 4'?
A: 1,130 USD million
Evidence: {'text': 'Inventories | | | 1,130 | | | | 938 |', 'page_number': 6, 'line_number': 106, 'start_offset': 18, 'end_offset': 23, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-028
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Other current assets' under 'column 4'?
A: 33,030 USD million
Evidence: {'text': 'Other current assets | | | 33,030 | | | | 25,723 |', 'page_number': 6, 'line_number': 107, 'start_offset': 27, 'end_offset': 33, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-029
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Total current assets' under 'column 4'?
A: 189,066 USD million
Evidence: {'text': 'Total current assets | | | 189,066 | | | | 191,131 |', 'page_number': 6, 'line_number': 108, 'start_offset': 27, 'end_offset': 34, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-030
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Property and equipment, net of accumulated depreciation of $98,880 and $93,653' under 'column 4'?
A: 230,861 USD
Evidence: {'text': 'Property and equipment, net of accumulated depreciation of $98,880 and $93,653 | | | 230,861 | | | | 204,966 |', 'page_number': 6, 'line_number': 109, 'start_offset': 85, 'end_offset': 92, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-031
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Operating lease right-of-use assets' under 'column 4'?
A: 24,791 USD million
Evidence: {'text': 'Operating lease right-of-use assets | | | 24,791 | | | | 24,823 |', 'page_number': 6, 'line_number': 110, 'start_offset': 42, 'end_offset': 48, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-032
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Equity and other investments' under 'column 4'?
A: 11,465 USD million
Evidence: {'text': 'Equity and other investments | | | 11,465 | | | | 15,405 |', 'page_number': 6, 'line_number': 111, 'start_offset': 35, 'end_offset': 41, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-033
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Goodwill' under 'column 4'?
A: 119,497 USD million
Evidence: {'text': 'Goodwill | | | 119,497 | | | | 119,509 |', 'page_number': 6, 'line_number': 112, 'start_offset': 15, 'end_offset': 22, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-034
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Intangible assets, net' under 'column 4'?
A: 21,236 USD million
Evidence: {'text': 'Intangible assets, net | | | 21,236 | | | | 22,604 |', 'page_number': 6, 'line_number': 113, 'start_offset': 29, 'end_offset': 35, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-035
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Other long-term assets' under 'column 4'?
A: 39,435 USD million
Evidence: {'text': 'Other long-term assets | | | 39,435 | | | | 40,565 |', 'page_number': 6, 'line_number': 114, 'start_offset': 29, 'end_offset': 35, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-036
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Total assets' under 'column 4'?
A: 636,351 USD
Evidence: {'text': 'Total assets | | $ | 636,351 | | | $ | 619,003 |', 'page_number': 6, 'line_number': 115, 'start_offset': 21, 'end_offset': 28, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-037
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Accounts payable' under 'column 4'?
A: 32,580 USD
Evidence: {'text': 'Accounts payable | | $ | 32,580 | | | $ | 27,724 |', 'page_number': 6, 'line_number': 118, 'start_offset': 25, 'end_offset': 31, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-038
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Current portion of long-term debt' under 'column 4'?
A: 7,832 USD million
Evidence: {'text': 'Current portion of long-term debt | | | 7,832 | | | | 2,999 |', 'page_number': 6, 'line_number': 119, 'start_offset': 40, 'end_offset': 45, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-039
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Accrued compensation' under 'column 4'?
A: 9,201 USD million
Evidence: {'text': 'Accrued compensation | | | 9,201 | | | | 13,709 |', 'page_number': 6, 'line_number': 120, 'start_offset': 27, 'end_offset': 32, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G2-040
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the reported value for 'Short-term income taxes' under 'column 4'?
A: 3,655 USD million
Evidence: {'text': 'Short-term income taxes | | | 3,655 | | | | 7,211 |', 'page_number': 6, 'line_number': 121, 'start_offset': 30, 'end_offset': 35, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

## Group3

### G3-001
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'Commercial paper' between 'column 7' and 'Unrealized Losses'?
A: 9,044.00 USD million
Evidence: {'text': 'Row: Commercial paper | | Level 2 | | | $ | 9,044 | | $ | 0 | | $ | 0 | | | $ | 9,044 | | $ | 8,597 | | $ | 447 | | $ | 0 | Computation: 9044.0 - 0.0 = 9,044.00', 'page_number': 14, 'line_number': 289, 'start_offset': 152, 'end_offset': 160, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-002
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the percent change for 'Commercial paper' from 'Unrealized Losses' to 'column 7'?
A: n/a
Evidence: {'text': 'Row: Commercial paper | | Level 2 | | | $ | 9,044 | | $ | 0 | | $ | 0 | | | $ | 9,044 | | $ | 8,597 | | $ | 447 | | $ | 0 | Computation: (9044.0 - 0.0) / |0.0| * 100 = n/a', 'page_number': 14, 'line_number': 289, 'start_offset': 168, 'end_offset': 171, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-003
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'Certificates of deposit' between 'column 7' and 'Unrealized Losses'?
A: 4,478.00 million
Evidence: {'text': 'Row: Certificates of deposit | | Level 2 | | | | 4,478 | | | 0 | | | 0 | | | | 4,478 | | | 4,434 | | | 44 | | | 0 | Computation: 4478.0 - 0.0 = 4,478.00', 'page_number': 14, 'line_number': 290, 'start_offset': 144, 'end_offset': 152, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-004
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the percent change for 'Certificates of deposit' from 'Unrealized Losses' to 'column 7'?
A: n/a
Evidence: {'text': 'Row: Certificates of deposit | | Level 2 | | | | 4,478 | | | 0 | | | 0 | | | | 4,478 | | | 4,434 | | | 44 | | | 0 | Computation: (4478.0 - 0.0) / |0.0| * 100 = n/a', 'page_number': 14, 'line_number': 290, 'start_offset': 160, 'end_offset': 163, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-005
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'U.S. government securities' between 'column 7' and 'Unrealized Losses'?
A: 54,630.00 million
Evidence: {'text': 'Row: U.S. government securities | | Level 1 | | | | 54,749 | | | 119 | | | (1,238 | ) | | | 53,630 | | | 1,143 | | | 52,487 | | | 0 | Computation: 54749.0 - 119.0 = 54,630.00', 'page_number': 14, 'line_number': 291, 'start_offset': 165, 'end_offset': 174, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-006
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the percent change for 'U.S. government securities' from 'Unrealized Losses' to 'column 7'?
A: 45907.56%
Evidence: {'text': 'Row: U.S. government securities | | Level 1 | | | | 54,749 | | | 119 | | | (1,238 | ) | | | 53,630 | | | 1,143 | | | 52,487 | | | 0 | Computation: (54749.0 - 119.0) / |119.0| * 100 = 45907.56%', 'page_number': 14, 'line_number': 291, 'start_offset': 183, 'end_offset': 192, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-007
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'U.S. agency securities' between 'column 7' and 'Unrealized Losses'?
A: 5,584.00 million
Evidence: {'text': 'Row: U.S. agency securities | | Level 2 | | | | 5,584 | | | 0 | | | 0 | | | | 5,584 | | | 2,100 | | | 3,484 | | | 0 | Computation: 5584.0 - 0.0 = 5,584.00', 'page_number': 14, 'line_number': 292, 'start_offset': 146, 'end_offset': 154, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-008
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the percent change for 'U.S. agency securities' from 'Unrealized Losses' to 'column 7'?
A: n/a
Evidence: {'text': 'Row: U.S. agency securities | | Level 2 | | | | 5,584 | | | 0 | | | 0 | | | | 5,584 | | | 2,100 | | | 3,484 | | | 0 | Computation: (5584.0 - 0.0) / |0.0| * 100 = n/a', 'page_number': 14, 'line_number': 292, 'start_offset': 162, 'end_offset': 165, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-009
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'Foreign government bonds' between 'column 7' and 'Unrealized Losses'?
A: 379.00 million
Evidence: {'text': 'Row: Foreign government bonds | | Level 2 | | | | 392 | | | 13 | | | (6 | ) | | | 399 | | | 0 | | | 399 | | | 0 | Computation: 392.0 - 13.0 = 379.00', 'page_number': 14, 'line_number': 293, 'start_offset': 142, 'end_offset': 148, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-010
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the percent change for 'Foreign government bonds' from 'Unrealized Losses' to 'column 7'?
A: 2915.38%
Evidence: {'text': 'Row: Foreign government bonds | | Level 2 | | | | 392 | | | 13 | | | (6 | ) | | | 399 | | | 0 | | | 399 | | | 0 | Computation: (392.0 - 13.0) / |13.0| * 100 = 2915.38%', 'page_number': 14, 'line_number': 293, 'start_offset': 159, 'end_offset': 167, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-011
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'Mortgage- and asset-backed securities' between 'column 7' and 'Unrealized Losses'?
A: 3,567.00 million
Evidence: {'text': 'Row: Mortgage- and asset-backed securities | | Level 2 | | | | 3,587 | | | 20 | | | (23 | ) | | | 3,584 | | | 0 | | | 3,584 | | | 0 | Computation: 3587.0 - 20.0 = 3,567.00', 'page_number': 14, 'line_number': 294, 'start_offset': 163, 'end_offset': 171, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-012
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the percent change for 'Mortgage- and asset-backed securities' from 'Unrealized Losses' to 'column 7'?
A: 17835.00%
Evidence: {'text': 'Row: Mortgage- and asset-backed securities | | Level 2 | | | | 3,587 | | | 20 | | | (23 | ) | | | 3,584 | | | 0 | | | 3,584 | | | 0 | Computation: (3587.0 - 20.0) / |20.0| * 100 = 17835.00%', 'page_number': 14, 'line_number': 294, 'start_offset': 180, 'end_offset': 189, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-013
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'Corporate notes and bonds' between 'column 7' and 'Unrealized Losses'?
A: 12,072.00 million
Evidence: {'text': 'Row: Corporate notes and bonds | | Level 2 | | | | 12,246 | | | 174 | | | (70 | ) | | | 12,350 | | | 0 | | | 12,350 | | | 0 | Computation: 12246.0 - 174.0 = 12,072.00', 'page_number': 14, 'line_number': 295, 'start_offset': 157, 'end_offset': 166, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-014
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the percent change for 'Corporate notes and bonds' from 'Unrealized Losses' to 'column 7'?
A: 6937.93%
Evidence: {'text': 'Row: Corporate notes and bonds | | Level 2 | | | | 12,246 | | | 174 | | | (70 | ) | | | 12,350 | | | 0 | | | 12,350 | | | 0 | Computation: (12246.0 - 174.0) / |174.0| * 100 = 6937.93%', 'page_number': 14, 'line_number': 295, 'start_offset': 175, 'end_offset': 183, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-015
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'Corporate notes and bonds' between 'column 7' and 'Unrealized Losses'?
A: 1,487.00 million
Evidence: {'text': 'Row: Corporate notes and bonds | | Level 3 | | | | 2,055 | | | 568 | | | 0 | | | | 2,623 | | | 0 | | | 113 | | | 2,510 | Computation: 2055.0 - 568.0 = 1,487.00', 'page_number': 14, 'line_number': 296, 'start_offset': 151, 'end_offset': 159, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-016
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the percent change for 'Corporate notes and bonds' from 'Unrealized Losses' to 'column 7'?
A: 261.80%
Evidence: {'text': 'Row: Corporate notes and bonds | | Level 3 | | | | 2,055 | | | 568 | | | 0 | | | | 2,623 | | | 0 | | | 113 | | | 2,510 | Computation: (2055.0 - 568.0) / |568.0| * 100 = 261.80%', 'page_number': 14, 'line_number': 296, 'start_offset': 169, 'end_offset': 176, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-017
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'Municipal securities' between 'column 7' and 'Unrealized Losses'?
A: 161.00 million
Evidence: {'text': 'Row: Municipal securities | | Level 2 | | | | 162 | | | 1 | | | (5 | ) | | | 158 | | | 0 | | | 158 | | | 0 | Computation: 162.0 - 1.0 = 161.00', 'page_number': 14, 'line_number': 297, 'start_offset': 136, 'end_offset': 142, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-018
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the percent change for 'Municipal securities' from 'Unrealized Losses' to 'column 7'?
A: 16100.00%
Evidence: {'text': 'Row: Municipal securities | | Level 2 | | | | 162 | | | 1 | | | (5 | ) | | | 158 | | | 0 | | | 158 | | | 0 | Computation: (162.0 - 1.0) / |1.0| * 100 = 16100.00%', 'page_number': 14, 'line_number': 297, 'start_offset': 152, 'end_offset': 161, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-019
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'Municipal securities' between 'column 7' and 'Unrealized Losses'?
A: 104.00 million
Evidence: {'text': 'Row: Municipal securities | | Level 3 | | | | 104 | | | 0 | | | (14 | ) | | | 90 | | | 0 | | | 90 | | | 0 | Computation: 104.0 - 0.0 = 104.00', 'page_number': 14, 'line_number': 298, 'start_offset': 135, 'end_offset': 141, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-020
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the percent change for 'Municipal securities' from 'Unrealized Losses' to 'column 7'?
A: n/a
Evidence: {'text': 'Row: Municipal securities | | Level 3 | | | | 104 | | | 0 | | | (14 | ) | | | 90 | | | 0 | | | 90 | | | 0 | Computation: (104.0 - 0.0) / |0.0| * 100 = n/a', 'page_number': 14, 'line_number': 298, 'start_offset': 151, 'end_offset': 154, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-021
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'Total debt investments' between 'column 7' and 'Unrealized Losses'?
A: 91,506.00 USD million
Evidence: {'text': 'Row: Total debt investments | | | | | $ | 92,401 | | $ | 895 | | $ | (1,356 | ) | | $ | 91,940 | | $ | 16,274 | | $ | 73,156 | | $ | 2,510 | Computation: 92401.0 - 895.0 = 91,506.00', 'page_number': 14, 'line_number': 299, 'start_offset': 172, 'end_offset': 181, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-022
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the percent change for 'Total debt investments' from 'Unrealized Losses' to 'column 7'?
A: 10224.13%
Evidence: {'text': 'Row: Total debt investments | | | | | $ | 92,401 | | $ | 895 | | $ | (1,356 | ) | | $ | 91,940 | | $ | 16,274 | | $ | 73,156 | | $ | 2,510 | Computation: (92401.0 - 895.0) / |895.0| * 100 = 10224.13%', 'page_number': 14, 'line_number': 299, 'start_offset': 190, 'end_offset': 199, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-023
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'Commercial paper' between 'column 7' and 'Unrealized Losses'?
A: 10,880.00 USD million
Evidence: {'text': 'Row: Commercial paper | | Level 2 | | | $ | 10,880 | | $ | 0 | | $ | 0 | | | $ | 10,880 | | $ | 9,939 | | $ | 941 | | $ | 0 | Computation: 10880.0 - 0.0 = 10,880.00', 'page_number': 14, 'line_number': 310, 'start_offset': 155, 'end_offset': 164, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-024
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'Certificates of deposit' between 'column 7' and 'Unrealized Losses'?
A: 2,653.00 million
Evidence: {'text': 'Row: Certificates of deposit | | Level 2 | | | | 2,653 | | | 0 | | | 0 | | | | 2,653 | | | 2,309 | | | 344 | | | 0 | Computation: 2653.0 - 0.0 = 2,653.00', 'page_number': 14, 'line_number': 311, 'start_offset': 145, 'end_offset': 153, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-025
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'U.S. government securities' between 'column 7' and 'Unrealized Losses'?
A: 52,807.00 million
Evidence: {'text': 'Row: U.S. government securities | | Level 1 | | | | 52,878 | | | 71 | | | (1,462 | ) | | | 51,487 | | | 4,742 | | | 46,745 | | | 0 | Computation: 52878.0 - 71.0 = 52,807.00', 'page_number': 14, 'line_number': 312, 'start_offset': 163, 'end_offset': 172, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-026
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the percent change for 'U.S. government securities' from 'Unrealized Losses' to 'column 7'?
A: 74376.06%
Evidence: {'text': 'Row: U.S. government securities | | Level 1 | | | | 52,878 | | | 71 | | | (1,462 | ) | | | 51,487 | | | 4,742 | | | 46,745 | | | 0 | Computation: (52878.0 - 71.0) / |71.0| * 100 = 74376.06%', 'page_number': 14, 'line_number': 312, 'start_offset': 180, 'end_offset': 189, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-027
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'U.S. agency securities' between 'column 7' and 'Unrealized Losses'?
A: 2,686.00 million
Evidence: {'text': 'Row: U.S. agency securities | | Level 2 | | | | 2,686 | | | 0 | | | 0 | | | | 2,686 | | | 496 | | | 2,190 | | | 0 | Computation: 2686.0 - 0.0 = 2,686.00', 'page_number': 14, 'line_number': 313, 'start_offset': 144, 'end_offset': 152, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-028
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'Foreign government bonds' between 'column 7' and 'Unrealized Losses'?
A: 325.00 million
Evidence: {'text': 'Row: Foreign government bonds | | Level 2 | | | | 349 | | | 24 | | | (9 | ) | | | 364 | | | 0 | | | 364 | | | 0 | Computation: 349.0 - 24.0 = 325.00', 'page_number': 14, 'line_number': 314, 'start_offset': 142, 'end_offset': 148, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-029
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the percent change for 'Foreign government bonds' from 'Unrealized Losses' to 'column 7'?
A: 1354.17%
Evidence: {'text': 'Row: Foreign government bonds | | Level 2 | | | | 349 | | | 24 | | | (9 | ) | | | 364 | | | 0 | | | 364 | | | 0 | Computation: (349.0 - 24.0) / |24.0| * 100 = 1354.17%', 'page_number': 14, 'line_number': 314, 'start_offset': 159, 'end_offset': 167, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}

### G3-030
Q: According to the MSFT_FY26Q1_10Q.docx file, what is the absolute difference for 'Mortgage- and asset-backed securities' between 'column 7' and 'Unrealized Losses'?
A: 2,548.00 million
Evidence: {'text': 'Row: Mortgage- and asset-backed securities | | Level 2 | | | | 2,558 | | | 10 | | | (27 | ) | | | 2,541 | | | 0 | | | 2,541 | | | 0 | Computation: 2558.0 - 10.0 = 2,548.00', 'page_number': 14, 'line_number': 315, 'start_offset': 163, 'end_offset': 171, 'offset_convention': {'library': 'python3-str', 'unit': 'unicode_codepoint', 'index_base': 0, 'range': '[start_offset, end_offset)'}}
