#!/usr/bin/env python3
"""
Estimate surface albedo (NIR, VIS, UV) from validation data.

This script:
1. Reads validation data from SQLite OBSTABLEs (SW_OUT, SW_IN)
2. Selects observations between 11:00-13:00 UTC daily
3. Calculates daily albedos as SW_OUT/SW_IN (broadband)
4. Computes monthly averages, using only that month's own data (no annual
   mean is computed or relied upon). Months without data are filled from
   the closest month that has data (see compute_monthly_averages).
5. Decomposes each month's broadband albedo into VIS/NIR/UV using a single
   first-order spectral-shape assumption (see estimate_surface_albedos).
   The SAME decomposition is used for vegetation and soil -- soil is not
   derived from vegetation cover fraction or from a separate residual
   method, it is simply the same spectral split scaled up slightly to
   reflect that soil is typically somewhat brighter than vegetation.
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
# whole solar spectrum. SURFEX/ISBA needs it split into VIS, NIR and UV bands.
# We approximate the broadband value as a solar-irradiance-weighted average of
# UV/VIS/NIR band albedos, and assume a fixed *spectral shape* (ratios between
# bands) taken from typical literature values, anchoring the absolute level to
# the in-situ measurement for that same month. These are first-order,
# order-of-magnitude assumptions meant for configuring an experiment quickly
# -- not a spectral retrieval.
#
# Vegetation and soil are given by the SAME spectral decomposition of the
# same measured monthly value -- there is no vegetation-fraction unmixing and
# no separate soil spectral shape. Soil is only distinguished from vegetation
# by a single "soil is usually brighter" boost factor applied uniformly
# across all three bands.

# Fraction of broadband solar irradiance carried by each band
W_UV, W_VIS, W_NIR = 0.05, 0.45, 0.50

# Single spectral shape (ratios relative to VIS) used for both surfaces.
# Values taken from typical closed-canopy literature ranges: strong VIS
# absorption (chlorophyll), strong NIR scattering (multiple within-canopy
# reflections), UV slightly below VIS.
SURFACE_UV_VIS_RATIO = 0.23
SURFACE_NIR_VIS_RATIO = 1.15

# Soil is usually somewhat brighter than vegetation across the solar
# spectrum (less absorption, no chlorophyll/photosynthetic pigments), so its
# namelist values are the same spectral split scaled up by this factor. This
# is a deliberately simple, uniform boost -- not a different spectral shape.
SOIL_BOOST_FACTOR = 1.20

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


def estimate_surface_albedos(monthly_total, soil_boost_factor=SOIL_BOOST_FACTOR):
    """Decompose each month's broadband albedo into VIS/NIR/UV, using a
    single spectral-shape strategy applied identically to vegetation and
    soil.

    Each month is decomposed independently from that month's own measured
    value only -- no annual mean, no vegetation-fraction correction, no
    separate residual method for soil. Vegetation values come directly from
    the spectral split; soil values are the same split scaled up by
    `soil_boost_factor` (soil is typically somewhat brighter than
    vegetation), then clipped to a physically plausible range.
    """
    nir_veg, vis_veg, uv_veg = [], [], []
    nir_soil, vis_soil, uv_soil = [], [], []

    for alpha_total in monthly_total:
        uv, vis, nir = split_spectral_bands(alpha_total, SURFACE_UV_VIS_RATIO,
                                             SURFACE_NIR_VIS_RATIO)

        vis_veg.append(float(np.clip(vis, *VIS_RANGE)))
        nir_veg.append(float(np.clip(nir, *NIR_RANGE)))
        uv_veg.append(float(np.clip(uv, *VIS_RANGE)))

        vis_soil.append(float(np.clip(vis * soil_boost_factor, *VIS_RANGE)))
        nir_soil.append(float(np.clip(nir * soil_boost_factor, *NIR_RANGE)))
        uv_soil.append(float(np.clip(uv * soil_boost_factor, *VIS_RANGE)))

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


def _fill_missing_months(monthly_avg):
    """Fill months without data using the closest month (by calendar
    distance, wrapping across the year boundary) that does have data.

    No annual mean is used: each filled month simply borrows the value of
    its nearest available neighbour, so a filled month always reflects a
    real measured month rather than a whole-period average.
    """
    available_months = sorted(monthly_avg.keys())
    if not available_months:
        raise ValueError("No monthly data available to fill from.")

    monthly_values = []
    for m in range(1, 13):
        if m in monthly_avg:
            monthly_values.append(monthly_avg[m])
        else:
            nearest = min(available_months,
                          key=lambda am: min(abs(am - m), 12 - abs(am - m)))
            monthly_values.append(monthly_avg[nearest])
    return monthly_values


def compute_monthly_averages(daily_albedos):
    """Compute monthly average albedos from daily data.

    Each month's value comes only from that month's own daily observations
    (no annual mean is computed). If the data spans more than 12 months,
    only the most recent 12 months (a rolling 365-day window ending at the
    last available observation) are used to pick a single representative
    year's worth of data. Months with no data in that window are filled
    from the closest month that has data (see _fill_missing_months) rather
    than from any whole-period average.

    A rolling window (rather than requiring exact alignment with Jan 1 -
    Dec 31 of a calendar year) is used deliberately: anchoring on "last
    observation is in December with day==31" is fragile -- if the very
    last valid midday observation happens to fall a day or two before the
    31st (a normal occurrence with real data), that calendar-year check
    would wrongly discard the whole most-recent year and fall back to the
    previous one, even though it is almost entirely covered by data.
    """
    daily_albedos = daily_albedos.copy()
    daily_albedos['date'] = pd.to_datetime(daily_albedos['date'])

    # Determine the window to use
    min_date = daily_albedos['date'].min()
    max_date = daily_albedos['date'].max()
    span_months = (max_date.year - min_date.year) * 12 + (max_date.month - min_date.month)

    if span_months > 12:
        window_start = max_date - pd.Timedelta(days=365)
        print(f"  Data spans {span_months} months — using the most recent 12 months "
              f"({window_start.date()} to {max_date.date()})")
        mask = daily_albedos['date'] >= window_start
        daily_albedos = daily_albedos[mask]

        if daily_albedos.empty:
            raise ValueError(f"No data found in the most recent 12 months "
                              f"({window_start.date()} to {max_date.date()}).")

    daily_albedos['month'] = daily_albedos['date'].dt.month
    monthly_avg = daily_albedos.groupby('month')['albedo'].mean().to_dict()

    missing = [m for m in range(1, 13) if m not in monthly_avg]
    if missing:
        print(f"  Months without data: {missing} — filling each from its "
              f"closest month with data")

    monthly_values = _fill_missing_months(monthly_avg)

    print("\n  Monthly albedo averages:")
    for month in range(1, 13):
        flag = "  (filled)" if month in missing else ""
        print(f"    Month {month:2d}: {monthly_values[month-1]:.8f}{flag}")

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
                                       nir_soil, vis_soil, uv_soil):
    """Generate complete namelist text with all six albedo parameters
    (VIS/NIR/UV x vegetation/soil). Both surfaces come from the same
    monthly spectral decomposition (see estimate_surface_albedos); soil is
    simply that same split scaled up by SOIL_BOOST_FACTOR."""
    output = []
    output.append("\n! Estimated albedos from validation data (SW_OUT/SW_IN 11:00-13:00 UTC)")
    output.append("! Single spectral-decomposition strategy applied to both vegetation and")
    output.append(f"! soil per month (no annual mean, no vegetation fraction); soil = same split "
                  f"x {SOIL_BOOST_FACTOR:.2f}")
    output.append("! (see estimate_surface_albedos in this script)\n")

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

    # Soil NIR albedo
    output.append("! Soil NIR albedo (monthly) - same spectral split as vegetation, scaled up")
    output.append(generate_namelist_block(vegtype, nir_soil, 'XUNIF_ALBNIR_SOIL'))
    output.append("")

    # Soil VIS albedo
    output.append("! Soil VIS albedo (monthly) - same spectral split as vegetation, scaled up")
    output.append(generate_namelist_block(vegtype, vis_soil, 'XUNIF_ALBVIS_SOIL'))
    output.append("")

    # Soil UV albedo
    output.append("! Soil UV albedo (monthly) - same spectral split as vegetation, scaled up")
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
    
    # Step 4: Compute monthly averages (own-month data only, nearest-month fill)
    print("\nStep 4: Computing monthly averages")
    monthly_albedos = compute_monthly_averages(daily_albedos)

    # Step 5: Read vegtype from station config, then decompose each month's
    # broadband albedo into VIS/NIR/UV using the single shared spectral
    # strategy for both vegetation and soil (see estimate_surface_albedos)
    print("\nStep 5: Decomposing broadband albedo into VIS/NIR/UV (vegetation & soil)")

    if not config_file.exists():
        print(f"⚠️  Warning: Station config not found: {config_file}")
        vegtype = 10  # default
    else:
        vegtype = config.get('Station_metadata', {}).get('vegtype', 10)

    print(f"  Using vegtype: {vegtype}")

    split = estimate_surface_albedos(monthly_albedos)
    nir_albedos, vis_albedos, uv_albedos = split['nir_veg'], split['vis_veg'], split['uv_veg']
    nir_soil_albedos, vis_soil_albedos, uv_soil_albedos = split['nir_soil'], split['vis_soil'], split['uv_soil']

    namelist_text = generate_complete_albedo_namelist(
        vegtype, nir_albedos, vis_albedos, uv_albedos,
        nir_soil_albedos, vis_soil_albedos, uv_soil_albedos
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
