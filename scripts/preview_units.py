import json
from pathlib import Path

j = json.loads(Path('msft_fy26q1_qa_benchmark_100.json').read_text())
for group in ['Group1', 'Group2', 'Group3']:
    print('\n' + group)
    n = 0
    for qa in j['qa_pairs']:
        if qa['group'] == group:
            print(f"{qa['id']} => {qa['answer']}")
            n += 1
            if n == 8:
                break
