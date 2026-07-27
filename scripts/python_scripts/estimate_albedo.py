#!/usr/bin/env python3
"""
Estimate surface albedo (NIR and VIS) from validation data.

This script:
1. Reads validation data from SQLite OBSTABLEs (SW_OUT, SW_IN)
2. Selects observations between 11:00-13:00 UTC daily
3. Calculates daily albedos as SW_OUT/SW_IN (broadband)
4. Computes monthly averages
5. Decomposes the broadband albedo into VIS/NIR/UV bands for vegetation and
   soil separately, using the station's vegetation cover fraction
   (Station_metadata.veg_fraction in the station yml) and a first-order
   spectral-shape assumption (see estimate_veg_and_soil_albedos). Soil is
   NOT copied from vegetation: its monthly value is derived from the
   in-situ measurement via a residual method (see estimate_soil_vis_monthly)
6. Generates namelist format text for the six SURFEX/ISBA namelist
   variables: XUNIF_ALB{NIR,VIS,UV}_{VEG,SOIL}
7. Saves output to station namelist directory

Useage:
    python3 estimate_albedo.py <station_name> <osvas_root> [--run-period start_date end_date]

Example:
    python3 estimate_albedo.py Cabauw /home/user/OSVAS --run-period "2017-11-01" "2018-01-31"
"""

import os
import sys
import sqlite3
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
from collections import defaultdict
import yaml


# ---------------------------------------------------------------------------
# First-order spectral decomposition assumptions
# ---------------------------------------------------------------------------
# The radiometer measures broadband albedo (SW_OUT/SW_IN), integrated over the
# whole solar spectrum. SURFEX/ISBA needs it split into VIS and NIR bands
# (UV is folded into VIS, since ISBA has no separate UV band). We approximate
# the broadband value as a solar-irradiance-weighted average of UV/VIS/NIR
# band albedos, and assume a fixed *spectral shape* (ratios between bands)
# taken from typical literature values, anchoring the absolute level to the
# in-situ measurement. These are first-order, order-of-magnitude assumptions
# meant for configuring an experiment quickly -- not a spectral retrieval.

# Fraction of broadband solar irradiance carried by each band
W_UV, W_VIS, W_NIR = 0.05, 0.45, 0.50

# Vegetation (closed forest canopy): strong VIS absorption (chlorophyll),
# strong NIR scattering (multiple within-canopy reflections), UV slightly
# below VIS.
VEG_UV_VIS_RATIO = 0.83
VEG_NIR_VIS_RATIO = 4.0

# Soil (forest floor, humid/organic litter under canopy shade): much flatter
# spectrum than vegetation.
SOIL_UV_VIS_RATIO = 0.6
SOIL_NIR_VIS_RATIO = 1.8

# Prior for forest-floor VIS albedo (humid/organic litter, shaded) -- used
# only as an anchor; the monthly value is then adjusted using the in-situ
# signal (see estimate_soil_vis_monthly).
SOIL_VIS_PRIOR = 0.08

# Physical plausibility bounds used to clip the decomposition
VIS_RANGE = (0.02, 0.40)
NIR_RANGE = (0.05, 0.60)


def split_spectral_bands(alpha_total, uv_vis_ratio, nir_vis_ratio,
                          w_uv=W_UV, w_vis=W_VIS, w_nir=W_NIR):
    """Decompose a broadband albedo into UV/VIS/NIR assuming a fixed spectral
    shape (band ratios relative to VIS) and solar-irradiance band weights.

    alpha_total = w_uv*(r_uv*VIS) + w_vis*VIS + w_nir*(r_nir*VIS)
    => VIS = alpha_total / (w_uv*r_uv + w_vis + w_nir*r_nir)
    """
    denom = w_uv * uv_vis_ratio + w_vis + w_nir * nir_vis_ratio
    vis = alpha_total / denom
    uv = uv_vis_ratio * vis
    nir = nir_vis_ratio * vis
    return uv, vis, nir


