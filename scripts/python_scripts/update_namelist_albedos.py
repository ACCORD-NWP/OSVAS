#!/usr/bin/env python3
"""
Update SURFEX namelists with estimated albedo values.

This script:
1. Reads estimated albedo namelist block (from estimate_albedo.py)
2. Finds and replaces albedo parameter blocks in experiment namelists
3. If albedo blocks are not found, inserts them into &NAM_DATA_ISBA group,
   together with fixed XUNIF_ALBUV_VEG and XUNIF_ALBUV_SOIL blocks
4. Creates backup copies of original namelists

Usage:
    python3 update_namelist_albedos.py <station_name> <osvas_root> [OPTIONS]

Options:
    --expnames EXP1 EXP2 ...    Experiment names to update (default: all from YAML config)
    --albedo-file Path          Path to albedo estimates file (default: namelists/{station}/albedo_estimates.nam)
    --no-backup                 Don't create backup copies
"""

import os
import sys
import re
import argparse
import shutil
import yaml
from pathlib import Path
from typing import List, Tuple


def read_albedo_namelist(albedo_file):
    """Read the estimated albedo namelist block."""
    if not Path(albedo_file).exists():
        print(f"❌ Error: Albedo file not found: {albedo_file}")
        sys.exit(1)
    
    with open(albedo_file, 'r') as f:
        content = f.read()
    
    print(f"  Read albedo estimates from: {albedo_file}")
    return content


def find_albedo_blocks(namelist_content):
    """Find all albedo parameter blocks in namelist content.
    
    Returns: List of (param_name, start_pos, end_pos) tuples
    """
    # Pattern to match XUNIF_ALB*_VEG/SOIL entries
    param_pattern = r'(XUNIF_ALB(?:NIR|VIS)_(?:VEG|SOIL)\(\d+,\s*\d+\)\s*=\s*[^,]+,(?:\s*\n)?)'
    
    blocks = list(re.finditer(param_pattern, namelist_content))
    return blocks


def extract_parameter_ranges(content, vegtype):
    """Extract the start and end positions of each albedo parameter block.
    
    Albedo blocks span from first month to 12th month for each parameter.
    """
    # Patterns for the four albedo types
    patterns = [
        ('XUNIF_ALBNIR_VEG', f'XUNIF_ALBNIR_VEG\\({vegtype},\\s*1\\)'),
        ('XUNIF_ALBVIS_VEG', f'XUNIF_ALBVIS_VEG\\({vegtype},\\s*1\\)'),
        ('XUNIF_ALBUV_VEG', f'XUNIF_ALBUV_VEG\\({vegtype},\\s*1\\)'),
        ('XUNIF_ALBNIR_SOIL', f'XUNIF_ALBNIR_SOIL\\({vegtype},\\s*1\\)'),
        ('XUNIF_ALBVIS_SOIL', f'XUNIF_ALBVIS_SOIL\\({vegtype},\\s*1\\)'),
        ('XUNIF_ALBUV_SOIL', f'XUNIF_ALBUV_SOIL\\({vegtype},\\s*1\\)'),        
    ]
    
    parameter_ranges = {}
    
    for param_name, start_pattern in patterns:
        # Find where this parameter block starts
        start_match = re.search(start_pattern, content)
        if not start_match:
            print(f"  ⚠️  {param_name}: Not found in namelist")
            continue
        
        # Search backward to find where the line starts (skip indentation)
        start_pos = content.rfind('\n', 0, start_match.start()) + 1
        if start_pos == 0:
            start_pos = 0
        
        # Find where month 12 line ends (last comma)
        last_month_pattern = f'{param_name}\\({vegtype},\\s*12\\)'
        end_match = re.search(last_month_pattern, content[start_pos:])
        
        if not end_match:
            print(f"  ⚠️  {param_name}(12): Not found in namelist")
            continue
        
        # Find end of that line (next newline or end of content)
        end_in_content = start_pos + end_match.end()
        next_newline = content.find('\n', end_in_content)
        if next_newline == -1:
            end_pos = len(content)
        else:
            end_pos = next_newline
        
        parameter_ranges[param_name] = (start_pos, end_pos)
        print(f"  ✓ Found {param_name} block")
    
    return parameter_ranges


