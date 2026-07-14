#!/usr/bin/env python3
"""
Estimate monthly LAI from Copernicus Global Land Service (CGLS) via openEO
and write a SURFEX-compatible XUNIF_LAI namelist block.

This script uses the BIOPAR process from the openEO Algorithm Plaza (VITO/CDSE)
to retrieve LAI time series, which is the correct approach for the CDSE backend
(CGLS LAI is not available as a standard load_collection on that backend).

Usage:
    python3 estimate_lai.py <station_name> <osvas_root> [OPTIONS]

Options:
    --lat LAT              Station latitude (overrides config)
    --lon LON              Station longitude (overrides config)
    --run-period START END Start and end dates of the forcing period (YYYY-MM-DD).
                           If the period spans more than 12 months, only the last
                           complete calendar year is used (e.g. Nov 2022–Jan 2024
                           → Jan–Dec 2023).
    --start-year YYYY      Alternative: first year of the climatology (default: 2015)
    --end-year YYYY        Alternative: last year of the climatology  (default: 2023)
    --output-file PATH     Output namelist file
                           (default: namelists/{station}/lai_estimates.nam)
    --backend URL          openEO backend URL
                           (default: https://openeofed.dataspace.copernicus.eu)
    --no-auth              Skip OIDC authentication (already authenticated)
    --list-collections     List all collections containing 'LAI' and exit
    --print-only           Format pre-computed values without connecting to openEO
                           (requires --monthly-lai JSON string)
    --monthly-lai JSON     Pre-computed monthly LAI as JSON, e.g.
                           '{"1":1.2,"2":1.3,...,"12":1.1}' (for --print-only)

Requirements:
    pip install openeo pyyaml numpy pandas

Authentication:
    Uses OIDC device-code flow (no browser needed). On first run, visit the URL
    printed to the terminal and enter the code. Credentials are cached on disk
    and reused automatically on subsequent runs.

Data source:
    BIOPAR process (openEO Algorithm Plaza, VITO):
      https://marketplace-portal.dataspace.copernicus.eu/catalogue/app-details/21
    Delivers CGLS-equivalent LAI at 300 m, 10-day composites, backed by
    Sentinel-3 OLCI + PROBA-V. Values are in physical units (m²/m²).
    Use the federated backend (openeofed.dataspace.copernicus.eu) so that
    partner resources (VITO) are accessible.

    Fallback (--collection mode):
    If BIOPAR is unavailable, the script can also try load_collection with a
    user-supplied collection name (--collection).
"""

import sys
import argparse
import json
import math
import yaml
import numpy as np
import pandas as pd
from datetime import date
from pathlib import Path

try:
    import openeo
except ImportError:
    print("❌ openeo package not found. Install with: pip install openeo")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Federated backend exposes VITO partner resources (BIOPAR process)
DEFAULT_BACKEND = "https://openeofed.dataspace.copernicus.eu"

# BIOPAR process namespace (VITO/ESA-APEx hosted UDP, referenced by URL).
# The old CDSE "u:<uuid>/BIOPAR" namespace has been retired by the backend
# (it now raises ProcessNamespaceInvalid); the process is now published as a
# plain openEO UDP JSON on the ESA-APEx algorithm catalogue instead.
BIOPAR_NAMESPACE = (
    "https://raw.githubusercontent.com/ESA-APEx/apex_algorithms/refs/heads/"
    "main/algorithm_catalog/vito/biopar/openeo_udp/biopar.json"
)

# Small spatial buffer around point (degrees, ~0.5 km)
POINT_BUFFER = 0.005


# ---------------------------------------------------------------------------
# Period resolution
# ---------------------------------------------------------------------------

