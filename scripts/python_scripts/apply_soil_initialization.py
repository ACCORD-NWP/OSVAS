#!/usr/bin/env python3
"""
Apply soil temperature and humidity initialization profiles to SURFEX run directories.

This script externalizes STEP 2.8 from ICOS_Flux_Downloader.ipynb.
It loads tg_profile and hug_profile from a previous Get_validation run
and applies them to the experiment run directories based on YAML configuration.

Usage:
    python apply_soil_initialization.py <station_name> <osvas_path> <mode>

Where mode is:
    - 'namelist': Apply to OPTIONS.nam before any SURFEX steps (if Init_to_namelist=True)
    - 'prep': Apply to PREP files after PREP step and before OFFLINE (if Init_to_prep=True)
"""

import os
import sys
import yaml
import numpy as np
import re
_re = re
import netCDF4 as nc

def _update_namelist_tg(namelist_path, tg_profile):
    """
    Replace all XUNIF_TG_SOIL(*) lines in OPTIONS.nam with values from
    tg_profile (K), inserted before the first closing '/' of the namelist.
    """
    with open(namelist_path) as f:
        content = f.read()

    n     = len(tg_profile)
    idx_w = len(str(n))
    vname = "XUNIF_TG_SOIL"
    new_lines = "\n".join(
        f"                       {f'{vname}({i+1})':<{len(vname)+idx_w+2+1}}= {v:.2f},"
        for i, v in enumerate(tg_profile)
    )

    # Remove any existing XUNIF_TG_SOIL(*) lines (with or without trailing comma).
    # This avoids duplicates even if the namelist already contains old entries.
    content = _re.sub(r'[ \t]*XUNIF_TG_SOIL\(\d+\)\s*=\s*[0-9.]+,?[ \t]*\n?', '', content)

    # Insert new block inside the NAM_PREP_ISBA group, if present.
    new_content = _re.sub(
        r'(?si)(^&NAM_PREP_ISBA\b.*?)(^\s*/\s*$)',
        lambda m: m.group(1).rstrip() + "\n" + new_lines + "\n" + m.group(2),
        content,
        count=1,
        flags=_re.MULTILINE
    )
    if new_content == content:
        # Fallback: insert before the first closing slash in the file.
        new_content = _re.sub(
            r'(?m)^(\s*/\s*)$',
            lambda m: new_lines + "\n" + m.group(0),
            content,
            count=1
        )
        if new_content == content:
            new_content = content.rstrip() + "\n" + new_lines + "\n"

    with open(namelist_path, 'w') as f:
        f.write(new_content)

    print(f"    ✅ OPTIONS.nam updated with {n} XUNIF_TG_SOIL values.")


def _update_prep_txt_tg(prep_path, tg_profile):
    """
    In PREP.txt, overwrite the value of every &NATURE TGnPm entry whose
    current value is NOT the SURFEX undefined sentinel (1D+21).
    Undefined entries are left untouched; only the patch(es) that already
    carry a defined temperature are updated.
    Layer index mapping: TGn → tg_profile[n-1].
    """
    UNDEF = "0.10000000000000000D+21"

    with open(prep_path) as f:
        lines = f.readlines()

    n_replaced = 0
    i = 0
    while i < len(lines):
        m = _re.match(r'\s*&NATURE\s+(TG(\d+)P\d+)', lines[i])
        if m:
            layer_idx = int(m.group(2)) - 1          # 0-based
            # PREP.txt block: header / description / value
            if i + 2 < len(lines):
                val_line = lines[i + 2].strip()
                if val_line != UNDEF and layer_idx < len(tg_profile):
                    # Format value in Fortran D-notation to match SURFEX output
                    val_f = f"{tg_profile[layer_idx]:.17E}"
                    val_f = val_f.replace('E+0', 'D+0').replace('E-0', 'D-0') \
                                 .replace('E+',  'D+').replace('E-',  'D-')
                    lines[i + 2] = f"      {val_f}\n"
                    n_replaced += 1
        i += 1

    with open(prep_path, 'w') as f:
        f.writelines(lines)

    print(f"    ✅ PREP.txt updated: {n_replaced} defined TG entries replaced.")


