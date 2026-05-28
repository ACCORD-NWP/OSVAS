#!/usr/bin/env python3
"""
Update SURFEX namelists with estimated LAI values.

This script:
1. Reads estimated LAI namelist block (from estimate_lai.py)
2. Finds and replaces XUNIF_LAI parameter blocks in experiment namelists
3. If the LAI block is not found, inserts it into the &NAM_DATA_ISBA group
4. Creates backup copies of original namelists

Usage:
    python3 update_namelist_lais.py <station_name> <osvas_root> [OPTIONS]

Options:
    --expnames EXP1 EXP2 ...  Experiment names to update (default: all from YAML config)
    --lai-file PATH           Path to LAI estimates file
                              (default: namelists/{station}/lai_estimates.nam)
    --no-backup               Don't create backup copies
"""

import sys
import re
import argparse
import shutil
import yaml
from pathlib import Path


# ---------------------------------------------------------------------------
# Read input
# ---------------------------------------------------------------------------

def read_lai_namelist(lai_file):
    """Read the estimated LAI namelist block."""
    if not Path(lai_file).exists():
        print(f"❌ Error: LAI file not found: {lai_file}")
        sys.exit(1)
    with open(lai_file, 'r') as f:
        content = f.read()
    print(f"  Read LAI estimates from: {lai_file}")
    return content


# ---------------------------------------------------------------------------
# Extract the new XUNIF_LAI block from the estimates file
# ---------------------------------------------------------------------------

def extract_lai_block(lai_content, vegtype):
    """
    Extract the XUNIF_LAI(vegtype, 1..12) block from the estimates file.
    Returns the block as a string, or None if not found.
    """
    lines      = lai_content.split('\n')
    block_lines = []
    in_block   = False

    for line in lines:
        if f'XUNIF_LAI({vegtype},' in line or f'XUNIF_LAI({vegtype} ,' in line:
            in_block = True
        if in_block:
            block_lines.append(line)
            # Stop after the month-12 line
            if re.search(rf'XUNIF_LAI\({vegtype},\s*12\)', line):
                break

    return '\n'.join(block_lines) if block_lines else None


# ---------------------------------------------------------------------------
# Find existing XUNIF_LAI block in the target namelist
# ---------------------------------------------------------------------------

def find_lai_parameter_range(content, vegtype):
    """
    Locate the existing XUNIF_LAI(vegtype, 1) … XUNIF_LAI(vegtype, 12) span
    in the namelist content.

    Returns (start_pos, end_pos) of the full block (line-aligned),
    or None if not found.
    """
    start_pattern = rf'XUNIF_LAI\({vegtype},\s*1\)'
    start_match   = re.search(start_pattern, content)
    if not start_match:
        return None

    # Walk back to the beginning of that line
    start_pos = content.rfind('\n', 0, start_match.start()) + 1

    end_pattern = rf'XUNIF_LAI\({vegtype},\s*12\)'
    end_match   = re.search(end_pattern, content[start_pos:])
    if not end_match:
        return None

    end_in_content = start_pos + end_match.end()
    next_newline   = content.find('\n', end_in_content)
    end_pos        = next_newline if next_newline != -1 else len(content)

    return start_pos, end_pos


# ---------------------------------------------------------------------------
# Fallback: insert into &NAM_DATA_ISBA
# ---------------------------------------------------------------------------

def insert_lai_into_nam_data_isba(content, new_block):
    """
    Insert new_block just before the closing '/' of &NAM_DATA_ISBA.
    Returns the updated content, or None if the group / closing slash
    cannot be found.
    """
    group_match = re.search(r'&NAM_DATA_ISBA\b', content)
    if not group_match:
        print("  ❌ &NAM_DATA_ISBA group not found in namelist — cannot insert block")
        return None

    search_start  = group_match.end()
    closing_match = re.search(r'\n([ \t]*/[ \t]*\n)', content[search_start:])
    if not closing_match:
        print("  ❌ Could not find closing '/' for &NAM_DATA_ISBA — cannot insert block")
        return None

    insert_pos = search_start + closing_match.start() + 1
    insertion  = new_block.rstrip('\n') + '\n'
    return content[:insert_pos] + insertion + content[insert_pos:]