def resolve_fetch_period(run_start: str, run_end: str):
    """
    Given a run period (YYYY-MM-DD strings), return the (start, end) date
    strings to pass to openEO and the target calendar year for aggregation.

    If the period spans more than 12 months, the last fully-covered calendar
    year is used.  E.g.:
        Nov 2022 – Jan 2024  →  fetch 2023-01-01 / 2023-12-31,  year=2023
        Mar 2023 – Nov 2023  →  fetch 2023-03-01 / 2023-11-30,  year=2023 (same year)
        Jan 2022 – Dec 2022  →  fetch 2022-01-01 / 2022-12-31,  year=2022

    Returns: (fetch_start, fetch_end, target_year, truncated)
        truncated  – True when the period was shortened to a single calendar year
    """
    start = pd.Timestamp(run_start)
    end   = pd.Timestamp(run_end)

    span_months = (end.year - start.year) * 12 + (end.month - start.month)

    if span_months <= 12:
        # Period fits in a year – use as-is, no truncation
        return run_start, run_end, None, False

    # More than 12 months: pick the last fully-covered calendar year
    last_year = end.year
    # "Fully covered" means the data reaches at least Dec 31 of that year
    if end.month < 12 or end.day < 31:
        last_year -= 1

    fetch_start = f"{last_year}-01-01"
    fetch_end   = f"{last_year}-12-31"
    return fetch_start, fetch_end, last_year, True


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config(osvas_root: Path, station_name: str) -> dict:
    config_file = (
        osvas_root / "config_files" / "Stations" / station_name / f"{station_name}.yml"
    )
    with open(config_file, "r") as f:
        return yaml.safe_load(f)


def get_station_coords(config: dict, lat_override=None, lon_override=None):
    lat = lat_override if lat_override is not None else config["Station_metadata"]["lat"]
    lon = lon_override if lon_override is not None else config["Station_metadata"]["lon"]
    return float(lat), float(lon)


# ---------------------------------------------------------------------------
# openEO connection
# ---------------------------------------------------------------------------

def connect_openeo(backend: str, skip_auth: bool = False):
    print(f"  Connecting to {backend} ...")
    conn = openeo.connect(backend)
    if not skip_auth:
        print("  Authenticating via OIDC device-code flow ...")
        conn.authenticate_oidc()
    return conn


# ---------------------------------------------------------------------------
# LAI retrieval – BIOPAR (primary path)
# ---------------------------------------------------------------------------

def _bbox_polygon(lat, lon, buf):
    """GeoJSON FeatureCollection with a small bounding box around the point."""
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [lon - buf, lat - buf],
                    [lon + buf, lat - buf],
                    [lon + buf, lat + buf],
                    [lon - buf, lat + buf],
                    [lon - buf, lat - buf],
                ]],
            },
        }],
    }


def fetch_lai_biopar(conn, lat: float, lon: float,
                     fetch_start: str, fetch_end: str) -> pd.DataFrame:
    """
    Retrieve LAI time series using the BIOPAR Algorithm Plaza process.

    BIOPAR returns physical LAI (m²/m²) directly — no scale factor needed.
    We chunk by year to keep individual job sizes manageable.
    """
    polygon = _bbox_polygon(lat, lon, POINT_BUFFER)

    start = pd.Timestamp(fetch_start)
    end   = pd.Timestamp(fetch_end)
    years = range(start.year, end.year + 1)

    all_records = []
    for year in years:
        yr_start = max(start, pd.Timestamp(f"{year}-01-01")).strftime("%Y-%m-%d")
        yr_end   = min(end,   pd.Timestamp(f"{year}-12-31")).strftime("%Y-%m-%d")
        print(f"    Processing {yr_start} → {yr_end} ...")

        bbox = {
            "west":  lon - POINT_BUFFER, "east":  lon + POINT_BUFFER,
            "south": lat - POINT_BUFFER, "north": lat + POINT_BUFFER,
        }

        cube = conn.datacube_from_process(
            "biopar",
            namespace=BIOPAR_NAMESPACE,
            spatial_extent=bbox,
            temporal_extent=[yr_start, yr_end],
            biopar_type="LAI",
        )

        ts  = cube.aggregate_spatial(geometries=polygon, reducer="mean")

        try:
            raise Exception("force going to the slow alternative (the quick one times out)")
            print("      Trying synchronous processing (small request) ...")
            result  = ts.execute()
            records = _parse_sync_result(result)
            print(f"      → {len(records)} observations (sync)")
        except Exception as exc:
            print(f"      Sync processing unavailable/timed out ({exc});"
                  f" falling back to batch job ...")
            job = ts.create_job(title=f"LAI_BIOPAR_{lat:.4f}_{lon:.4f}_{year}")
            job.start_and_wait()
            records = _parse_job_results(job)
            print(f"      → {len(records)} observations (batch)")

        all_records.extend(records)

    if not all_records:
        raise RuntimeError("No LAI data returned from BIOPAR for any year.")

    df = pd.DataFrame(all_records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["lai"])
    df = df[df["lai"] > 0]
    df = df.sort_values("date").reset_index(drop=True)
    print(f"  Total valid observations: {len(df)}")
    return df


