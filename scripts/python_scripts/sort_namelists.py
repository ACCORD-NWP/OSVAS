import os
import re
import glob

def parse_blocks(lines):
    blocks = []
    current_block = []
    in_block = False
    for line in lines:
        if re.match(r'^\s*&[Nn][Aa][Mm]_', line):
            if current_block:
                blocks.append(current_block)
            current_block = [line]
            in_block = True
        elif line.strip() == '/':
            if in_block:
                current_block.append(line)
                blocks.append(current_block)
                current_block = []
                in_block = False
        elif in_block:
            current_block.append(line)
    if current_block:
        blocks.append(current_block)
    return blocks

def get_sort_key(block):
    first_line = block[0]
    match = re.match(r'^\s*&[Nn][Aa][Mm]_(\w+)', first_line)
    if match:
        return match.group(1).upper()
    return ''

def sort_file(filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()
    blocks = parse_blocks(lines)
    # Sort blocks
    blocks.sort(key=get_sort_key)
    # Join back
    new_lines = []
    for block in blocks:
        new_lines.extend(block)
    # Write back
    with open(filepath, 'w') as f:
        f.writelines(new_lines)

# Find all files
files = glob.glob('../../namelists/**/OPTIONS.nam*', recursive=True)
for f in files:
    sort_file(f)
    print(f"Sorted {f}")
