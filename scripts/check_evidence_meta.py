import json
from pathlib import Path

j = json.loads(Path('msft_fy26q1_qa_benchmark_100.json').read_text())
qas = j['qa_pairs']
required = {'text', 'page_number', 'line_number', 'start_offset', 'end_offset'}
missing = []
bad = []

for qa in qas:
    ev = qa.get('evidence', {})
    if not isinstance(ev, dict) or not required.issubset(ev.keys()):
        missing.append(qa['id'])
        continue
    txt = ev['text']
    s = ev['start_offset']
    e = ev['end_offset']
    if not isinstance(s, int) or not isinstance(e, int) or s < 0 or e < s or e > len(txt):
        bad.append((qa['id'], s, e, len(txt)))

print('total', len(qas))
print('missing_evidence_fields', len(missing))
print('bad_offsets', len(bad))
print('first_three:')
for qa in qas[:3]:
    print(qa['id'], qa['evidence'])
