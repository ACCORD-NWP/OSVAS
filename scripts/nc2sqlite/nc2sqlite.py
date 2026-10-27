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
    parser.add_argument("-sl", "--station_list", required=True,
                        help="Path to a valid station list CSV (columns SID, lat, lon, elev). "
                             "Always required: it is the source of station coordinates in "
                             "both gridded and single-station modes.")
    parser.add_argument("-st", "--station", required=False, type=int, default=None,
                        help="Optional. Station ID (must exist in the -sl station list), used "
                             "only for input files that are NOT gridded fields with "
                             "lat/lon coordinates (e.g. point-extracted NetCDF), to say "
                             "which station the data belongs to. For gridded fields, "
                             "omit it: the script interpolates to every station in the "
                             "-sl list that falls inside the grid. If given together "
                             "with a gridded file, it is ignored.")
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


def _is_precip_like_name(*names):
    """True if any of the given variable/output names look like a
    precipitation-related field: matches 'pcp', 'precip', 'rain', or
    'snow' anywhere in the name, case-insensitive (e.g. 'Rainf', 'Snowf',
    'TotalPcp', 'precipitation_amount_acc')."""
    keywords = ("pcp", "precip", "rain", "snow")
    for name in names:
        if name and any(k in name.lower() for k in keywords):
            return True
    return False


def _is_precip_flux_units(units_str):
    """True if a units string represents a precipitation-style mass flux
    (kg/m2/s, i.e. a RATE), as opposed to an already-accumulated depth
    (kg/m2). Tolerates common NetCDF notational variants: spaces, dots,
    carets/asterisks for exponents, and slash- vs exponent-style forms
    ('kg/m2/s', 'kg m-2 s-1', 'kg.m-2.s-1', 'kg/m^2/s', 'kg m^-2 s^-1', ...).
    """
    if not units_str:
        return False
    s = units_str.lower().strip()
    s = s.replace(" ", "").replace(".", "").replace("^", "").replace("*", "")
    normalized_flux_forms = {
        "kg/m2/s", "kg/m^2/s", "kgm-2s-1", "kg/(m2s)", "kg/(m2*s)",
        "kgm-2*s-1", "kgm2-1s-1",
    }
    return s in normalized_flux_forms


def maybe_convert_precip_flux(values, units, dt_seconds_file, *name_candidates):
    """If a variable's name suggests precipitation (name contains 'pcp',
    'precip', 'rain', or 'snow', case-insensitive) AND its units indicate a mass
    FLUX (kg/m2/s or an equivalent notation), convert it to an accumulated
    DEPTH (kg/m2, numerically identical to mm of liquid water) by
    multiplying by the timestep interval: kg/m2/s * s = kg/m2.

    dt_seconds_file is the interval derived from the file's own consecutive
    timesteps (see compute_dt_seconds); if the file only has a single
    timestep (dt can't be derived), falls back to the common default of
    3600s (1 hour), with a printed warning so the assumption is visible
    rather than silent.

    Variables that don't match both the name and units criteria are
    returned unchanged.
    """
    if not _is_precip_like_name(*name_candidates):
        return values, units
    if not _is_precip_flux_units(units):
        return values, units

    label = "/".join(n for n in name_candidates if n)
    dt = dt_seconds_file
    if dt is None:
        dt = 3600.0
        print(f"⚠️ {label}: flux units ('{units}') detected but this file has only a "
              f"single timestep, so the accumulation interval can't be derived from "
              f"consecutive times. Assuming the common default of 3600s (1 hour) — "
              f"verify this matches the file's real accumulation period.")

    print(f"Converting {label} from flux ('{units}') to accumulated depth (kg/m2) "
          f"using dt={dt:.0f}s")
    return values * dt, "kg/m2"


def compute_dt_seconds(times):
    """Derive the (assumed uniform) interval between consecutive timesteps,
    in seconds, directly from the file's own time coordinate — the same
    file-derived approach used for the standalone plotting scripts, rather
    than hardcoding a value. Returns None if the file only has a single
    timestep (nothing to derive an interval from)."""
    if len(times) < 2:
        return None
    diffs = [(times[i + 1] - times[i]).total_seconds() for i in range(len(times) - 1)]
    if not all(abs(d - diffs[0]) < 1e-6 for d in diffs):
        print(f"⚠️ Non-uniform timestep spacing detected ({diffs[:5]}... seconds) — "
              f"using the first interval ({diffs[0]:.0f}s) for any flux→accumulation "
              f"conversion; verify this file's time axis if precip variables look off.")
    return diffs[0]


