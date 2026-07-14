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
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS FC (
            fcst_dttm INT,
            lead_time INT,
            z DOUBLE,
            SID DOUBLE,
            lat DOUBLE,
            lon DOUBLE,
            valid_dttm INT,
            parameter TEXT,
            units TEXT,
            "{experiment_name}_det" DOUBLE
        )
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Derived-variable support
# ---------------------------------------------------------------------------
#
# Whitelist of functions/operators made available inside postprocess
# expressions. Kept deliberately small and explicit (no __builtins__) so that
# expressions in param_dict.json cannot execute arbitrary code.
SAFE_FUNCTIONS = {
    "sqrt": np.sqrt,
    "abs": np.abs,
    "log": np.log,
    "log10": np.log10,
    "exp": np.exp,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "power": np.power,
    "minimum": np.minimum,
    "maximum": np.maximum,
    "where": np.where,
    "pi": np.pi,
}


def extract_variable_series(ds, var_name):
    """Read the full time series of a raw NetCDF variable (collapsing all
    non-time dimensions to index 0, as the original script did), returning it
    as a float array with fill values replaced by NaN, plus its units."""
    var = ds.variables[var_name]
    var_dims = var.dimensions

    if "time" not in var_dims:
        raise ValueError(f"variable '{var_name}' has no 'time' dimension")

    time_dim_index = var_dims.index("time")
    slicing = [slice(None) if i == time_dim_index else 0 for i in range(len(var_dims))]
    values = np.array(var[tuple(slicing)], dtype=float)
    values[values >= 1e20] = np.nan  # normalise _FillValue to NaN

    units = getattr(var, "units", "-")
    return values, units


def resolve_component(name, ds, values_cache, units_cache):
    """Resolve one of the 'inputs' of a derived variable. It can be either:
      - the generic output name of a variable already processed earlier in
        param_dict.json (looked up in values_cache), or
      - the name of a variable as it appears in the NetCDF file.
    """
    if name in values_cache:
        return values_cache[name], units_cache.get(name, "-")
    if name in ds.variables:
        return extract_variable_series(ds, name)
    raise KeyError(
        f"input '{name}' is neither a variable already processed in this "
        f"file nor a variable present in the NetCDF file"
    )


def evaluate_derived(spec, ds, values_cache, units_cache):
    """Compute a derived variable defined as:
        {
          "type": "derived",
          "inputs": [...],          # names of component variables (raw NetCDF
                                     # names, or generic names of variables
                                     # processed earlier in param_dict.json)
          "constants": {...},       # optional numeric constants usable in
                                     # the expression
          "expression": "...",      # algebraic expression combining inputs,
                                     # constants and SAFE_FUNCTIONS
          "units": "..."            # units to store for the result (free text)
        }
    """
    inputs = spec["inputs"]
    expression = spec["expression"]
    constants = spec.get("constants", {})
    units = spec.get("units", "-")

    namespace = dict(SAFE_FUNCTIONS)
    namespace.update(constants)

    for name in inputs:
        values, _ = resolve_component(name, ds, values_cache, units_cache)
        namespace[name] = values

    result = eval(expression, {"__builtins__": {}}, namespace)
    result = np.asarray(result, dtype=float)
    return result, units


def write_variable_to_sqlite(values, times, output_name, units, SID, z, lat, lon,
                              experiment_name, output_base, common_fctable):
    """Write a (values, times) time series to monthly FCTABLE sqlite files,
    following the same directory/naming/splitting logic as the original
    script."""
    conn = None
    cursor = None
    current_month = None
    out_path = None

    for i, val in enumerate(values):
        if val is None or (isinstance(val, float) and np.isnan(val)):
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
            if common_fctable:
                osvas_root = Path(output_base).parent.parent.parent
                out_dir = osvas_root / "sqlites" / "FCTABLES" / "common_fctables" / experiment_name / f"{year:04d}" / f"{month:02d}"
            else:
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

        # Cache of already-processed variables for this file, keyed by their
        # generic output name, so that derived variables defined further down
        # in param_dict.json can reuse them as inputs.
        values_cache = {}
        units_cache = {}

        for key, spec in param_dict.items():
            if key.startswith("_comment"):
                continue

            try:
                if isinstance(spec, dict) and spec.get("type") == "derived":
                    # Derived / postprocessed variable: the JSON key IS the
                    # generic output name.
                    output_name = key
                    print(f"processing derived variable {output_name} = {spec.get('expression')}")
                    values, units = evaluate_derived(spec, ds, values_cache, units_cache)
                else:
                    # Original behaviour: direct passthrough mapping
                    # {netcdf_name: output_name}
                    var_name = key
                    output_name = spec
                    if var_name not in ds.variables:
                        continue
                    print(f"processing {var_name} as {output_name}")
                    values, units = extract_variable_series(ds, var_name)

                values_cache[output_name] = values
                units_cache[output_name] = units

                write_variable_to_sqlite(
                    values, times, output_name, units,
                    SID, z, lat, lon, experiment_name, output_base, common_fctable
                )

            except Exception as e:
                print(f"⚠️ Skipping variable {key} in {ncfile}: {e}")
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
        param_dict = json.load(f)  # {netcdf_name: output_name} or {output_name: {derived spec}}

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
