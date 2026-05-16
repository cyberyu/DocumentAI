#!/usr/bin/env python3
"""Fix the inline regex by adding .\\d+ alternative."""
with open('scripts/run_surfsense_benchmark.py') as f:
    content = f.read()

old_line = '            r"|[$\u20ac\u00a3\u00a5]?[-+]?\\d+(?:\\.\\d+)?"'
new_lines = [
    '            r"|[$\u20ac\u00a3\u00a5]?[-+]?\\d+(?:\\.\\d+)?"',
    '            r"|\\.\\d+"',
]
replacement = '\n'.join(new_lines)

if old_line in content:
    # Only replace occurrences in extraction functions, not in _SIGNED_NUM_RE
    # Replace the last occurrence (the one in _extract_final_numeric_candidate)
    # and the one before it (in _extract_final_value_candidate)
    lines = content.split('\n')
    count = 0
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == old_line.strip():
            # Check if the next line doesn't already have |\.\d+
            if i + 1 >= len(lines) or '|\\.\\d+' not in lines[i + 1]:
                lines[i] = lines[i] + '\n' + new_lines[1]
                count += 1
                if count >= 2:  # fix both occurrences
                    break
    content = '\n'.join(lines)
    with open('scripts/run_surfsense_benchmark.py', 'w') as f:
        f.write(content)
    print(f'Fixed {count} occurrences')
else:
    print('Pattern not found')
    # Show what lines have similar content
    for i, line in enumerate(content.split('\n')):
        if '\\d+(?:\\.\\d+)?' in line:
            print(f'  Line {i}: {line.strip()[:60]}')
PYEOF