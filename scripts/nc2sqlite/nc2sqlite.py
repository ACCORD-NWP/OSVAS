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
import hashlib
from scipy.spatial import Delaunay, cKDTree
from scipy.interpolate import LinearNDInterpolator

def parse_args():
    parser = argparse.ArgumentParser(description="Convert point NetCDF SURFEX output to SQLite.")
    parser.add_argument("-p", "--param_dict", required=True, help="Path to param_dict.json")
    parser.add_argument("-sl", "--station_list", required=True, help="Path to station_list_default.csv")
    parser.add_argument("-st", "--station", required=False, type=int, default=None,
                        help="Station ID for single-station (point NetCDF) mode. "
                             "Omit this when feeding 2D gridded fields with -sl: all "
                             "stations in the station list falling inside the grid "
                             "will be interpolated to.")
    parser.add_argument("-o", "--output", required=True, help="Output base directory")
    parser.add_argument("-m", "--experiment_name", required=True, help="Experiment name")
    parser.add_argument("--common_fctable", action="store_true", default=False, help="Use common fctable directory (sqlites/model_data/common_fctables/) instead of station-specific")
    parser.add_argument("ncdir", nargs='+',
                        help="Directory containing NetCDF files, one or more explicit "
                             "file paths, and/or glob patterns. Accepts multiple values "
                             "so a shell-expanded wildcard (e.g. 'raw_*') that matches "
                             "several files works directly.")
    parser.add_argument("--int", dest="interp", choices=["bilinear", "np"], default="bilinear",
                        help="Interpolation method for 2D fields: 'bilinear' (default) or 'np' (nearest point)")
    return parser.parse_args()