# ---------------------------------------------------------------------------
# Main per-file update
# ---------------------------------------------------------------------------

def update_namelist_with_lais(namelist_file, lai_content, vegtype, backup=True):
    """
    Replace or insert the XUNIF_LAI block in the given namelist file.

    Replace path: an existing XUNIF_LAI(vegtype,1..12) block is found and
                  overwritten in-place.
    Insert path:  no existing block found → insert before closing '/' of
                  &NAM_DATA_ISBA.
    """
    with open(namelist_file, 'r') as f:
        content = f.read()

    new_block = extract_lai_block(lai_content, vegtype)
    if not new_block:
        print(f"  ❌ Could not extract XUNIF_LAI({vegtype},...) block from estimates file")
        return False

    param_range = find_lai_parameter_range(content, vegtype)

    if param_range:
        # ── Replace existing block ─────────────────────────────────────────
        start_pos, end_pos = param_range
        content = content[:start_pos] + new_block + content[end_pos:]
        print(f"  ✓ Replaced existing XUNIF_LAI block")
    else:
        # ── Insert into &NAM_DATA_ISBA ─────────────────────────────────────
        print(f"  ℹ️  No existing XUNIF_LAI block found — inserting into &NAM_DATA_ISBA")
        updated = insert_lai_into_nam_data_isba(content, new_block)
        if updated is None:
            return False
        content = updated
        print(f"  ✓ Inserted XUNIF_LAI block into &NAM_DATA_ISBA")

    # Create backup after confirming something was modified
    if backup:
        backup_file = str(namelist_file) + '.backup_lai'
        shutil.copy2(namelist_file, backup_file)
        print(f"  ✓ Backup created: {backup_file}")

    with open(namelist_file, 'w') as f:
        f.write(content)

    print(f"  ✓ Namelist updated: {namelist_file}")
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Update SURFEX namelists with estimated LAI values'
    )
    parser.add_argument('station_name', help='Station name')
    parser.add_argument('osvas_root',   help='OSVAS root directory')
    parser.add_argument('--expnames', nargs='+',
                        help='Experiment names to update (default: all from YAML config)')
    parser.add_argument('--lai-file',
                        help='Path to LAI estimates file')
    parser.add_argument('--no-backup', action='store_true',
                        help="Don't create backup copies")

    args = parser.parse_args()

    station_name = args.station_name
    osvas_root   = Path(args.osvas_root).expanduser().resolve()

    print(f"\n{'='*70}")
    print(f"Updating namelists with estimated LAIs for {station_name}")
    print(f"{'='*70}\n")

    config_file = (
        osvas_root / 'config_files' / 'Stations' / station_name / f'{station_name}.yml'
    )
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)

    # Experiment names
    if args.expnames:
        expnames = args.expnames
    else:
        expnames = config['OSVAS_steps']['Expnames']
        print(f"Using experiments from config: {', '.join(expnames)}")

    # Vegtype
    vegtype = config['Station_metadata']['vegtype']

    # LAI estimates file
    lai_file = (
        args.lai_file
        if args.lai_file
        else osvas_root / 'namelists' / station_name / 'lai_estimates.nam'
    )

    print(f"Step 1: Reading LAI estimates")
    lai_content = read_lai_namelist(lai_file)

    print(f"\nStep 2: Updating experiment namelists")
    success_count = 0

    for expname in expnames:
        namelist_file = osvas_root / 'namelists' / station_name / f'OPTIONS.nam_{expname}'
        if not namelist_file.exists():
            print(f"  ✗ Namelist not found: {namelist_file}")
            continue
        print(f"\n  Processing: {expname}")
        if update_namelist_with_lais(
            namelist_file, lai_content, vegtype, backup=not args.no_backup
        ):
            success_count += 1

    print(f"\n{'='*70}")
    print(f"✅ Updated {success_count}/{len(expnames)} experiment namelists")
    print(f"{'='*70}\n")

    return 0 if success_count == len(expnames) else 1


if __name__ == '__main__':
    sys.exit(main())