def _parse_job_results(job) -> list:
    """Download batch job results and extract (date, lai) pairs."""
    results = job.get_results()
    assets  = results.get_assets()

    json_assets = [a for a in assets if a.name.endswith(".json")]
    csv_assets  = [a for a in assets if a.name.endswith(".csv")]
    asset = (json_assets or csv_assets or assets)[0]
    raw   = asset.load_bytes()

    return _parse_lai_bytes(raw)


def _parse_sync_result(result) -> list:
    """
    Extract (date, lai) pairs from a synchronous `.execute()` result.

    Depending on the openeo client version/backend, this can already be a
    parsed dict/list, raw bytes, or a requests.Response-like object with
    .content — normalize all of those into bytes and reuse the same
    parsing logic as the batch-job path.
    """
    if isinstance(result, (dict, list)):
        data = result
        records = []
        if isinstance(data, dict):
            for date_str, features in data.items():
                val = _extract_value_from_feature(features)
                if val is not None and not (isinstance(val, float) and math.isnan(val)):
                    records.append({"date": date_str, "lai": float(val)})
        return records

    raw = result.content if hasattr(result, "content") else result
    return _parse_lai_bytes(raw)


def _parse_lai_bytes(raw) -> list:
    """Shared JSON/CSV parsing logic for both sync and batch-job results."""
    records = []
    try:
        data = json.loads(raw)
        for date_str, features in data.items():
            val = _extract_value_from_feature(features)
            if val is not None and not (isinstance(val, float) and math.isnan(val)):
                records.append({"date": date_str, "lai": float(val)})
    except (json.JSONDecodeError, ValueError, TypeError):
        from io import StringIO
        raw_text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        df_raw = pd.read_csv(StringIO(raw_text))
        df_raw.columns = [c.strip() for c in df_raw.columns]
        date_col = next(c for c in df_raw.columns if "date" in c.lower() or "time" in c.lower())
        val_col  = next(c for c in df_raw.columns if c != date_col)
        for _, row in df_raw.iterrows():
            val = row[val_col]
            if pd.notna(val) and float(val) > 0:
                records.append({"date": str(row[date_col]), "lai": float(val)})

    return records


def _extract_value_from_feature(features):
    """Recursively pull the first numeric value out of a nested feature dict."""
    if isinstance(features, (int, float)):
        return features
    if isinstance(features, dict):
        for v in features.values():
            result = _extract_value_from_feature(v)
            if result is not None:
                return result
    if isinstance(features, list) and features:
        return _extract_value_from_feature(features[0])
    return None


# ---------------------------------------------------------------------------
# LAI retrieval – load_collection (fallback path)
# ---------------------------------------------------------------------------

def fetch_lai_collection(conn, lat: float, lon: float,
                         fetch_start: str, fetch_end: str,
                         collection: str) -> pd.DataFrame:
    """
    Fallback: load LAI from a named collection via load_collection.
    Useful if the target backend exposes CGLS LAI as a standard collection.
    """
    LAI_BAND   = "LAI"
    QFLAG_BAND = "QFLAG"

    buf = POINT_BUFFER
    spatial_extent = {
        "west":  lon - buf, "east":  lon + buf,
        "south": lat - buf, "north": lat + buf,
    }

    print(f"  Loading collection '{collection}' ({fetch_start} → {fetch_end}) ...")
    try:
        cube = conn.load_collection(
            collection,
            spatial_extent=spatial_extent,
            temporal_extent=[fetch_start, fetch_end],
            bands=[LAI_BAND, QFLAG_BAND],
        )
        qflag    = cube.band(QFLAG_BAND)
        lai_raw  = cube.band(LAI_BAND)
        good_pix = (qflag % 2) == 1
        lai_phys = lai_raw.mask(~good_pix) * 0.033333
    except Exception:
        print(f"  ⚠️  No QFLAG band — loading LAI only (no quality mask)")
        cube     = conn.load_collection(
            collection,
            spatial_extent=spatial_extent,
            temporal_extent=[fetch_start, fetch_end],
            bands=[LAI_BAND],
        )
        lai_phys = cube.band(LAI_BAND) * 0.033333

    polygon = _bbox_polygon(lat, lon, buf)
    ts  = lai_phys.aggregate_spatial(geometries=polygon, reducer="mean")
    job = ts.create_job(title=f"LAI_{collection}_{lat:.4f}_{lon:.4f}")
    job.start_and_wait()

    records = _parse_job_results(job)
    if not records:
        raise RuntimeError(f"No data returned from collection '{collection}'.")

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["lai"])
    df = df[df["lai"] > 0]
    df = df.sort_values("date").reset_index(drop=True)
    print(f"  Retrieved {len(df)} valid observations")
    return df