def _update_prep_nc_tg(prep_path, tg_profile):
    """
    In PREP.nc, overwrite every TGnPm variable whose current value is
    NOT masked (fill value 1e+20) with tg_profile[n-1] (K).
    """
    n_replaced = 0
    with nc.Dataset(prep_path, 'r+') as ds:
        tg_vars = [v for v in ds.variables if _re.match(r'TG\d+P\d+$', v)]
        for vname in tg_vars:
            m = _re.match(r'TG(\d+)P\d+', vname)
            layer_idx = int(m.group(1)) - 1          # 0-based
            if layer_idx >= len(tg_profile):
                continue
            var = ds[vname]
            val = var[:]
            # Skip if fully masked (undefined)
            if isinstance(val, np.ma.MaskedArray) and val.mask.all():
                continue
            # Skip if all values equal the fill value (unmasked file)
            fv = getattr(var, '_FillValue', None)
            if fv is not None and not isinstance(val, np.ma.MaskedArray):
                if np.all(val == fv):
                    continue
            var[:] = tg_profile[layer_idx]
            n_replaced += 1

    print(f"    ✅ PREP.nc updated: {n_replaced} defined TG variables replaced.")


def _update_namelist_hug(namelist_path, hug_profile):
    """
    Replace all XUNIF_HUG_SOIL(*) lines in OPTIONS.nam with values from
    hug_profile ([0-1] fraction, 0-based list), inserted before the first
    closing '/' of the namelist.
    """
    with open(namelist_path) as f:
        content = f.read()

    n     = len(hug_profile)
    idx_w = len(str(n))
    vname = "XUNIF_HUG_SOIL"
    new_lines = "\n".join(
        f"                       {f'{vname}({i+1})':<{len(vname)+idx_w+2+1}}= {v:.2f},"
        for i, v in enumerate(hug_profile)
    )

    # Remove any existing XUNIF_HUG_SOIL(*) lines (with or without trailing comma).
    content = _re.sub(r'[ \t]*XUNIF_HUG_SOIL\(\d+\)\s*=\s*[0-9.]+,?[ \t]*\n?', '', content)

    new_content = _re.sub(
        r'(?si)(^&NAM_PREP_ISBA\b.*?)(^\s*/\s*$)',
        lambda m: m.group(1).rstrip() + "\n" + new_lines + "\n" + m.group(2),
        content,
        count=1,
        flags=_re.MULTILINE
    )
    if new_content == content:
        new_content = _re.sub(
            r'(?m)^(\s*/\s*)$',
            lambda m: new_lines + "\n" + m.group(0),
            content,
            count=1
        )
        if new_content == content:
            new_content = content.rstrip() + "\n" + new_lines + "\n"

    with open(namelist_path, 'w') as f:
        f.write(new_content)

    print(f"    ✅ OPTIONS.nam updated with {n} XUNIF_HUG_SOIL values.")


def _update_prep_txt_wg(prep_path, hug_profile):
    """
    In PREP.txt, overwrite the value of every &NATURE WGnPm entry whose
    current value is NOT the SURFEX undefined sentinel (1D+21).
    Layer index mapping: WGn → hug_profile[n-1].
    """
    UNDEF = "0.10000000000000000D+21"

    with open(prep_path) as f:
        lines = f.readlines()

    n_replaced = 0
    i = 0
    while i < len(lines):
        m = _re.match(r'\s*&NATURE\s+(WG(\d+)P\d+)', lines[i])
        if m:
            layer_idx = int(m.group(2)) - 1
            if i + 2 < len(lines):
                val_line = lines[i + 2].strip()
                if val_line != UNDEF and layer_idx < len(hug_profile):
                    val_f = f"{hug_profile[layer_idx]:.17E}"
                    val_f = val_f.replace('E+0', 'D+0').replace('E-0', 'D-0') \
                                 .replace('E+',  'D+').replace('E-',  'D-')
                    lines[i + 2] = f"      {val_f}\n"
                    n_replaced += 1
        i += 1

    with open(prep_path, 'w') as f:
        f.writelines(lines)

    print(f"    ✅ PREP.txt updated: {n_replaced} defined WG entries replaced.")


