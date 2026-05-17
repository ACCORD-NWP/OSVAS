import argparse
import os
import json
import sqlite3
import netCDF4
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv
import sys
import traceback

def parse_args():
    parser = argparse.ArgumentParser(description="Convert point NetCDF SURFEX output to SQLite.")
    parser.add_argument("-p", "--param_dict", required=True, help="Path to param_dict.json")
    parser.add_argument("-s", "--station_list", required=True, help="Path to station_list_default.csv")
    parser.add_argument("-st", "--station", required=True, type=int, help="Station ID")
    parser.add_argument("-o", "--output", required=True, help="Output base directory")
    parser.add_argument("-m", "--experiment_name", required=True, help="Experiment name")
    parser.add_argument("--common_fctable", action="store_true", default=False, help="Use common fctable directory (sqlites/model_data/common_fctables/) instead of station-specific")
    parser.add_argument("ncdir", help="Directory containing NetCDF files")
    return parser.parse_args()

def load_station_info(station_list_path):
    station_info = {}
    with open(station_list_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            print(row)
            sid = int(row['SID'])
            lat = float(row['lat'])
            lon = float(row['lon'])
            z = float(row['elev'])
            station_info[int(row['SID'])] = {
                'SID': sid,
                'lat': lat,
                'lon': lon,
                'z': z
            }
    return station_info


def create_fc_table(conn, param_name, experiment_name):
    cursor = conn.cursor()
    #cursor.execute("DROP TABLE IF EXISTS FC")
    try:
       cursor.execute(f"""
           CREATE TABLE FC (
               fcst_dttm INT,
               lead_time INT,
               z DOUBLE,
               SID DOUBLE,
               lat DOUBLE,
               lon DOUBLE,
               valid_dttm INT,
               parameter TEXT,
               units TEXT,
               {experiment_name}_det DOUBLE
           )
       """)
       conn.commit()
    except:
        print("table FC apparently exists already")



def process_netcdf_file(ncfile, param_dict, SID, z, lat, lon, experiment_name, output_base, common_fctable=False):
    with netCDF4.Dataset(ncfile) as ds:
        if "time" not in ds.variables:
            print(f"⚠️ Skipping {ncfile}: no 'time' variable found")
            return        

        time_var = ds.variables["time"]
        times = netCDF4.num2date(time_var[:], time_var.units, only_use_cftime_datetimes=False)

        # Ensure all times are treated as UTC (avoid local-time shift)
        if times[0].tzinfo is None:
           times = [t.replace(tzinfo=timezone.utc) for t in times]

        for var_name, output_name in param_dict.items():
            if var_name not in ds.variables:
                continue
            try:
                print(f'processing {var_name} as {output_name}')
                var = ds.variables[var_name]
                units = getattr(var, "units", "-")

                var_dims = var.dimensions
                print(f"{var_name} dimensions: {var.dimensions}, shape: {var.shape}")

                if "time" not in var_dims:
                    print(f"⚠️ Skipping variable {var_name} in {ncfile}: no 'time' dimension")
                    continue

                time_dim_index = var_dims.index("time")
                slicing = [slice(None) if i == time_dim_index else 0 for i in range(len(var_dims))]
                values = var[tuple(slicing)]

                conn = None
                cursor = None
                current_month = None
                out_path = None

                for i, val in enumerate(values):
                    if val >= 1e20:  # skip _FillValue
                        continue

                    valid_dt = times[i]
                    if valid_dt.tzinfo is None:
                        valid_dt = valid_dt.replace(tzinfo=timezone.utc)
                    valid_time = int(valid_dt.timestamp())
                    
                    # Forecast time = valid time truncated to the day (keep it UTC-aware)
                    fcst_dt = datetime(valid_dt.year, valid_dt.month, valid_dt.day, tzinfo=timezone.utc)
                    fcst_time = int(fcst_dt.timestamp())
                    
                    # Lead time = difference in hours from beginning of the day
                    lead_time = (valid_dt - fcst_dt).total_seconds() / 3600.0

                    # If the month changed, create a new file
                    month_key = (fcst_dt.year, fcst_dt.month)
                    if current_month != month_key:
                        if conn:
                            conn.commit()
                            conn.close()
                            print(f"Wrote FCTABLE in {out_path}")
                        current_month = month_key

                        year, month = fcst_dt.year, fcst_dt.month
                        # Determine output directory based on common_fctable flag
                        if common_fctable:
                            # Use common fctable directory structure
                            osvas_root = Path(output_base).parent.parent.parent  # Extract OSVAS root (go up: Meteopole -> FCTABLES -> sqlites -> OSVAS)
                            out_dir = osvas_root / "sqlites" / "FCTABLES" / "common_fctables" / experiment_name / f"{year:04d}" / f"{month:02d}"
                        else:
                            # Use station-specific directory structure (current behavior)
                            out_dir = Path(output_base) / experiment_name / f"{year:04d}" / f"{month:02d}"
                        out_dir.mkdir(parents=True, exist_ok=True)
                        out_path = out_dir / f"FCTABLE_{output_name}_{year:04d}{month:02d}_00.sqlite"

                        conn = sqlite3.connect(out_path)
                        create_fc_table(conn, output_name, experiment_name)
                        cursor = conn.cursor()

                    cursor.execute(f"""
                        INSERT INTO FC VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        fcst_time,
                        lead_time,
                        z,
                        SID,
                        lat,
                        lon,
                        valid_time,
                        output_name,
                        units,
                        float(val)
                    ))

                if conn:
                    conn.commit()
                    conn.close()
                    print(f"Wrote FCTABLE in {out_path}")

            except Exception as e:
                print(f"⚠️ Skipping variable {var_name} in {ncfile}: {e}")
                continue



def main():
    args = parse_args()
    station_info = load_station_info(args.station_list)
    station_id = int(args.station)

    if station_id not in station_info:
        print(f"Error: Station {station_id} not found in station list.")
        sys.exit(1)

    station = station_info[station_id]
    SID, z, lat, lon = station['SID'], station['z'], station['lat'], station['lon']

    # Load param_dict from JSON file
    with open(args.param_dict) as f:
        param_dict = json.load(f)  # Expecting a dict: {netcdf_name: output_name}

    nc_files = list(Path(args.ncdir).glob("*.nc"))
    for ncfile in nc_files:
        print(f"Processing {ncfile}")
        try:
            process_netcdf_file(ncfile, param_dict, SID, z, lat, lon, args.experiment_name, args.output, args.common_fctable)
        except Exception as e:
            print(f"⚠️ Failed to process {ncfile}: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    main()