def extract_estimated_block(albedo_content, param_name):
    """Extract a single parameter block from estimated albedo namelist."""
    pattern = rf'(! .*?)?(\s*{param_name}\(\d+,\s*1\).*?{param_name}\(\d+,\s*12\)[^,]*,)'
    
    match = re.search(pattern, albedo_content, re.DOTALL)
    if match:
        return match.group(2).strip()
    
    return None


def build_albuv_block(vegtype):
    """Build the fixed XUNIF_ALBUV_VEG and XUNIF_ALBUV_SOIL blocks."""
    indent = ' ' * 23  # match typical SURFEX namelist indentation
    lines = []

    for month in range(1, 13):
        pad = ' ' if month < 10 else ''
        lines.append(f"{indent}XUNIF_ALBUV_VEG({vegtype},{pad}{month})  = 0.015,")
    for month in range(1, 13):
        pad = ' ' if month < 10 else ''
        lines.append(f"{indent}XUNIF_ALBUV_SOIL({vegtype},{pad}{month}) = 0.06,")

    return '\n'.join(lines)


def extract_new_blocks_from_albedo(albedo_content, vegtype):
    """Extract the six NIR/VIS VEG/SOIL blocks from the albedo estimates file."""
    param_names = ['XUNIF_ALBNIR_VEG', 'XUNIF_ALBVIS_VEG',  'XUNIF_ALBUV_VEG', 'XUNIF_ALBNIR_SOIL', 'XUNIF_ALBVIS_SOIL',  'XUNIF_ALBUV_SOIL']
    new_blocks = {}

    for param_name in param_names:
        lines = albedo_content.split('\n')
        block_lines = []
        in_block = False

        for line in lines:
            if param_name in line and '(' in line:
                in_block = True
            if in_block:
                block_lines.append(line)
                if f'{param_name}({vegtype},12)' in line:
                    break

        if block_lines:
            new_blocks[param_name] = '\n'.join(block_lines)

    return new_blocks


def insert_albedos_into_nam_data_isba(content, albedo_content, vegtype):
    """Fallback: insert all albedo blocks just before the closing '/' of &NAM_DATA_ISBA.

    Inserts the six NIR/VIS/UV estimated blocks.
    Returns the updated content, or None if &NAM_DATA_ISBA is not found.
    """
    # Find &NAM_DATA_ISBA group
    group_match = re.search(r'&NAM_DATA_ISBA\b', content)
    if not group_match:
        print(f"  ❌ &NAM_DATA_ISBA group not found in namelist — cannot insert blocks")
        return None

    # Find the closing '/' of that namelist group (first bare '/' after the opening)
    search_start = group_match.end()
    # A closing slash is a line that, after stripping, is just '/'
    closing_match = re.search(r'\n([ \t]*/[ \t]*\n)', content[search_start:])
    if not closing_match:
        print(f"  ❌ Could not find closing '/' for &NAM_DATA_ISBA — cannot insert blocks")
        return None

    insert_pos = search_start + closing_match.start() + 1  # position of the '/' line

    # Build the block to insert
    new_blocks = extract_new_blocks_from_albedo(albedo_content, vegtype)
    if not new_blocks:
        print(f"  ⚠️  Could not extract estimated albedo blocks from albedo file")
        return None

    param_order = ['XUNIF_ALBNIR_VEG', 'XUNIF_ALBVIS_VEG', 'XUNIF_ALBUV_VEG', 'XUNIF_ALBNIR_SOIL', 'XUNIF_ALBVIS_SOIL', 'XUNIF_ALBUV_SOIL']   
    block_parts = []
    for param_name in param_order:
        if param_name in new_blocks:
            block_parts.append(new_blocks[param_name])
        else:
            print(f"  ⚠️  {param_name} block missing from albedo estimates file")

    block_parts.append(build_albuv_block(vegtype))

    insertion = '\n'.join(block_parts) + '\n'

    content = content[:insert_pos] + insertion + content[insert_pos:]
    print(f"  ✓ Inserted NIR/VIS/UV SOIL/VEG albedo blocks into &NAM_DATA_ISBA")
    return content