def estimate_soil_vis_monthly(monthly_total, f_soil, soil_vis_prior=SOIL_VIS_PRIOR,
                               damping=0.3):
    """First-order monthly soil VIS albedo estimate that still makes use of
    the in-situ signal, even though soil's contribution to the total mixture
    is small.

    Rationale: under a closed canopy the vegetation contribution is large
    and fairly stable across the year (roughly constant phenology), while
    forest-floor/soil albedo is the surface most likely to vary quickly
    month to month (moisture, litter, occasional snow). So instead of
    freezing soil at a fixed tabulated value, we attribute part of the
    *anomaly* of the measured broadband albedo relative to its annual mean
    to the soil term, inversely scaled by its small areal weight (f_soil).

    `damping` (0-1) tempers this attribution. Dividing the raw anomaly by a
    very small f_soil (e.g. 0.04) amplifies it ~25x, which turns ordinary
    measurement noise into implausible swings once f_soil gets this small.
    damping<1 assumes only part of the total's monthly variability really
    comes from the forest floor (the rest being canopy variability or noise
    not worth resolving at this fraction of cover); damping=1 recovers the
    undamped residual method, damping=0 freezes soil at soil_vis_prior.

    Caveat: this still assumes a roughly evergreen canopy with stable
    albedo; for deciduous forest experiencing leaf-off periods, part of the
    seasonal anomaly is actually due to vegetation, not soil. Values are
    clipped to a physically plausible VIS range regardless.

    !!! ONLY VALID FOR EVERGREEN/PERENNIAL CANOPIES !!!
    In a deciduous forest this assumption breaks down for two compounding
    reasons: (1) leafless-canopy albedo (bare branches/trunks) is itself
    quite different from foliage albedo, so alpha_veg is NOT stable across
    the year as assumed here; and (2) the *radiative* vegetation fraction
    drops sharply in winter (the canopy becomes far more transparent to
    shortwave), so the true f_soil in winter is much larger than the
    structural/summer f_veg used as a constant here. Applying this residual
    method to a deciduous site will misattribute canopy-driven seasonal
    variability to the soil. See main() for the runtime warning tied to
    Station_metadata.canopy_type.
    """
    annual_mean = np.mean(monthly_total)
    f_soil = np.clip(f_soil, 1e-3, 1.0)
    soil_vis = [
        soil_vis_prior + damping * (month_val - annual_mean) / f_soil
        for month_val in monthly_total
    ]
    return list(np.clip(soil_vis, *VIS_RANGE))


def estimate_veg_and_soil_albedos(monthly_total, f_veg):
    """Given monthly broadband albedo and the vegetation cover fraction,
    return monthly NIR/VIS albedo lists for vegetation and soil.

    Steps:
      1. Estimate a monthly soil VIS (and derived UV/NIR) using the
         in-situ residual method above.
      2. Back out the vegetation-only broadband albedo from the linear
         mixture: alpha_total = f_veg*alpha_veg + f_soil*alpha_soil.
      3. Split alpha_veg into VIS/NIR using the fixed canopy spectral shape.
    """
    f_veg = np.clip(f_veg, 0.01, 1.0)
    f_soil = 1.0 - f_veg

    soil_vis_monthly = estimate_soil_vis_monthly(monthly_total, f_soil)

    nir_veg, vis_veg, uv_veg = [], [], []
    nir_soil, vis_soil, uv_soil = [], [], []
    for alpha_total, soil_vis in zip(monthly_total, soil_vis_monthly):
        # soil_vis is already the anchor (from the residual method above);
        # derive UV/NIR from it using the fixed soil spectral shape.
        s_uv = SOIL_UV_VIS_RATIO * soil_vis
        s_nir = SOIL_NIR_VIS_RATIO * soil_vis
        s_vis = soil_vis
        soil_total_est = W_UV * s_uv + W_VIS * s_vis + W_NIR * s_nir

        alpha_veg = (alpha_total - f_soil * soil_total_est) / f_veg
        alpha_veg = max(alpha_veg, 0.01)  # guard against noisy/edge months

        v_uv, v_vis, v_nir = split_spectral_bands(alpha_veg, VEG_UV_VIS_RATIO, VEG_NIR_VIS_RATIO)

        vis_veg.append(float(np.clip(v_vis, *VIS_RANGE)))
        nir_veg.append(float(np.clip(v_nir, *NIR_RANGE)))
        uv_veg.append(float(np.clip(v_uv, *VIS_RANGE)))
        vis_soil.append(float(np.clip(s_vis, *VIS_RANGE)))
        nir_soil.append(float(np.clip(s_nir, *NIR_RANGE)))
        uv_soil.append(float(np.clip(s_uv, *VIS_RANGE)))

    return {
        'nir_veg': nir_veg,
        'vis_veg': vis_veg,
        'uv_veg': uv_veg,
        'nir_soil': nir_soil,
        'vis_soil': vis_soil,
        'uv_soil': uv_soil,
    }