def _detect_latlon_vars(ds):
    """Find the lat/lon coordinate variables in a dataset, tolerating the
    naming/shape conventions seen across different model outputs:
      - 2D grid style: 'latitude'/'longitude' with shape (y, x)   [an_*.nc]
      - flattened SURFEX FORCING style: 'LAT'/'LON' with shape (Number_of_points,)
    Returns (lat_name, lon_name) or (None, None) if neither pattern matches.
    Works for either 1D (flattened point cloud) or 2D (meshgrid) coordinates —
    interpolation doesn't care which, since points get raveled either way."""
    for lat_name, lon_name in (
        ("latitude", "longitude"),
        ("LAT", "LON"),
        ("lat", "lon"),
        ("Latitude", "Longitude"),
    ):
        if lat_name in ds.variables and lon_name in ds.variables:
            return lat_name, lon_name
    return None, None


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
            values = np.array(var[slicing], dtype=np.float32)
        else:
            slicing = [slice(None) if i == time_dim_index else 0 for i in range(len(var_dims))]
            values = np.array(var[tuple(slicing)], dtype=np.float32)
    elif "time" in ds.variables and ds.variables["time"].size == 1:
        # SURFEX 2D field with a singleton time axis: value is valid for the
        # one time slot held in the global time variable, but the field itself
        # is stored without a time dimension.
        values = np.array(var[:], dtype=np.float32)
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
    result = np.asarray(result, dtype=np.float32)
    return result, units