def _update_prep_nc_wg(prep_path, hug_profile):
    """
    In PREP.nc, overwrite every WGnPm variable whose current value is NOT
    masked (fill value 1e+20) with hug_profile[n-1] ([0-1] fraction).
    """
    n_replaced = 0
    with nc.Dataset(prep_path, 'r+') as ds:
        wg_vars = [v for v in ds.variables if _re.match(r'WG\d+P\d+$', v)]
        for vname in wg_vars:
            m = _re.match(r'WG(\d+)P\d+', vname)
            layer_idx = int(m.group(1)) - 1
            if layer_idx >= len(hug_profile):
                continue
            var = ds[vname]
            val = var[:]
            if isinstance(val, np.ma.MaskedArray) and val.mask.all():
                continue
            fv = getattr(var, '_FillValue', None)
            if fv is not None and not isinstance(val, np.ma.MaskedArray):
                if np.all(val == fv):
                    continue
            var[:] = hug_profile[layer_idx]
            n_replaced += 1

    print(f"    ✅ PREP.nc updated: {n_replaced} defined WG variables replaced.")


def main():
    if len(sys.argv) != 4:
        print("Usage: python apply_soil_initialization.py <station_name> <osvas_path> <mode>")
        print("Mode: 'namelist' or 'prep'")
        sys.exit(1)

    station_name = sys.argv[1]
    osvas_path = sys.argv[2]
    mode = sys.argv[3]

    if mode not in ['namelist', 'prep']:
        print("Mode must be 'namelist' or 'prep'")
        sys.exit(1)

    # Load config
    config_path = os.path.join(osvas_path, "config_files", "Stations", station_name, f"{station_name}.yml")
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    init_cfg = config.get('Initialization_data', {})
    init_to_namelist = init_cfg.get('Init_to_namelist', False)
    init_to_prep = init_cfg.get('Init_to_prep', False)

    if mode == 'namelist' and not init_to_namelist:
        print("⏩ Skipping namelist initialization: Init_to_namelist=False")
        return
    if mode == 'prep' and not init_to_prep:
        print("⏩ Skipping prep initialization: Init_to_prep=False")
        return

    # Load profiles
    profile_path = os.path.join(osvas_path, "profiles", station_name)
    tg_profile_file = os.path.join(profile_path, "tg_profile.npy")
    hug_profile_file = os.path.join(profile_path, "hug_profile.npy")

    if not os.path.exists(tg_profile_file):
        print(f"❌ TG profile not found: {tg_profile_file}")
        sys.exit(1)

    tg_profile = np.load(tg_profile_file)
    print(f"✅ Loaded TG profile with {len(tg_profile)} layers")

    hug_profile = None
    if os.path.exists(hug_profile_file):
        hug_profile = np.load(hug_profile_file)
        print(f"✅ Loaded HUG profile with {len(hug_profile)} layers")
    else:
        print("ℹ️  No HUG profile found – skipping HUG updates")

    # Get expnames
    expnames = config['OSVAS_steps'].get('Expnames', [])
    if not expnames:
        print("⚠️  No Expnames defined – nothing to update.")
        return

    print(f"\n▶ Applying {mode} soil initialization profiles")

    for expname in expnames:
        run_dir = os.path.join(osvas_path, "RUNS", station_name, expname, "run")
        print(f"\n  [{expname}]  run_dir: {run_dir}")

        if mode == 'namelist':
            # Apply to OPTIONS.nam
            namelist_path = os.path.join(run_dir, "OPTIONS.nam")
            if os.path.exists(namelist_path):
                _update_namelist_tg(namelist_path, tg_profile)
                if hug_profile is not None:
                    _update_namelist_hug(namelist_path, hug_profile)
                else:
                    print("    ℹ️  No HUG profile available – XUNIF_HUG_SOIL not updated.")
            else:
                print(f"    ⚠️  OPTIONS.nam not found in {run_dir} – skipping.")

        elif mode == 'prep':
            # Apply to PREP files
            prep_txt = os.path.join(run_dir, "PREP.txt")
            prep_nc = os.path.join(run_dir, "PREP.nc")
            found_any = False
            if os.path.exists(prep_txt):
                print("    Updating PREP.txt …")
                _update_prep_txt_tg(prep_txt, tg_profile)
                if hug_profile is not None:
                    _update_prep_txt_wg(prep_txt, hug_profile)
                found_any = True
            if os.path.exists(prep_nc):
                print("    Updating PREP.nc …")
                _update_prep_nc_tg(prep_nc, tg_profile)
                if hug_profile is not None:
                    _update_prep_nc_wg(prep_nc, hug_profile)
                found_any = True
            if not found_any:
                print(f"    ⚠️  No PREP.txt or PREP.nc found in {run_dir} – skipping.")

    print(f"\n✅ {mode.capitalize()} soil initialization complete.")


if __name__ == "__main__":
    main()