#!/usr/bin/env python3
import argparse
from pathlib import Path
import re


def patch_fn_verif_helpers(path: Path) -> bool:
    text = path.read_text(encoding='utf-8')
    if 'month = "All"' in text:
        print(f"✅ {path.name}: already patched for month = 'All'.")
        return False

    original = text
    text = text.replace('valid_dttm = "All") %>%', 'valid_dttm = "All", month = "All") %>%')

    if text == original:
        print(f"⚠️  {path.name}: could not find the expected block to patch.")
        return False

    path.write_text(text, encoding='utf-8')
    print(f"✅ {path.name}: patched valid_dttm block with month = 'All'.")
    return True


def patch_point_verif(path: Path) -> bool:
    text = path.read_text(encoding='utf-8')
    modified = False

    if '"station_group","month"' not in text and '"station_group","month"' not in text:
        if 'c("fcst_cycle","station_group")' in text:
            text = text.replace('c("fcst_cycle","station_group")', 'c("fcst_cycle","station_group","month")', 1)
            modified = True
            print(f"✅ {path.name}: added month to grps_surface_default grouping.")
        else:
            print(f"⚠️  {path.name}: could not find the grps_surface_default grouping block to patch.")

    if 'sprintf("%02d",valid_month)' not in text:
        pattern = re.compile(
            r'(fcst <- harpPoint::mutate_list\(fcst,\s*\n\s*valid_hour = sprintf\("%02d",valid_hour\)\))',
            re.MULTILINE,
        )
        replacement = (
            r"\1\n  fcst <- harpPoint::mutate_list(fcst,\n"
            r"                                 month = sprintf("%02d",valid_month))"
        )
        text, count = pattern.subn(replacement, text, count=1)
        if count > 0:
            modified = True
            print(f"✅ {path.name}: inserted month mutator after valid_hour conversion.")
        else:
            print(f"⚠️  {path.name}: could not find valid_hour mutate block to patch.")

    if modified:
        path.write_text(text, encoding='utf-8')
        return True

    print(f"⚠️  {path.name}: no changes were made.")
    return False


def main():
    parser = argparse.ArgumentParser(description='Apply OSVAS-specific patches to HARPSCRIPTS files.')
    parser.add_argument('harpscripts_dir', help='Path to the HARPSCRIPTS repository')
    args = parser.parse_args()

    harpscripts_dir = Path(args.harpscripts_dir).expanduser().resolve()
    if not harpscripts_dir.is_dir():
        raise SystemExit(f"Error: HARPSCRIPTS directory not found: {harpscripts_dir}")

    fn_verif_helpers = harpscripts_dir / 'verification' / 'fn_verif_helpers.R'
    point_verif = harpscripts_dir / 'verification' / 'point_verif.R'

    if not fn_verif_helpers.exists() or not point_verif.exists():
        raise SystemExit("Error: expected HARPSCRIPTS verification files not found.")

    patch_fn_verif_helpers(fn_verif_helpers)
    patch_point_verif(point_verif)


if __name__ == '__main__':
    main()