def load_station_info(station_list_path):
    station_info = {}
    with open(station_list_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
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
        print(f"Number of stations to interpolate: {len(station_info)}")
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


# ---------------------------------------------------------------------------
# Grid-geometry cache for point interpolation
# ---------------------------------------------------------------------------
#
# Building a Delaunay triangulation / KD-tree over a 2500x2500 lat/lon grid is
# expensive (this is what made 8-station interpolation take ~590s: it was
# being rebuilt from scratch once per station, per timestep). Since the grid
# geometry is normally identical across every file in a run, we build it once
# and reuse it — but only after confirming the lat/lon arrays actually match
# what we cached, so a domain/resolution change can never silently reuse a
# stale triangulation.
_GRID_CACHE = {
    "fingerprint": None,
    "tri": None,      # scipy.spatial.Delaunay over (lat, lon) grid points
    "kdtree": None,    # scipy.spatial.cKDTree over the same points
    "bbox": None,      # (min_lat, max_lat, min_lon, max_lon)
}


def _grid_fingerprint(lat_grid, lon_grid):
    """Cheap-but-safe fingerprint of a grid's geometry: shape + a hash of the
    actual coordinate values. Two grids with the same shape but different
    coordinates (different domain, resampled resolution, shifted origin,
    etc.) will always produce a different fingerprint."""
    h = hashlib.sha1()
    h.update(str(lat_grid.shape).encode())
    h.update(np.ascontiguousarray(lat_grid, dtype=np.float64).tobytes())
    h.update(np.ascontiguousarray(lon_grid, dtype=np.float64).tobytes())
    return h.hexdigest()


def get_grid_geometry(lat_grid, lon_grid, ncfile=None):
    """Return (points, tri, kdtree, bbox) for this lat/lon grid, rebuilding
    and re-caching only when the grid's fingerprint differs from what's
    cached (first call, or a genuine domain/resolution change)."""
    fp = _grid_fingerprint(lat_grid, lon_grid)
    points = np.column_stack((lat_grid.ravel(), lon_grid.ravel()))

    if _GRID_CACHE["fingerprint"] != fp:
        label = f" (triggered by {ncfile})" if ncfile is not None else ""
        if _GRID_CACHE["fingerprint"] is None:
            print(f"Building grid triangulation/KD-tree for interpolation{label}")
        else:
            print(f"⚠️ Grid geometry changed{label} — rebuilding triangulation/KD-tree "
                  f"(this should only happen if the domain/resolution actually changed)")

        _GRID_CACHE["fingerprint"] = fp
        _GRID_CACHE["tri"] = Delaunay(points)
        _GRID_CACHE["kdtree"] = cKDTree(points)
        _GRID_CACHE["bbox"] = (
            float(np.nanmin(lat_grid)), float(np.nanmax(lat_grid)),
            float(np.nanmin(lon_grid)), float(np.nanmax(lon_grid)),
        )

    return points, _GRID_CACHE["tri"], _GRID_CACHE["kdtree"], _GRID_CACHE["bbox"]


def extract_variable_series(ds, var_name, preserve_grid=False):
    """Read the full time series of a raw NetCDF variable.

    If `preserve_grid` is False (original behaviour), collapse all non-time
    dimensions to index 0 and return a 1D time array. If `preserve_grid` is
    True and the variable has spatial dimensions (e.g. time,y,x), return the
    full array with shape (time, ...).

    Some SURFEX-style 2D fields are stored as a grid with a singleton global
    `time` variable, while the variable itself is only `(y, x)` (or similar) and
    does not repeat the `time` dimension. In that case we treat it as a single
    time slot and keep the spatial grid with a leading singleton time axis.
    Returns (values, units).
    """
    var = ds.variables[var_name]
    var_dims = var.dimensions

    if "time" in var_dims:
        time_dim_index = var_dims.index("time")
        if preserve_grid and len(var_dims) > 1:
            slicing = tuple(slice(None) for _ in range(len(var_dims)))
            values = np.array(var[slicing], dtype=float)
        else:
            slicing = [slice(None) if i == time_dim_index else 0 for i in range(len(var_dims))]
            values = np.array(var[tuple(slicing)], dtype=float)
    elif "time" in ds.variables and ds.variables["time"].size == 1:
        # SURFEX 2D field with a singleton time axis: value is valid for the
        # one time slot held in the global time variable, but the field itself
        # is stored without a time dimension.
        values = np.array(var[:], dtype=float)
        if preserve_grid:
            values = values[np.newaxis, ...]
        else:
            values = values.reshape(-1)
    else:
        raise ValueError(f"variable '{var_name}' has no usable 'time' dimension")

    values[values >= 1e20] = np.nan  # normalise _FillValue to NaN

    units = getattr(var, "units", "-")
    return values, units


def resolve_component(name, ds, values_cache, units_cache, preserve_grid=False):
    """Resolve one of the 'inputs' of a derived variable. It can be either:
      - the generic output name of a variable already processed earlier in
        param_dict.json (looked up in values_cache), or
      - the name of a variable as it appears in the NetCDF file.
    """
    if name in values_cache:
        return values_cache[name], units_cache.get(name, "-")
    if name in ds.variables:
        return extract_variable_series(ds, name, preserve_grid=preserve_grid)
    raise KeyError(
        f"input '{name}' is neither a variable already processed in this "
        f"file nor a variable present in the NetCDF file"
    )


def evaluate_derived(spec, ds, values_cache, units_cache, preserve_grid=False):
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
        values, _ = resolve_component(name, ds, values_cache, units_cache, preserve_grid=preserve_grid)
        namespace[name] = values

    result = eval(expression, {"__builtins__": {}}, namespace)
    result = np.asarray(result, dtype=float)
    return result, units


def write_station_rows(station_rows, output_name, units, experiment_name, output_base, common_fctable):
    """Write multiple station/value series into the required monthly FCTABLEs.

    Each item in `station_rows` is a tuple:
        (SID, z, lat, lon, values, times)
    The values/times arrays are for a single station across the available time
    steps. All rows for a given month/file are inserted into a single SQLite
    connection to avoid reopening the same output file for every station.
    """
    if not station_rows:
        return

    conn = None
    cursor = None
    current_month = None
    out_path = None

    for SID, z, lat, lon, values, times in station_rows:
        for i, val in enumerate(values):
            if val is None or (isinstance(val, float) and np.isnan(val)):
                continue

            valid_dt = times[i]
            if valid_dt.tzinfo is None:
                valid_dt = valid_dt.replace(tzinfo=timezone.utc)
            valid_time = int(valid_dt.timestamp())

            fcst_dt = datetime(valid_dt.year, valid_dt.month, valid_dt.day, tzinfo=timezone.utc)
            fcst_time = int(fcst_dt.timestamp())
            lead_time = (valid_dt - fcst_dt).total_seconds() / 3600.0

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


def write_variable_to_sqlite(values, times, output_name, units, SID, z, lat, lon,
                              experiment_name, output_base, common_fctable):
    """Write a (values, times) time series to monthly FCTABLE sqlite files,
    following the same directory/naming/splitting logic as the original
    script."""
    write_station_rows([(SID, z, lat, lon, values, times)], output_name, units, experiment_name, output_base, common_fctable)


def process_netcdf_file(ncfile, param_dict, SID, z, lat, lon, experiment_name, output_base, common_fctable=False, station_info=None, args=None):
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

        # Detect whether this dataset contains 2D latitude/longitude grids
        grid_mode_global = (
            'latitude' in ds.variables and 'longitude' in ds.variables
            and getattr(ds.variables['latitude'], 'ndim', 1) == 2
            and getattr(ds.variables['longitude'], 'ndim', 1) == 2
        )

        # Build (or reuse) the interpolation geometry once per file, not once
        # per station/timestep/variable. get_grid_geometry() checks the grid
        # fingerprint and only rebuilds if the domain actually changed.
        geom_points = geom_tri = geom_kdtree = geom_bbox = None
        if grid_mode_global and station_info is not None and args is not None:
            lat_grid = np.array(ds.variables['latitude'][:])
            lon_grid = np.array(ds.variables['longitude'][:])
            geom_points, geom_tri, geom_kdtree, geom_bbox = get_grid_geometry(
                lat_grid, lon_grid, ncfile=ncfile
            )
            bbox_min_lat, bbox_max_lat, bbox_min_lon, bbox_max_lon = geom_bbox

            # Stations inside the grid's bounding box, resolved once per file.
            station_points_in_bbox = [
                (sid, sinfo['lat'], sinfo['lon'], sinfo['z'])
                for sid, sinfo in station_info.items()
                if bbox_min_lat <= sinfo['lat'] <= bbox_max_lat
                and bbox_min_lon <= sinfo['lon'] <= bbox_max_lon
            ]
            query_latlon = np.array([[slat, slon] for _, slat, slon, _ in station_points_in_bbox])
            method = 'linear' if args.interp == 'bilinear' else 'nearest'

        for key, spec in param_dict.items():
            if key.startswith("_comment"):
                continue

            try:
                # Decide whether to preserve grid for this variable
                preserve_grid = grid_mode_global

                if isinstance(spec, dict) and spec.get("type") == "derived":
                    # Derived / postprocessed variable: the JSON key IS the
                    # generic output name.
                    output_name = key
                    print(f"processing derived variable {output_name} = {spec.get('expression')}")
                    values, units = evaluate_derived(spec, ds, values_cache, units_cache, preserve_grid=preserve_grid)
                else:
                    # Original behaviour: direct passthrough mapping
                    # {netcdf_name: output_name}
                    var_name = key
                    output_name = spec
                    if var_name not in ds.variables:
                        continue
                    print(f"processing {var_name} as {output_name}")
                    values, units = extract_variable_series(ds, var_name, preserve_grid=preserve_grid)

                values_cache[output_name] = values
                units_cache[output_name] = units

                # If values are gridded (time, y, x) and lat/lon arrays exist,
                # interpolate to all stations in the station list that fall
                # inside the grid bounds. Otherwise fall back to original
                # single-station behaviour.
                if isinstance(values, np.ndarray) and values.ndim >= 3 and grid_mode_global and station_info is not None and args is not None:
                    try:
                        if not station_points_in_bbox:
                            station_rows = []
                        else:
                            # One interpolator built per timestep (reusing the
                            # cached triangulation/KD-tree — no re-triangulation),
                            # queried for ALL stations at once instead of once
                            # per station. This is the change that turns
                            # N_stations separate O(grid) triangulations into a
                            # single one per timestep.
                            n_stations = len(station_points_in_bbox)
                            series = np.full((values.shape[0], n_stations), np.nan)

                            for t_idx in range(values.shape[0]):
                                gridvals = values[t_idx].ravel()
                                if not np.any(~np.isnan(gridvals)):
                                    continue

                                if method == 'linear':
                                    interp_vals = LinearNDInterpolator(geom_tri, gridvals)(query_latlon)
                                else:
                                    _, nn_idx = geom_kdtree.query(query_latlon)
                                    interp_vals = gridvals[nn_idx]

                                series[t_idx, :] = interp_vals

                            station_rows = [
                                (sid, sz, slat, slon, series[:, i], times)
                                for i, (sid, slat, slon, sz) in enumerate(station_points_in_bbox)
                            ]

                        if station_rows:
                            write_station_rows(
                                station_rows, output_name, units,
                                experiment_name, output_base, common_fctable
                            )
                    except Exception as e:
                        print(f"⚠️ Grid interpolation failed for {output_name} in {ncfile}: {e}")
                        traceback.print_exc()
                else:
                    if SID is None:
                        raise ValueError(
                            f"variable '{output_name}' in {ncfile} is not a 2D gridded "
                            f"field (or lat/longitude grids weren't found), and no -st "
                            f"was given to fall back on a single station. Pass -st "
                            f"<station_id> if this file contains point/station data."
                        )
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

    if args.station is not None:
        # Legacy single-station mode: -st picks one station, used as the
        # fallback target when a file turns out not to be a 2D gridded field.
        station_id = int(args.station)
        if station_id not in station_info:
            print(f"Error: Station {station_id} not found in station list.")
            sys.exit(1)
        station = station_info[station_id]
        SID, z, lat, lon = station['SID'], station['z'], station['lat'], station['lon']
    else:
        # -st omitted: assume gridded 2D input, interpolate to every station
        # in the list that falls inside the grid. process_netcdf_file() will
        # raise a clear error per-file if a file turns out not to be gridded
        # and no -st was given to fall back on.
        SID = z = lat = lon = None

    # Load param_dict from JSON file
    with open(args.param_dict) as f:
        param_dict = json.load(f)  # {netcdf_name: output_name} or {output_name: {derived spec}}

    # Resolve nc input argument(s): each entry can be a directory, a glob
    # pattern, or an explicit file path. nc_input is now a list (args.ncdir
    # has nargs='+') so that a shell-expanded wildcard matching several files
    # (e.g. 'raw_*') is accepted directly instead of erroring out as
    # "unrecognized arguments".
    nc_files = []
    from glob import glob
    import fnmatch

    def _add_nc_path(p):
        p = Path(p)
        if p.is_dir():
            nc_files.extend(list(p.rglob('*.nc')))
        elif p.is_file() and str(p).lower().endswith('.nc'):
            nc_files.append(p)

    for nc_input in args.ncdir:
        if any(ch in nc_input for ch in ["*", "?", "["]):
            # First try: expand the glob as given (should work when shell didn't
            # expand it). If that yields matches, process them.
            matches = glob(nc_input, recursive=True)
            if matches:
                for m in matches:
                    _add_nc_path(m)
            else:
                # Fallback: pattern like /some/path/.../an* — find the base
                # directory before the first wildcard and search it recursively
                # for names matching the basename pattern.
                first_wild = min((nc_input.find(c) for c in ['*', '?', '['] if nc_input.find(c) != -1), default=-1)
                if first_wild != -1:
                    prefix = nc_input[:first_wild]
                    base_dir = os.path.dirname(prefix)
                    if base_dir == '':
                        base_dir = '.'
                    base = Path(base_dir)
                    pattern = os.path.basename(nc_input)
                    if base.exists():
                        for p in base.rglob('*'):
                            if fnmatch.fnmatch(p.name, pattern):
                                _add_nc_path(p)
                    else:
                        # Last resort: try a global recursive glob from cwd
                        for m in glob(nc_input, recursive=True):
                            _add_nc_path(m)
        else:
            p = Path(nc_input)
            if p.is_dir():
                nc_files.extend(list(p.rglob('*.nc')))
            elif p.is_file():
                nc_files.append(p)
            else:
                # Maybe the user passed an unexpanded wildcard-like token; try
                # globbing from cwd
                for m in glob(nc_input, recursive=True):
                    _add_nc_path(m)

    # Deduplicate and sort
    nc_files = sorted(list(dict.fromkeys(nc_files)))

    print(f"Found {len(nc_files)} NetCDF files to process")

    for ncfile in nc_files:
        start_time = datetime.now(timezone.utc)
        print(f"Processing {ncfile}")
        try:
            process_netcdf_file(ncfile, param_dict, SID, z, lat, lon, args.experiment_name, args.output, args.common_fctable, station_info=station_info, args=args)
        except Exception as e:
            print(f"⚠️ Failed to process {ncfile}: {e}")
            traceback.print_exc()
        finally:
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            print(f"Completed {ncfile} in {elapsed:.2f} seconds")

if __name__ == "__main__":
    main()
