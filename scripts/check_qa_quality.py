import json
import re
from pathlib import Path

j = json.loads(Path('msft_fy26q1_qa_benchmark_100.json').read_text())
qas = j['qa_pairs']

bad_date = [q['id'] for q in qas if q['group'] == 'Group1' and re.fullmatch(r'\d{1,2},?', q['answer'])]
bad_small = [q['id'] for q in qas if q['group'] == 'Group1' and re.fullmatch(r'[1-9]', q['answer'])]
paren_bad = [
    q['id']
    for q in qas
    if q['group'] == 'Group2' and q['answer'].startswith('(') and not q['answer'].endswith(')')
]

print('total', len(qas))
print('bad_date', len(bad_date), bad_date[:10])
print('bad_small', len(bad_small), bad_small[:10])
print('paren_bad', len(paren_bad), paren_bad[:10])

print('\nSAMPLE GROUP1:')
for q in [x for x in qas if x['group'] == 'Group1'][:8]:
    print(q['id'], q['answer'], '|', q['question'][:90])