# ---------------------------------------------------------------------------
# Climatology
# ---------------------------------------------------------------------------

def compute_monthly_climatology(df: pd.DataFrame, target_year: int = None) -> dict:
    """
    Compute monthly mean LAI.

    If target_year is given (set when the run period was truncated to a single
    calendar year), only data from that year is used.  Otherwise all data in
    the DataFrame is used.

    Any missing months are gap-filled by nearest-neighbour interpolation.
    Returns {1: mean_jan, ..., 12: mean_dec}.
    """
    df = df.copy()

    if target_year is not None:
        df = df[df["date"].dt.year == target_year]
        if df.empty:
            raise ValueError(f"No LAI data found for target year {target_year}.")
        print(f"  Using data from calendar year {target_year}")

    df["month"] = df["date"].dt.month
    monthly     = df.groupby("month")["lai"].mean()

    full = pd.Series(index=range(1, 13), dtype=float)
    for m in range(1, 13):
        if m in monthly.index:
            full[m] = monthly[m]

    n_missing = int(full.isna().sum())
    if n_missing > 0:
        print(f"  ⚠️  {n_missing} month(s) have no data — gap-filling by interpolation")
    full = full.interpolate(method="nearest").bfill().ffill()

    return {int(m): round(float(v), 3) for m, v in full.items()}


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_namelist_block(monthly_lai: dict, vegtype: int) -> str:
    """Format monthly LAI values as a SURFEX XUNIF_LAI namelist block."""
    lines = []
    for month in range(1, 13):
        value     = monthly_lai[month]
        month_pad = " " if month < 10 else ""
        key       = f"XUNIF_LAI({vegtype},{month_pad}{month})"
        line      = f"                       {key:<22} = {value},"
        lines.append(line)
    return "\n".join(lines)