def update_namelist_with_albedos(namelist_file, albedo_content, vegtype, backup=True):
    """Replace albedo blocks in namelist with estimated values.

    If the existing blocks are not found, falls back to inserting all blocks
    (NIR/VIS estimated + fixed ALBUV) into the &NAM_DATA_ISBA group.
    """
    
    with open(namelist_file, 'r') as f:
        content = f.read()
    
    # Find existing albedo parameter ranges
    param_ranges = extract_parameter_ranges(content, vegtype)
    
    if not param_ranges:
        # ── Fallback path ──────────────────────────────────────────────────
        print(f"  ℹ️  No existing albedo blocks found — inserting into &NAM_DATA_ISBA")
        updated = insert_albedos_into_nam_data_isba(content, albedo_content, vegtype)
        if updated is None:
            return False
        content = updated

    else:
        # ── Normal replace path ────────────────────────────────────────────
        new_blocks = extract_new_blocks_from_albedo(albedo_content, vegtype)

        if not new_blocks:
            print(f"  ⚠️  Could not extract estimated albedo blocks")
            return False

        # Replace blocks in reverse order to maintain position validity
        sorted_params = sorted(param_ranges.keys(), key=lambda x: param_ranges[x][0], reverse=True)
        for param_name in sorted_params:
            if param_name in new_blocks:
                start_pos, end_pos = param_ranges[param_name]
                content = content[:start_pos] + new_blocks[param_name] + content[end_pos:]
                print(f"  ✓ Updated {param_name}")

    # Create backup (done after we know something will be written)
    if backup:
        backup_file = str(namelist_file) + '.backup_alb'
        shutil.copy2(namelist_file, backup_file)
        print(f"  ✓ Backup created: {backup_file}")

    # Write updated namelist
    with open(namelist_file, 'w') as f:
        f.write(content)
    
    print(f"  ✓ Namelist updated: {namelist_file}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Update SURFEX namelists with estimated albedo values'
    )
    parser.add_argument('station_name', help='Station name')
    parser.add_argument('osvas_root', help='OSVAS root directory')
    parser.add_argument('--expnames', nargs='+', 
                       help='Experiment names to update (default: all from YAML config)')
    parser.add_argument('--albedo-file', 
                       help='Path to albedo estimates file')
    parser.add_argument('--no-backup', action='store_true',
                       help="Don't create backup copies")
    
    args = parser.parse_args()
    
    station_name = args.station_name
    osvas_root = Path(args.osvas_root).expanduser().resolve()
    
    print(f"\n{'='*70}")
    print(f"Updating namelists with estimated albedos for {station_name}")
    print(f"{'='*70}\n")
    
    # Get experiment names
    if args.expnames:
        expnames = args.expnames
    else:
        config_file = osvas_root / 'config_files' / 'Stations' / station_name / f'{station_name}.yml'
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        expnames = config['OSVAS_steps']['Expnames']
        print(f"Using experiments from config: {', '.join(expnames)}")
    
    # Get vegtype
    config_file = osvas_root / 'config_files' / 'Stations' / station_name / f'{station_name}.yml'
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    vegtype = config['Station_metadata']['vegtype']
    
    # Get albedo estimates file
    if args.albedo_file:
        albedo_file = args.albedo_file
    else:
        albedo_file = osvas_root / 'namelists' / station_name / 'albedo_estimates.nam'
    
    print(f"Step 1: Reading albedo estimates")
    albedo_content = read_albedo_namelist(albedo_file)
    
    # Update each experiment's namelist
    print(f"\nStep 2: Updating experiment namelists")
    success_count = 0
    
    for expname in expnames:
        namelist_file = osvas_root / 'namelists' / station_name / f'OPTIONS.nam_{expname}'
        
        if not namelist_file.exists():
            print(f"  ✗ Namelist not found: {namelist_file}")
            continue
        
        print(f"\n  Processing: {expname}")
        if update_namelist_with_albedos(namelist_file, albedo_content, vegtype, backup=not args.no_backup):
            success_count += 1
    
    print(f"\n{'='*70}")
    print(f"✅ Updated {success_count}/{len(expnames)} experiment namelists")
    print(f"{'='*70}\n")
    
    return 0 if success_count == len(expnames) else 1


if __name__ == '__main__':
    sys.exit(main())