def get_obstable_files(obstable_path, osvas_root, run_start=None, run_end=None):
    """Find SQLite OBSTABLE files in the given obstable_path within run period.

    `obstable_path` is either a station name or 'common_obstables'.
    """
    obstable_dir = Path(osvas_root) / 'sqlites' / 'OBSTABLES' / 'validation_data' / obstable_path

    if not obstable_dir.exists():
        print(f"❌ Error: OBSTABLE directory not found: {obstable_dir}")
        return []

    obstable_files = sorted(obstable_dir.glob('OBSTABLE_*.sqlite'))

    if run_start and run_end:
        start_year = int(run_start.split('-')[0])
        end_year = int(run_end.split('-')[0])
        obstable_files = [f for f in obstable_files
                         if start_year <= int(f.stem.split('_')[1]) <= end_year]

    return obstable_files


def read_validation_data(obstable_files, station_sid=None, run_start=None, run_end=None):
    """Read SW_OUT and SW_IN from SQLite OBSTABLEs, filtering by run period.

    If `station_sid` is provided and OBSTABLEs contain multiple stations,
    filter to that SID.
    """
    data_list = []
    
    for obstable_file in obstable_files:
        print(f"  Reading: {obstable_file.name}")
        try:
            with sqlite3.connect(str(obstable_file)) as conn:
                query = "SELECT * FROM SYNOP WHERE SW_OUT IS NOT NULL AND SW_IN IS NOT NULL AND SW_IN > 0"
                df = pd.read_sql_query(query, conn)
                
                if df.empty:
                    continue
                
                # Convert Unix seconds to datetime
                df['valid_dttm'] = pd.to_datetime(df['valid_dttm'], unit='s', utc=True)
                # If a station SID is provided and the OBSTABLEs contain multiple
                # stations (common obstables), filter to only the requested SID.
                if station_sid is not None:
                    # Case-insensitive check for SID column
                    cols_upper = {c.upper(): c for c in df.columns}
                    if 'SID' in cols_upper:
                        sid_col = cols_upper['SID']
                        df = df[df[sid_col] == station_sid]
                    else:
                        # No SID column found; assume file is station-specific and keep as is
                        pass
                data_list.append(df)
        except Exception as e:
            print(f"  ⚠️  Warning: Error reading {obstable_file}: {e}")
    
    if not data_list:
        print("❌ No SW_OUT/SW_IN data found in OBSTABLES")
        return pd.DataFrame()
    
    df_all = pd.concat(data_list, ignore_index=True)
    
    # Filter by run period if specified
    if run_start and run_end:
        run_start_dt = pd.to_datetime(run_start, utc=True)
        run_end_dt = pd.to_datetime(run_end, utc=True)
        df_all = df_all[(df_all['valid_dttm'] >= run_start_dt) & 
                        (df_all['valid_dttm'] <= run_end_dt)]
    
    print(f"  Loaded {len(df_all)} records with valid SW_OUT/SW_IN")
    return df_all


def select_midday_data(df, hour_start=11, hour_end=13):
    """Select data between specified hours (UTC) for each day."""
    df = df.copy()
    df['hour'] = df['valid_dttm'].dt.hour
    df['date'] = df['valid_dttm'].dt.date
    
    # Filter to midday window (11:00-13:00 UTC)
    df_midday = df[(df['hour'] >= hour_start) & (df['hour'] < hour_end)]
    
    print(f"  Selected {len(df_midday)} records between {hour_start:02d}:00-{hour_end:02d}:00 UTC")
    return df_midday


