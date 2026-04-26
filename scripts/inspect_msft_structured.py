import json
import re
from pathlib import Path

j = json.loads(Path('msft_docx_structured.json').read_text())
print('paragraphs', j['paragraph_count'], 'tables', j['table_count'])

num_paras = [p for p in j['paragraphs'] if re.search(r'\$?\d[\d,]*(?:\.\d+)?%?', p)]
print('\nNUMERIC PARAGRAPH SAMPLES:')
for p in num_paras[:12]:
    print('-', p[:220])

print('\nTABLE HEADER SAMPLES:')
for t in j['tables'][:12]:
    h = t['rows'][0]
    print('-', h[:6])