def write_station_rows(station_rows, output_name, units, experiment_name, output_base, common_fctable):
    """Write multiple station/value series into the required monthly FCTABLEs.

    Each item in `station_rows` is a tuple:
        (SID, z, lat, lon, values, times)
    The values/times arrays are for a single station across the available time
    steps. All rows for a given month/file are inserted into a single SQLite
    connection to avoid reopening the same output file for every station.

    The forecast cycle (fcst_dttm) is anchored ONCE per call, at midnight of
    the *earliest* timestep across all rows — not re-derived per individual
    row. One call here always corresponds to one NetCDF file's worth of data
    for one variable, i.e. one forecast cycle, so every timestep in it (even
    ones that fall on a later calendar day, e.g. hour 24+ of a 48-hour SURFEX
    FORCING file) is a lead time of that SAME cycle rather than being treated
    as the start of a new one. Truncating each row's own valid time to
    midnight (the old behaviour) silently split a single forecast run into a
    separate fcst_dttm per calendar day it crossed."""
    if not station_rows:
        return

    all_times = [t for *_, times in station_rows for t in times]
    if not all_times:
        return
    anchor_dt = min(all_times)
    if anchor_dt.tzinfo is None:
        anchor_dt = anchor_dt.replace(tzinfo=timezone.utc)
    fcst_dt = datetime(anchor_dt.year, anchor_dt.month, anchor_dt.day, tzinfo=timezone.utc)
    fcst_time = int(fcst_dt.timestamp())

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

        # Derived once per file, from the file's own time coordinate — used
        # to convert any precipitation-named flux variable (kg/m2/s) into an
        # accumulated depth (kg/m2) before writing. None if this file only
        # has a single timestep (e.g. a per-hour an_*.nc grid file).
        dt_seconds_file = compute_dt_seconds(times)

        # Cache of already-processed variables for this file, keyed by their
        # generic output name, so that derived variables defined further down
        # in param_dict.json can reuse them as inputs.
        values_cache = {}
        units_cache = {}

        # Only variables actually referenced as an "input" by some derived
        # spec anywhere in param_dict.json need to stay in values_cache for
        # the rest of the file — everything else is a plain passthrough that
        # gets interpolated/written once and is never looked up again. With
        # no pruning, values_cache retains EVERY processed variable's full
        # array simultaneously (for a 25-timestep, 6.25M-point SURFEX FORCING
        # file, ~0.6 GB each even at float32 — several GB total with a
        # typical multi-variable param_dict), which is the dominant driver of
        # memory usage for these files. Skipping the cache entirely for
        # variables nothing downstream needs avoids that buildup.
        needed_as_input = set()
        for spec in param_dict.values():
            if isinstance(spec, dict) and spec.get("type") == "derived":
                needed_as_input.update(spec.get("inputs", []))

        # Detect whether this dataset contains lat/lon coordinates suitable for
        # grid interpolation — either a 2D (y, x) meshgrid or a flattened 1D
        # point cloud (e.g. SURFEX FORCING's Number_of_points layout). Either
        # shape works identically for Delaunay/KD-tree interpolation once
        # raveled to a flat list of (lat, lon) points.
        latlon_var_names = _detect_latlon_vars(ds)
        grid_mode_global = latlon_var_names[0] is not None

        # Build (or reuse) the interpolation geometry once per file, not once
        # per station/timestep/variable. get_grid_geometry() checks the grid
        # fingerprint and only rebuilds if the domain actually changed.
        geom_points = geom_tri = geom_kdtree = geom_bbox = None
        if grid_mode_global and station_info is not None and args is not None:
            lat_name, lon_name = latlon_var_names
            lat_grid = np.array(ds.variables[lat_name][:])
            lon_grid = np.array(ds.variables[lon_name][:])
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
                    var_name = None
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

                # Precipitation-named flux variables (kg/m2/s) get converted
                # to an accumulated depth (kg/m2) here, before anything else
                # sees them — so values_cache, interpolation, and the FCTABLE
                # write all consistently use the converted depth.
                values, units = maybe_convert_precip_flux(
                    values, units, dt_seconds_file, var_name, output_name
                )

                if output_name in needed_as_input:
                    values_cache[output_name] = values
                    units_cache[output_name] = units

                # Accumulation-type variables (precipitation, etc.) have no
                # meaningful value at the very first timestep of a forecast
                # cycle — there's no prior timestep for it to accumulate
                # since, so a 0 there is an artifact of the initial state,
                # not a real observation. Drop that leading timestep (and its
                # matching time) before writing, for any variable whose
                # output name contains "Pcp". This only affects what gets
                # written to the FCTABLE — values_cache above still holds the
                # full untrimmed series, so any derived variable further down
                # in param_dict.json that uses this one as an input still
                # gets the complete, correctly time-aligned array.
                write_values, write_times = values, times
                if "Pcp" in output_name and isinstance(values, np.ndarray) and values.ndim >= 1 and values.shape[0] > 1:
                    write_values = values[1:]
                    write_times = times[1:]

                # If values are gridded — either (time, y, x) from a 2D mesh,
                # or (time, Number_of_points) from a flattened point cloud
                # like SURFEX FORCING files — and lat/lon coordinates exist,
                # interpolate to all stations in the station list that fall
                # inside the grid bounds. Otherwise fall back to original
                # single-station behaviour.
                if isinstance(write_values, np.ndarray) and write_values.ndim >= 2 and grid_mode_global and station_info is not None and args is not None:
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
                            series = np.full((write_values.shape[0], n_stations), np.nan)

                            for t_idx in range(write_values.shape[0]):
                                gridvals = write_values[t_idx].ravel()
                                if not np.any(~np.isnan(gridvals)):
                                    continue

                                if method == 'linear':
                                    interp_vals = LinearNDInterpolator(geom_tri, gridvals)(query_latlon)
                                else:
                                    _, nn_idx = geom_kdtree.query(query_latlon)
                                    interp_vals = gridvals[nn_idx]

                                series[t_idx, :] = interp_vals

                            station_rows = [
                                (sid, sz, slat, slon, series[:, i], write_times)
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
                        write_values, write_times, output_name, units,
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

    def _walk_paths(base):
        """Yield every file and folder under `base`. Unlike Path.rglob, this
        follows symlinked folders (rglob silently skips them, so a run tree
        whose date folders are symlinks looked empty) and reports folders it
        can't read instead of silently skipping them. Guards against symlink
        cycles."""
        seen_dirs = set()

        def _onerror(err):
            print(f"\u26a0\ufe0f Can't read directory {err.filename}: {err.strerror}")

        for root, dirs, files in os.walk(str(base), followlinks=True, onerror=_onerror):
            real_root = os.path.realpath(root)
            if real_root in seen_dirs:
                dirs[:] = []  # already visited (symlink cycle / alias): don't descend again
                continue
            seen_dirs.add(real_root)
            for d in dirs:
                yield Path(root) / d
            for f in files:
                yield Path(root) / f

    def _add_nc_path(p):
        p = Path(p)
        if p.is_dir():
            for q in _walk_paths(p):
                if q.is_file() and q.name.lower().endswith('.nc'):
                    nc_files.append(q)
        elif p.is_file() and str(p).lower().endswith('.nc'):
            nc_files.append(p)

    # Resolve nc input argument(s): each entry can be a directory (searched
    # recursively for *.nc), a glob pattern, or an explicit file path.
    # args.ncdir has nargs='+' so a shell-expanded wildcard that matches
    # several files is accepted directly.
    for nc_input in args.ncdir:
        n_before = len(nc_files)
        has_wildcard = any(ch in nc_input for ch in ["*", "?", "["])

        if has_wildcard:
            # First try: expand the glob as given (works when the shell didn't
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
                        for p in _walk_paths(base):
                            if fnmatch.fnmatch(p.name, pattern):
                                _add_nc_path(p)
        else:
            p = Path(nc_input)
            if p.is_dir():
                _add_nc_path(p)
            elif p.is_file():
                nc_files.append(p)
            else:
                # Maybe an unexpanded wildcard-like token; try globbing from cwd
                for m in glob(nc_input, recursive=True):
                    _add_nc_path(m)

        if len(nc_files) == n_before:
            if not has_wildcard and not os.path.exists(nc_input):
                print(f"\u26a0\ufe0f Input path does not exist (or isn't visible from this "
                      f"process/node): {nc_input}")
            else:
                print(f"\u26a0\ufe0f No .nc files found for input: {nc_input} "
                      f"(check the path/pattern, and any 'Can't read directory' warnings above)")

    # Sort, then drop paths that resolve to a file already in the list — e.g.
    # raw_air_temperature_2m.nc -> raw.nc symlinks would otherwise make the
    # same data get processed (and written to the FCTABLEs) several times.
    nc_files = sorted(dict.fromkeys(nc_files))
    unique_files, seen_real = [], set()
    for f in nc_files:
        real = os.path.realpath(f)
        if real in seen_real:
            continue
        seen_real.add(real)
        unique_files.append(f)
    n_dups = len(nc_files) - len(unique_files)
    nc_files = unique_files
    if n_dups:
        print(f"Skipped {n_dups} path(s) that are symlinks/duplicates of a file already "
              f"in the list (e.g. raw_*.nc -> raw.nc)")

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