def calculate_daily_albedos(df_midday):
    """Calculate daily average albedo from midday observations."""
    df = df_midday.copy()
    
    # Calculate albedo for each observation
    df['albedo'] = df['SW_OUT'] / df['SW_IN']
    
    # Remove unrealistic albedos (should be between ~0.05 and ~0.95)
    df_valid = df[(df['albedo'] >= 0.0) & (df['albedo'] <= 1.0)]
    
    if len(df_valid) < len(df):
        removed = len(df) - len(df_valid)
        print(f"  Removed {removed} unrealistic albedos (outside [0, 1])")
    
    # Average by date
    daily_albedos = df_valid.groupby('date')['albedo'].mean().reset_index()
    daily_albedos.columns = ['date', 'albedo']
    
    print(f"  Calculated {len(daily_albedos)} daily average albedos")
    return daily_albedos


def compute_monthly_averages(daily_albedos):
    """Compute monthly average albedos from daily data.
    
    If the data spans more than 12 months, only the last complete calendar
    year is used (e.g. Nov 2022 – Jan 2024 → uses Jan–Dec 2023).
    """
    daily_albedos = daily_albedos.copy()
    daily_albedos['date'] = pd.to_datetime(daily_albedos['date'])

    # Determine the year to use
    min_date = daily_albedos['date'].min()
    max_date = daily_albedos['date'].max()
    span_months = (max_date.year - min_date.year) * 12 + (max_date.month - min_date.month)

    if span_months > 12:
        # Find the last calendar year that is fully contained in the data
        last_year = max_date.year
        if max_date.month < 12 or max_date.day < 31:
            last_year -= 1  # current year is incomplete, step back one

        print(f"  Data spans {span_months} months — using calendar year {last_year}")
        mask = daily_albedos['date'].dt.year == last_year
        daily_albedos = daily_albedos[mask]

        if daily_albedos.empty:
            raise ValueError(f"No data found for selected year {last_year}.")

    daily_albedos['month'] = daily_albedos['date'].dt.month
    monthly_avg = daily_albedos.groupby('month')['albedo'].mean().to_dict()

    # Fill any missing months with the annual mean of the selected period
    annual_mean = daily_albedos['albedo'].mean()
    monthly_values = [monthly_avg.get(m, annual_mean) for m in range(1, 13)]

    print("\n  Monthly albedo averages:")
    for month in range(1, 13):
        print(f"    Month {month:2d}: {monthly_values[month-1]:.8f}")

    return monthly_values


def generate_namelist_block(vegtype, albedo_monthly, param_name):
    """Generate namelist text block for albedo parameters.
    
    Parameters:
    -----------
    vegtype : int
        Vegetation type index (e.g., 10 for Cabauw)
    albedo_monthly : list
        List of 12 monthly albedo values
    param_name : str
        Parameter name (e.g., 'XUNIF_ALBNIR_VEG', 'XUNIF_ALBVIS_SOIL')
    
    Returns:
    --------
    str : Formatted namelist block
    """
    lines = []
    for month in range(1, 13):
        value = albedo_monthly[month - 1]
        comma = "," if month < 12 else ","
        line = f"                       {param_name}({vegtype},{month:2d}) = {value:.8f}{comma}"
        lines.append(line)
    
    return '\n'.join(lines)


def generate_complete_albedo_namelist(vegtype, nir_veg, vis_veg, uv_veg,
                                       nir_soil, vis_soil, uv_soil, f_veg):
    """Generate complete namelist text with all six albedo parameters
    (VIS/NIR/UV x vegetation/soil), using independently decomposed series
    (first-order spectral split anchored on the in-situ measured broadband
    albedo, see estimate_veg_and_soil_albedos)."""
    output = []
    output.append("\n! Estimated albedos from validation data (SW_OUT/SW_IN 11:00-13:00 UTC)")
    output.append(f"! Decomposed into VIS/NIR/UV for vegetation and soil assuming f_veg={f_veg:.3f}")
    output.append("! (first-order spectral split, see estimate_veg_and_soil_albedos in this script)\n")

    # Vegetation NIR albedo
    output.append("! Vegetation NIR albedo (monthly)")
    output.append(generate_namelist_block(vegtype, nir_veg, 'XUNIF_ALBNIR_VEG'))
    output.append("")

    # Vegetation VIS albedo
    output.append("! Vegetation VIS albedo (monthly)")
    output.append(generate_namelist_block(vegtype, vis_veg, 'XUNIF_ALBVIS_VEG'))
    output.append("")

    # Vegetation UV albedo
    output.append("! Vegetation UV albedo (monthly)")
    output.append(generate_namelist_block(vegtype, uv_veg, 'XUNIF_ALBUV_VEG'))
    output.append("")

    # Soil NIR albedo -- derived from the in-situ residual method, not a
    # fixed default and not simply copied from vegetation
    output.append("! Soil NIR albedo (monthly) - derived from in-situ residual (low sensitivity)")
    output.append(generate_namelist_block(vegtype, nir_soil, 'XUNIF_ALBNIR_SOIL'))
    output.append("")

    # Soil VIS albedo
    output.append("! Soil VIS albedo (monthly) - derived from in-situ residual (low sensitivity)")
    output.append(generate_namelist_block(vegtype, vis_soil, 'XUNIF_ALBVIS_SOIL'))
    output.append("")

    # Soil UV albedo
    output.append("! Soil UV albedo (monthly) - derived from in-situ residual (low sensitivity)")
    output.append(generate_namelist_block(vegtype, uv_soil, 'XUNIF_ALBUV_SOIL'))
    output.append("")

    return '\n'.join(output)


