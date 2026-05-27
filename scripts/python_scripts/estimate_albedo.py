#!/usr/bin/env python3
"""
Estimate surface albedo (NIR and VIS) from validation data.

This script:
1. Reads validation data from SQLite OBSTABLEs (SW_OUT, SW_IN)
2. Selects observations between 11:00-13:00 UTC daily
3. Calculates daily albedos as SW_OUT/SW_IN
4. Computes monthly averages
5. Generates namelist format text for both vegetation and soil
6. Saves output to station namelist directory

Useage:
    python3 estimate_albedo.py <station_name> <osvas_root> [--validation-period start_date end_date]

Example:
    python3 estimate_albedo.py Cabauw /home/user/OSVAS --validation-period "2017-11-01" "2018-01-31"
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


def get_obstable_files(station_name, osvas_root, val_start=None, val_end=None):
    """Find SQLite OBSTABLE files for a station within validation period."""
    obstable_dir = Path(osvas_root) / 'sqlites' / 'OBSTABLES' / 'validation_data' / station_name
    
    if not obstable_dir.exists():
        print(f"❌ Error: OBSTABLE directory not found: {obstable_dir}")
        return []
    
    obstable_files = sorted(obstable_dir.glob('OBSTABLE_*.sqlite'))
    
    if val_start and val_end:
        start_year = int(val_start.split('-')[0])
        end_year = int(val_end.split('-')[0])
        obstable_files = [f for f in obstable_files 
                         if start_year <= int(f.stem.split('_')[1]) <= end_year]
    
    return obstable_files


def read_validation_data(obstable_files, val_start=None, val_end=None):
    """Read SW_OUT and SW_IN from SQLite OBSTABLEs, filtering by validation period."""
    data_list = []
    
    for obstable_file in obstable_files:
        print(f"  Reading: {obstable_file.name}")
        try:
            with sqlite3.connect(str(obstable_file)) as conn:
                query = "SELECT valid_dttm, SW_OUT, SW_IN FROM SYNOP WHERE SW_OUT IS NOT NULL AND SW_IN IS NOT NULL AND SW_IN > 0"
                df = pd.read_sql_query(query, conn)
                
                if df.empty:
                    continue
                
                # Convert Unix seconds to datetime
                df['valid_dttm'] = pd.to_datetime(df['valid_dttm'], unit='s', utc=True)
                data_list.append(df)
        except Exception as e:
            print(f"  ⚠️  Warning: Error reading {obstable_file}: {e}")
    
    if not data_list:
        print("❌ No SW_OUT/SW_IN data found in OBSTABLES")
        return pd.DataFrame()
    
    df_all = pd.concat(data_list, ignore_index=True)
    
    # Filter by validation period if specified
    if val_start and val_end:
        val_start_dt = pd.to_datetime(val_start, utc=True)
        val_end_dt = pd.to_datetime(val_end, utc=True)
        df_all = df_all[(df_all['valid_dttm'] >= val_start_dt) & 
                        (df_all['valid_dttm'] <= val_end_dt)]
    
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
    """Compute monthly average albedos from daily data."""
    daily_albedos = daily_albedos.copy()
    daily_albedos['date'] = pd.to_datetime(daily_albedos['date'])
    daily_albedos['month'] = daily_albedos['date'].dt.month
    
    monthly_avg = daily_albedos.groupby('month')['albedo'].mean().to_dict()
    
    # Create array for all 12 months (fill missing with annual mean)
    annual_mean = daily_albedos['albedo'].mean()
    monthly_values = [monthly_avg.get(m, annual_mean) for m in range(1, 13)]
    
    # Print summary
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


def generate_complete_albedo_namelist(vegtype, niralbedo_monthly, visalbedo_monthly):
    """Generate complete namelist text with all four albedo parameters."""
    output = []
    output.append("\n! Estimated albedos from validation data (SW_OUT/SW_IN 11:00-13:00 UTC)")
    output.append("! Monthly averages for vegetation and soil surfaces\n")
    
    # Vegetation NIR albedo
    output.append("! Vegetation NIR albedo (monthly)")
    output.append(generate_namelist_block(vegtype, niralbedo_monthly, 'XUNIF_ALBNIR_VEG'))
    output.append("")
    
    # Vegetation VIS albedo
    output.append("! Vegetation VIS albedo (monthly)")
    output.append(generate_namelist_block(vegtype, visalbedo_monthly, 'XUNIF_ALBVIS_VEG'))
    output.append("")
    
    # Soil NIR albedo (same as vegetation initially, can be adjusted separately)
    output.append("! Soil NIR albedo (monthly) - estimated same as vegetation")
    output.append(generate_namelist_block(vegtype, niralbedo_monthly, 'XUNIF_ALBNIR_SOIL'))
    output.append("")
    
    # Soil VIS albedo (same as vegetation initially, can be adjusted separately)
    output.append("! Soil VIS albedo (monthly) - estimated same as vegetation")
    output.append(generate_namelist_block(vegtype, visalbedo_monthly, 'XUNIF_ALBVIS_SOIL'))
    output.append("")
    
    return '\n'.join(output)


def main():
    parser = argparse.ArgumentParser(
        description='Estimate surface albedo from validation data'
    )
    parser.add_argument('station_name', help='Station name')
    parser.add_argument('osvas_root', help='OSVAS root directory')
    parser.add_argument('--validation-period', nargs=2, 
                       metavar=('START_DATE', 'END_DATE'),
                       help='Validation period (YYYY-MM-DD format). If not provided, uses all available data.')
    parser.add_argument('--output', help='Output file path (default: namelists/{station_name}/albedo_estimates.nam)')
    
    args = parser.parse_args()
    
    station_name = args.station_name
    osvas_root = Path(args.osvas_root).expanduser().resolve()
    
    print(f"\n{'='*70}")
    print(f"Estimating surface albedos for {station_name}")
    print(f"{'='*70}\n")
    
    # Get validation period
    val_start, val_end = None, None
    if args.validation_period:
        val_start, val_end = args.validation_period
        print(f"Validation period: {val_start} to {val_end}")
    else:
        print("Using all available validation data")
    print()
    
    # Step 1: Find and read OBSTABLE files
    print("Step 1: Reading validation data from OBSTABLEs")
    obstable_files = get_obstable_files(station_name, osvas_root, val_start, val_end)
    
    if not obstable_files:
        print(f"❌ No OBSTABLE files found for {station_name}")
        sys.exit(1)
    
    print(f"  Found {len(obstable_files)} OBSTABLE files")
    df_all = read_validation_data(obstable_files, val_start, val_end)
    
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
    
    # For now, assume NIR and VIS albedos are the same (can be refined later)
    # In reality, vegetation typically has different NIR vs VIS albedos
    nir_albedos = monthly_albedos
    vis_albedos = monthly_albedos
    
    # Step 5: Generate namelist format
    print("\nStep 5: Generating namelist format")
    
    # Read vegtype from station config
    config_file = osvas_root / 'config_files' / 'Stations' / station_name / f'{station_name}.yml'
    if not config_file.exists():
        print(f"⚠️  Warning: Station config not found: {config_file}")
        vegtype = 10  # default
    else:
        import yaml
        with open(config_file) as f:
            config = yaml.safe_load(f)
        vegtype = config.get('Station_metadata', {}).get('vegtype', 10)
    
    print(f"  Using vegtype: {vegtype}")
    
    namelist_text = generate_complete_albedo_namelist(vegtype, nir_albedos, vis_albedos)
    
    # Step 6: Save output
    print("\nStep 6: Saving results")
    
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = osvas_root / 'namelists' / station_name / 'albedo_estimates.nam'
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(namelist_text)
    
    print(f"  ✅ Albedo estimates saved to: {output_path}")
    print(f"\n  NIR albedo:  min={min(nir_albedos):.8f}, max={max(nir_albedos):.8f}, mean={np.mean(nir_albedos):.8f}")
    print(f"  VIS albedo:  min={min(vis_albedos):.8f}, max={max(vis_albedos):.8f}, mean={np.mean(vis_albedos):.8f}")
    print(f"\n{'='*70}")
    print("✅ Albedo estimation completed successfully")
    print(f"{'='*70}\n")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