def write_output(namelist_block: str, output_file: Path,
                 lat: float, lon: float,
                 fetch_start: str, fetch_end: str, target_year: int = None):
    period_str = (
        f"calendar year {target_year} (from run period {fetch_start} – {fetch_end})"
        if target_year
        else f"{fetch_start} – {fetch_end}"
    )
    header = (
        f"! XUNIF_LAI estimates from CGLS LAI 300m (openEO/Copernicus Data Space)\n"
        f"! Location  : lat={lat:.4f}, lon={lon:.4f}\n"
        f"! Period    : {period_str}\n"
        f"! Generated by estimate_lai.py\n"
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        f.write(header + namelist_block + "\n")
    print(f"  ✓ Written to: {output_file}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Estimate monthly LAI from CGLS/BIOPAR via openEO for a SURFEX station"
    )
    parser.add_argument("station_name", help="Station name")
    parser.add_argument("osvas_root",   help="OSVAS root directory")
    parser.add_argument("--lat",  type=float, help="Station latitude  (overrides config)")
    parser.add_argument("--lon",  type=float, help="Station longitude (overrides config)")

    # Period definition – two mutually exclusive approaches
    period_group = parser.add_mutually_exclusive_group()
    period_group.add_argument(
        "--run-period", nargs=2, metavar=("START", "END"),
        help="Run period as two YYYY-MM-DD dates (from Forcing_data config). "
             "If span > 12 months, the last complete calendar year is used."
    )
    period_group.add_argument(
        "--start-year", type=int, default=None,
        help="First year of a multi-year climatology (use with --end-year)"
    )
    parser.add_argument("--end-year", type=int, default=None,
                        help="Last year of a multi-year climatology")

    parser.add_argument("--output-file",
                        help="Output file path (default: namelists/{station}/lai_estimates.nam)")
    parser.add_argument("--backend", default=DEFAULT_BACKEND,
                        help=f"openEO backend URL (default: {DEFAULT_BACKEND})")
    parser.add_argument("--collection", default=None,
                        help="Use load_collection instead of BIOPAR (supply collection name)")
    parser.add_argument("--no-auth",   action="store_true",
                        help="Skip OIDC authentication (if already authenticated)")
    parser.add_argument("--list-collections", action="store_true",
                        help="List all collections containing 'LAI' on the backend and exit")
    parser.add_argument("--print-only", action="store_true",
                        help="Format pre-computed values without connecting to openEO")
    parser.add_argument("--monthly-lai",
                        help="JSON string of pre-computed monthly LAI (for --print-only)")

    args = parser.parse_args()

    station_name = args.station_name
    osvas_root   = Path(args.osvas_root).expanduser().resolve()

    print(f"\n{'='*70}")
    print(f"LAI estimation for station: {station_name}")
    print(f"{'='*70}\n")

    config   = load_config(osvas_root, station_name)
    lat, lon = get_station_coords(config, args.lat, args.lon)
    vegtype  = config["Station_metadata"]["vegtype"]

    # ── Resolve fetch period ──────────────────────────────────────────────
    target_year = None  # only set when we truncate to a single calendar year

    if args.run_period:
        run_start, run_end = args.run_period
        fetch_start, fetch_end, target_year, truncated = resolve_fetch_period(
            run_start, run_end
        )
        if truncated:
            print(
                f"  Run period {run_start} – {run_end} spans more than 12 months.\n"
                f"  Using last complete calendar year: {target_year}"
            )
    else:
        # --start-year / --end-year (or hard defaults)
        start_yr = args.start_year if args.start_year else 2015
        end_yr   = args.end_year   if args.end_year   else 2023
        fetch_start = f"{start_yr}-01-01"
        fetch_end   = f"{end_yr}-12-31"

    print(f"  Station     : {station_name}")
    print(f"  Location    : lat={lat:.4f}, lon={lon:.4f}")
    print(f"  Vegtype     : {vegtype}")
    print(f"  Fetch period: {fetch_start} – {fetch_end}")
    if target_year:
        print(f"  Target year : {target_year}\n")
    else:
        print()

    output_file = (
        Path(args.output_file)
        if args.output_file
        else osvas_root / "namelists" / station_name / "lai_estimates.nam"
    )

    # ── print-only mode ───────────────────────────────────────────────────
    if args.print_only:
        if not args.monthly_lai:
            print("❌ --print-only requires --monthly-lai JSON string")
            sys.exit(1)
        monthly_lai = {int(k): float(v) for k, v in json.loads(args.monthly_lai).items()}
        block = format_namelist_block(monthly_lai, vegtype)
        print("\nNamelist block:\n")
        print(block)
        write_output(block, output_file, lat, lon, fetch_start, fetch_end, target_year)
        return 0

    # ── connect ───────────────────────────────────────────────────────────
    print("Step 1: Connecting to openEO")
    conn = connect_openeo(args.backend, skip_auth=args.no_auth)
    print(f"  ✓ Connected\n")

    # ── list-collections mode ─────────────────────────────────────────────
    if args.list_collections:
        available = conn.list_collection_ids()
        lai_cols  = [c for c in sorted(available) if "LAI" in c.upper()]
        print(f"Collections containing 'LAI' on {args.backend}:")
        for c in lai_cols or ["(none found)"]:
            print(f"  {c}")
        print(f"\nAll {len(available)} collections:")
        for c in sorted(available):
            print(f"  {c}")
        return 0

    # ── fetch LAI ─────────────────────────────────────────────────────────
    print("Step 2: Fetching LAI time series")

    if args.collection:
        available = conn.list_collection_ids()
        if args.collection not in available:
            lai_cols = [c for c in available if "LAI" in c.upper()]
            print(f"  ❌ Collection '{args.collection}' not found.")
            if lai_cols:
                print(f"  Available LAI collections: {lai_cols}")
            sys.exit(1)
        df = fetch_lai_collection(
            conn, lat, lon, fetch_start, fetch_end, collection=args.collection
        )
    else:
        print("  Using BIOPAR process (Algorithm Plaza / VITO)")
        df = fetch_lai_biopar(conn, lat, lon, fetch_start, fetch_end)

    # ── climatology ───────────────────────────────────────────────────────
    print("\nStep 3: Computing monthly climatology")
    monthly_lai = compute_monthly_climatology(df, target_year=target_year)
    for m, v in monthly_lai.items():
        print(f"  Month {m:2d}: {v:.3f}")

    # ── write output ──────────────────────────────────────────────────────
    print("\nStep 4: Writing namelist block")
    block = format_namelist_block(monthly_lai, vegtype)
    print("\n" + block + "\n")
    write_output(block, output_file, lat, lon, fetch_start, fetch_end, target_year)

    print(f"\n{'='*70}")
    print(f"✅ LAI estimation complete")
    print(f"{'='*70}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