def main():
    parser = argparse.ArgumentParser(
        description='Estimate surface albedo from validation data'
    )
    parser.add_argument('station_name', help='Station name')
    parser.add_argument('osvas_root', help='OSVAS root directory')
    parser.add_argument('--run-period', nargs=2, 
                       metavar=('START_DATE', 'END_DATE'),
                       help='Run period (YYYY-MM-DD format). If not provided, uses all available data.')
    parser.add_argument('--output', help='Output file path (default: namelists/{station_name}/albedo_estimates.nam)')
    
    args = parser.parse_args()
    
    station_name = args.station_name
    osvas_root = Path(args.osvas_root).expanduser().resolve()
    
    print(f"\n{'='*70}")
    print(f"Estimating surface albedos for {station_name}")
    print(f"{'='*70}\n")
    
    # Get run period
    run_start, run_end = None, None
    if args.run_period:
        run_start, run_end = args.run_period
        print(f"Run period: {run_start} to {run_end}")
    else:
        print("Using all available validation data")
    print()
    
    # Read station config early to determine if validation uses common obstables
    config_file = osvas_root / 'config_files' / 'Stations' / station_name / f'{station_name}.yml'
    station_sid = None
    common_obstable = False
    if config_file.exists():
        with open(config_file) as f:
            config = yaml.safe_load(f)
        station_sid = config.get('Station_metadata', {}).get('SID')
        common_obstable = config.get('Validation_data', {}).get('common_obstable', False)

    # Step 1: Find and read OBSTABLE files
    print("Step 1: Reading validation data from OBSTABLEs")
    obstable_path = 'common_obstables' if common_obstable else station_name
    obstable_files = get_obstable_files(obstable_path, osvas_root, run_start, run_end)
    
    if not obstable_files:
        print(f"❌ No OBSTABLE files found for {station_name}")
        sys.exit(1)
    
    print(f"  Found {len(obstable_files)} OBSTABLE files")
    df_all = read_validation_data(obstable_files, station_sid=station_sid, run_start=run_start, run_end=run_end)
    
    if df_all.empty:
        print("❌ No valid radiation data found")
        sys.exit(1)
    
    # Step 2: Select midday data (11:00-13:00 UTC)
    print("\nStep 2: Selecting midday observations (11:00-13:00 UTC)")
    df_midday = select_midday_data(df_all, hour_start=11, hour_end=13)
    
    if df_midday.empty:
        print("❌ No midday data found in specified time window")
        sys.exit(1)
    
    # Step 3: Calculate daily albedos
    print("\nStep 3: Calculating daily albedos (SW_OUT/SW_IN)")
    daily_albedos = calculate_daily_albedos(df_midday)
    
    if daily_albedos.empty:
        print("❌ Could not calculate daily albedos")
        sys.exit(1)
    
    # Step 4: Compute monthly averages
    print("\nStep 4: Computing monthly averages")
    monthly_albedos = compute_monthly_averages(daily_albedos)

    # Step 5: Read vegtype and vegetation fraction from station config, then
    # decompose the measured broadband albedo into VIS/NIR for vegetation
    # and soil (first-order spectral split, see estimate_veg_and_soil_albedos)
    print("\nStep 5: Decomposing broadband albedo into VIS/NIR (vegetation/soil)")

    config_file = osvas_root / 'config_files' / 'Stations' / station_name / f'{station_name}.yml'
    if not config_file.exists():
        print(f"⚠️  Warning: Station config not found: {config_file}")
        vegtype = 10  # default
        f_veg = 1.0
    else:
        with open(config_file) as f:
            config = yaml.safe_load(f)
        vegtype = config.get('Station_metadata', {}).get('vegtype', 10)
        f_veg = config.get('Station_metadata', {}).get('veg_fraction', None)
        if f_veg is None:
            print("  ⚠️  'veg_fraction' not found in station config — assuming f_veg=1.0 "
                  "(no soil correction). Add Station_metadata.veg_fraction to the station "
                  "yml to enable it.")
            f_veg = 1.0

    canopy_type = None
    if config_file.exists():
        canopy_type = config.get('Station_metadata', {}).get('canopy_type', None)

    if f_veg < 0.999 and canopy_type not in ('evergreen', 'perennial', 'perennifolio'):
        print(
            "\n" + "!" * 78 + "\n"
            "!! WARNING: soil albedo decomposition assumes an EVERGREEN/PERENNIAL\n"
            "!! canopy (stable albedo year-round). Station_metadata.canopy_type is\n"
            f"!! {'not set' if canopy_type is None else repr(canopy_type)} for '{station_name}'.\n"
            "!!\n"
            "!! If this is a DECIDUOUS forest, the monthly XUNIF_ALB*_SOIL values\n"
            "!! below are NOT reliable: leaf-off winter months change both the\n"
            "!! canopy's own albedo and the effective (radiative) vegetation\n"
            "!! fraction, so seasonal variability gets misattributed to soil.\n"
            "!! Set Station_metadata.canopy_type: evergreen in the station yml to\n"
            "!! silence this warning once confirmed, or treat the SOIL values as\n"
            "!! unreliable and replace them with a fixed literature value instead.\n"
            + "!" * 78 + "\n"
        )

    print(f"  Using vegtype: {vegtype}, f_veg: {f_veg:.3f}")

    split = estimate_veg_and_soil_albedos(monthly_albedos, f_veg)
    nir_albedos, vis_albedos, uv_albedos = split['nir_veg'], split['vis_veg'], split['uv_veg']
    nir_soil_albedos, vis_soil_albedos, uv_soil_albedos = split['nir_soil'], split['vis_soil'], split['uv_soil']

    namelist_text = generate_complete_albedo_namelist(
        vegtype, nir_albedos, vis_albedos, uv_albedos,
        nir_soil_albedos, vis_soil_albedos, uv_soil_albedos, f_veg
    )
    
    # Step 6: Save output
    print("\nStep 6: Saving results")
    
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = osvas_root / 'namelists' / station_name / 'albedo_estimates.nam'
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(namelist_text)
    
    print(f"  ✅ Albedo estimates saved to: {output_path}")
    print(f"\n  VEG  NIR: min={min(nir_albedos):.8f}, max={max(nir_albedos):.8f}, mean={np.mean(nir_albedos):.8f}")
    print(f"  VEG  VIS: min={min(vis_albedos):.8f}, max={max(vis_albedos):.8f}, mean={np.mean(vis_albedos):.8f}")
    print(f"  VEG  UV : min={min(uv_albedos):.8f}, max={max(uv_albedos):.8f}, mean={np.mean(uv_albedos):.8f}")
    print(f"  SOIL NIR: min={min(nir_soil_albedos):.8f}, max={max(nir_soil_albedos):.8f}, mean={np.mean(nir_soil_albedos):.8f}")
    print(f"  SOIL VIS: min={min(vis_soil_albedos):.8f}, max={max(vis_soil_albedos):.8f}, mean={np.mean(vis_soil_albedos):.8f}")
    print(f"  SOIL UV : min={min(uv_soil_albedos):.8f}, max={max(uv_soil_albedos):.8f}, mean={np.mean(uv_soil_albedos):.8f}")
    print(f"\n{'='*70}")
    print("✅ Albedo estimation completed successfully")
    print(f"{'='*70}\n")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
