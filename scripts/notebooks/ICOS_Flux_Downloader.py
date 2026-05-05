#!/usr/bin/env python
# coding: utf-8

# In[ ]:


###### OSVAS ########################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)###########################
###### STEP 2: Downloading validation data from ICOS #############
#### STEP 2.0: DEFINING STATION and OSVAS PATH ########################
import os
import tempfile, shutil, subprocess
# Default values defined in the notebook for Station and OSVAS install:
OSVAS='/home/pn56/OSVASgh/'  # Main OSVAS path
Station_name='Loobos'

# If an environment variable STATION or OSVAS exists, override the default
Station_name = os.getenv("STATION_NAME", Station_name)
OSVAS = os.getenv("OSVAS", OSVAS)

print(f"Creating Validation files for: {Station_name} with OSVAS installation in {OSVAS}" )


# In[ ]:


###### OSVAS ##################################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)#####################################
#### STEP 2.1: IMPORTING NEEDED PACKAGES AND DEFINING FUNCTIONS ###############
import pandas as pd
import numpy as np
import sqlite3
import os
import yaml
from icoscp.dobj import Dobj
from icoscp_core.icos import bootstrap
from icoscp import cpauth
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import re as _re


def expand_wildcard_variables(variables, units, df_columns):
    """
    Expand wildcard entries in the variables (and units) dicts.

    A wildcard entry has a '*' in the ICOS source name, e.g.:
        SWC_*: SWC_*
        TS_*:  TS_*

    For each such entry, every column in df_columns whose name matches the
    prefix before '*' is added as an explicit mapping.  The destination name
    (left-hand side) is built by replacing '*' with the same suffix found in
    the source column name.

    Non-wildcard entries are passed through unchanged.

    Parameters
    ----------
    variables : dict   {dest_name: source_name}  from the YAML
    units     : dict   {dest_name: unit_string}   from the YAML
    df_columns: list   actual column names present in the downloaded dataset

    Returns
    -------
    expanded_variables : dict
    expanded_units     : dict
    """
    import fnmatch

    expanded_variables = {}
    expanded_units = {}

    for dest, src in variables.items():
        if src is None:
            continue

        dest_str = str(dest)
        src_str  = str(src)

        if '*' not in src_str:
            # plain entry – keep as-is
            expanded_variables[dest_str] = src_str
            if dest_str in units:
                expanded_units[dest_str] = units[dest_str]
            continue

        # wildcard entry: find the prefix before '*'
        prefix = src_str.split('*')[0]   # e.g. 'SWC_'
        dest_prefix = dest_str.split('*')[0]  # e.g. 'SWC_'

        # collect matching columns, sorted for deterministic order
        matched = sorted(
            col for col in df_columns
            if col.startswith(prefix) and col != prefix
        )

        if not matched:
            print(f"⚠️  Wildcard '{src_str}' matched no columns in the dataset – skipping.")
            continue

        # look up the unit for the wildcard entry (keyed by dest pattern or src pattern)
        wildcard_unit = units.get(dest_str, units.get(src_str, ""))

        for col in matched:
            suffix   = col[len(prefix):]          # e.g. '1', '2', '3' …
            new_dest = f"{dest_prefix}{suffix}"   # e.g. 'SWC_1'
            new_src  = col                         # e.g. 'SWC_1'
            expanded_variables[new_dest] = new_src
            expanded_units[new_dest] = wildcard_unit
            print(f"    ↳ wildcard '{src_str}' → mapped '{new_src}' → '{new_dest}'")

    return expanded_variables, expanded_units

SOIL_PREFIXES = ("TS_", "SWC_")

def is_soil_variable(name):
    """Return True if the variable name (or wildcard pattern) refers to a soil variable."""
    return any(str(name).startswith(p) for p in SOIL_PREFIXES)

def read_soil_depths_from_metadata(metadata_file, ts_cols, swc_cols):
    """
    Parse an ICOS VARINFO CSV file and return per-variable depth vectors
    for TS and SWC, matched to the variable lists actually present in the data.

    The CSV has a long format with columns:
        SITE_ID, GROUP_ID, VARIABLE_GROUP, VARIABLE, DATAVALUE
    where each GROUP_ID groups rows for one sensor instance.
    Relevant VARIABLE values: VAR_INFO_VARNAME, VAR_INFO_HEIGHT.
    VAR_INFO_HEIGHT is negative (below surface, in metres); we negate it.

    When a variable name appears in multiple GROUP_IDs (replicate sensors at the
    same depth), the depth is taken as the mean of all reported depths for that
    variable name (they are always identical in practice).

    Parameters
    ----------
    metadata_file : str   full path to the CSV
    ts_cols       : list of str   e.g. ['TS_1','TS_2',...]  present in obstable
    swc_cols      : list of str   e.g. ['SWC_1','SWC_2',...] present in obstable

    Returns
    -------
    depths_ts  : list of float  [m], one entry per ts_col (same order)
    depths_swc : list of float  [m], one entry per swc_col (same order)
    """
    df = pd.read_csv(metadata_file)

    # Pivot GROUP_ID → {VAR_INFO_VARNAME, VAR_INFO_HEIGHT}
    pivot = (
        df[df["VARIABLE"].isin(["VAR_INFO_VARNAME", "VAR_INFO_HEIGHT"])]
        .pivot_table(index="GROUP_ID", columns="VARIABLE",
                     values="DATAVALUE", aggfunc="first")
        .reset_index()
    )
    pivot = pivot.rename(columns={"VAR_INFO_VARNAME": "varname",
                                   "VAR_INFO_HEIGHT":  "height"})
    pivot["height"] = pd.to_numeric(pivot["height"], errors="coerce")

    # Keep only soil variables; depth = -height (heights are negative = below surface)
    soil = pivot[pivot["varname"].str.match(r"(TS|SWC)_\d+", na=False)].copy()
    soil["depth_m"] = -soil["height"]

    # One depth per variable name (average over replicates, but they're always equal)
    depth_map = soil.groupby("varname")["depth_m"].mean().to_dict()

    def _resolve(cols, label):
        depths = []
        missing = []
        for c in cols:
            if c in depth_map:
                depths.append(round(depth_map[c], 4))
            else:
                missing.append(c)
        if missing:
            raise RuntimeError(
                f"Columns {missing} not found in metadata file {metadata_file}. "
                f"Cannot determine {label} depths."
            )
        return depths

    depths_ts  = _resolve(ts_cols,  "TS")
    depths_swc = _resolve(swc_cols, "SWC")
    return depths_ts, depths_swc


def get_soil_depths(initialization_data, ts_cols, swc_cols, osvas_path, station_name):
    """
    Resolve observation depth vectors for TS and SWC columns using the
    following priority:

    1. Explicit lists in YAML:
           Initialization_data.soil_depths_ts   (for TS)
           Initialization_data.soil_depths_swc  (for SWC)
       If only one generic ``soil_depths`` key is found it is used for both.
    2. Metadata file defined by Initialization_data.metadata_filename,
       looked up in config_files/{station_name}/.
    3. Error — no silent fallback from variable-name indices.

    Parameters
    ----------
    initialization_data : dict   the Initialization_data YAML block
    ts_cols, swc_cols   : lists of str   columns present in the obstable
    osvas_path          : str   $OSVAS root
    station_name        : str

    Returns
    -------
    depths_ts  : list of float [m]
    depths_swc : list of float [m]
    """
    # --- Priority 1: explicit YAML lists ---
    if "soil_depths_ts" in initialization_data or "soil_depths_swc" in initialization_data:
        depths_ts  = list(initialization_data.get("soil_depths_ts",  []))
        depths_swc = list(initialization_data.get("soil_depths_swc", []))
        if not depths_ts and ts_cols:
            raise RuntimeError("soil_depths_ts not specified in YAML but TS columns are present.")
        if not depths_swc and swc_cols:
            raise RuntimeError("soil_depths_swc not specified in YAML but SWC columns are present.")
        print("  ℹ️  Soil depths read from YAML (soil_depths_ts / soil_depths_swc).")
        return depths_ts, depths_swc

    if "soil_depths" in initialization_data:
        d = list(initialization_data["soil_depths"])
        print("  ℹ️  Soil depths read from YAML (generic soil_depths – applied to both TS and SWC).")
        return d, d

    # --- Priority 2: metadata file ---
    if "metadata_filename" in initialization_data:
        meta_file = os.path.join(
            osvas_path, "config_files", "Stations",station_name,
            initialization_data["metadata_filename"]
        )
        if not os.path.exists(meta_file):
            raise FileNotFoundError(
                f"metadata_filename '{initialization_data['metadata_filename']}' "
                f"not found at {meta_file}."
            )
        print(f"  ℹ️  Reading soil depths from metadata file: {meta_file}")
        depths_ts, depths_swc = read_soil_depths_from_metadata(meta_file, ts_cols, swc_cols)
        print(f"    TS  depths (m): {depths_ts}")
        print(f"    SWC depths (m): {depths_swc}")
        return depths_ts, depths_swc

    # --- No source found ---
    raise RuntimeError(
        "Cannot determine soil observation depths. "
        "Please add 'soil_depths_ts'/'soil_depths_swc' or 'metadata_filename' "
        "to the Initialization_data block of the YAML config."
    )



def write_obstable(df_merged, output_dir, units_map):
    """
    Write a merged dataframe to per-year OBSTABLE_{yyyy}.sqlite files.
    The dataframe must have valid_dttm as UTC datetime before this call.
    """
    df_out = df_merged.copy()
    df_out["valid_dttm"] = pd.to_datetime(df_out["valid_dttm"], utc=True)
    df_out["year_obs"] = df_out["valid_dttm"].dt.year
    df_out["valid_dttm"] = df_out["valid_dttm"].apply(lambda x: int(x.timestamp()))

    os.makedirs(output_dir, exist_ok=True)

    # ---  Loop over years ---
    for year, df_year in df_out.groupby("year_obs"):
        output_file = os.path.join(output_dir, f"OBSTABLE_{year}.sqlite")

        with sqlite3.connect(output_file) as conn:
            incoming_cols = list(df_year.columns)
            # ---  Build CREATE TABLE statement with correct types ---
            col_defs = []
            for c in incoming_cols:
                if c == "valid_dttm":
                    col_defs.append(f'"{c}" INTEGER')
                elif c == "SID":
                    col_defs.append(f'"{c}" DOUBLE')
                else:
                    col_defs.append(f'"{c}" REAL')

            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS SYNOP (
                    {", ".join(col_defs)},
                    UNIQUE("valid_dttm","SID")
                );
            """)
            # --- Detect existing columns ---
            existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(SYNOP);")]
            # --- Add new columns as REAL (except SID, which should already exist) ---
            for col in incoming_cols:
                if col not in existing_cols:
                    if col in ("SID", "valid_dttm"):
                        conn.execute(f'ALTER TABLE SYNOP ADD COLUMN "{col}" INTEGER;')
                    else:
                        conn.execute(f'ALTER TABLE SYNOP ADD COLUMN "{col}" REAL;')

            # --- Refresh column list ---
            existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(SYNOP);")]
            # --- Fill any missing columns in df ---
            for col in existing_cols:
                if col not in df_year.columns:
                    df_year[col] = None

            # --- Enforce integer type for SID before writing ---
            if "SID" in df_year.columns:
                df_year["SID"] = pd.to_numeric(df_year["SID"], errors="coerce").astype("Int64")

            df_year = df_year[existing_cols]
            # ---  Write to temporary table ---
            df_year.to_sql("SYNOP_tmp", conn, if_exists="replace", index=False)
            # --- Merge logic ---
            conn.execute("""
                DELETE FROM SYNOP
                WHERE (valid_dttm, SID) IN (
                    SELECT valid_dttm, SID FROM SYNOP_tmp
                );
            """)

            col_names = ", ".join([f'"{c}"' for c in existing_cols])
            conn.execute(f"""
                INSERT INTO SYNOP ({col_names})
                SELECT {col_names} FROM SYNOP_tmp;
            """)

            conn.execute("DROP TABLE SYNOP_tmp")
            # ---- create SYNOP_params if missing ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS SYNOP_params (
                    parameter VARCHAR PRIMARY KEY,
                    accum_hours REAL,
                    units VARCHAR
                );
            """)

            # ---- get SYNOP columns from the actual table schema ----
            synop_cols = [row[1] for row in conn.execute("PRAGMA table_info(SYNOP);")]
            # ---- define which columns are metadata and should NOT be listed in SYNOP_params ----
            skip_cols = {"SID", "valid_dttm", "lat", "lon", "elev", "year_obs"}
            # ---- find which parameter names are already present to avoid duplicates ----
            existing_params = {row[0] for row in conn.execute("SELECT parameter FROM SYNOP_params;")}
            # ---- prepare rows for insertion: only column names in SYNOP that are not metadata and not already present ----
            rows_to_insert = []
            for col in synop_cols:
                if col in skip_cols or col in existing_params:
                    continue
                unit = units_map.get(col, "")
                rows_to_insert.append((col, 0.0, unit))
            # ---- insert missing parameter rows ----
            if rows_to_insert:
                conn.executemany(
                    "INSERT INTO SYNOP_params (parameter, accum_hours, units) VALUES (?, ?, ?);",
                    rows_to_insert
                )
                conn.commit()

        print(f"✅ Year {year} data merged into {output_file}")

# ── Soil profile model (heat-equation analytical solution) ──────────────────

def _fit_harmonic(temperature, w):
    """
    Fit T = T_m + A*cos(w*t + phi) to a (depth × time) DataArray.

    Parameters
    ----------
    temperature : xr.DataArray  dims = (depth, time_coord)
    w           : angular frequency [rad / unit-of-time_coord]

    Returns
    -------
    T_m, A, phi : xr.DataArray  coords = (depth,)
    """
    import xarray as xr
    time_dim = temperature.dims[1]
    t = temperature[time_dim].values
    X = np.column_stack([np.ones_like(t), np.cos(w * t), np.sin(w * t)])
    Y = temperature.values

    T_m = np.full(Y.shape[0], np.nan)
    A   = np.full(Y.shape[0], np.nan)
    phi = np.full(Y.shape[0], np.nan)

    for i in range(Y.shape[0]):
        y = Y[i, :]
        mask = ~np.isnan(y)
        if mask.sum() < 3:
            continue
        beta, *_ = np.linalg.lstsq(X[mask], y[mask], rcond=None)
        tm, a, b = beta
        T_m[i] = tm
        A[i]   = np.sqrt(a**2 + b**2)
        phi[i] = np.arctan2(-b, a)

    T_m = xr.DataArray(T_m, coords={"depth": temperature.depth})
    A   = xr.DataArray(A,   coords={"depth": temperature.depth})
    phi = xr.DataArray(phi, coords={"depth": temperature.depth})
    return T_m, A, phi


def _compute_decay(amplitude):
    """
    Fit A(z) = A0*exp(-z/d) via log-linear regression.

    Returns
    -------
    d  : decay depth  [same units as amplitude.depth]
    A0 : surface amplitude
    """
    log_amp = np.log(amplitude)
    beta = log_amp.polyfit(dim="depth", deg=1)
    slope, intercept = beta["polyfit_coefficients"].values
    d  = -1.0 / slope
    A0 = np.exp(intercept)
    return d, A0


def _generate_temperature(depths, times, T_m, A_Y, D_Y, phi_Y, w_Y,
                                                A_D, D_D, phi_D, w_D):
    """
    T(z, t) = T_m + A_Y·exp(-z/D_Y)·cos(w_Y·DOY - z/D_Y + phi_Y)
                  + A_D·exp(-z/D_D)·cos(w_D·TOD - z/D_D + phi_D)

    Parameters
    ----------
    depths : 1-D array  [m]
    times  : 1-D array of np.datetime64 / pandas Timestamp
    T_m, A_Y, D_Y, phi_Y, w_Y : annual-cycle parameters
    A_D, D_D, phi_D, w_D      : daily-cycle parameters

    Returns
    -------
    xr.DataArray  dims=(depth, time)
    """
    import xarray as xr
    time_da  = xr.DataArray(times,  dims="time",  coords={"time":  times})
    depth_da = xr.DataArray(depths, dims="depth", coords={"depth": depths})

    doy = time_da.dt.dayofyear
    tod = time_da.dt.hour + time_da.dt.minute / 60.0 + time_da.dt.second / 3600.0

    z = depth_da
    annual = A_Y * np.exp(-z / D_Y) * np.cos(w_Y * doy  - z / D_Y + phi_Y)
    daily  = A_D * np.exp(-z / D_D) * np.cos(w_D * tod  - z / D_D + phi_D)

    T = T_m + annual + daily
    return xr.DataArray(T, dims=("depth", "time"),
                        coords={"depth": depths, "time": times})


def compute_soil_temperature_profile(temp_xr, profile_time, target_depths,
                                     coef=None):
    """
    Fit (or reuse) an analytical heat-equation model to observed soil
    temperatures and evaluate it at *target_depths* for *profile_time*.

    Parameters
    ----------
    temp_xr      : xr.DataArray  dims=(depth, time)  [°C, no offset needed here]
    profile_time : array-like of datetime64 / Timestamp
    target_depths: 1-D array of depths [m] for the output grid
    coef         : list of 9 floats (from a previous call) or None

    Returns
    -------
    coef : list  [T_m, A_Y, D_Y, phi_Y, w_Y, A_D, D_D, phi_D, w_D]
    Tz   : xr.DataArray  dims=(depth, time)  temperatures at target_depths [°C]
    """
    if coef is None:
        temp_xr.coords["tod"] = (temp_xr.time.dt.hour
                                 + temp_xr.time.dt.minute / 60.0)
        temp_xr.coords["doy"] = temp_xr.time.dt.dayofyear

        annual_cycle = temp_xr.groupby("doy").mean("time")
        daily_cycle  = temp_xr.groupby("tod").mean("time")

        w_Y = 2 * np.pi / 365.25
        w_D = 2 * np.pi / 24.0

        T_D, A_Dh, phi_D = _fit_harmonic(daily_cycle,  w_D)
        T_Y, A_Yh, phi_Y = _fit_harmonic(annual_cycle, w_Y)

        if not np.allclose(T_D.values, T_Y.values, atol=0.5):
            print("⚠️  Mean temperature differs between daily and annual harmonics:")
            print("    Daily  T_m:", T_D.values)
            print("    Annual T_m:", T_Y.values)

        D_D, A_D0 = _compute_decay(A_Dh)
        D_Y, A_Y0 = _compute_decay(A_Yh)

        K_D = D_D**2 * np.pi / (24 * 3600)
        K_Y = D_Y**2 * np.pi / (24 * 3600 * 365.25)
        print(f"  Thermal diffusivity — daily: {K_D:.3e} m²/s  annual: {K_Y:.3e} m²/s")

        coef = [float(T_Y[0]), float(A_Y0), float(D_Y),
                float(phi_Y[0]), float(w_Y),
                float(A_D0), float(D_D), float(phi_D[0]), float(w_D)]

    Tz = _generate_temperature(target_depths, profile_time, *coef)
    return coef, Tz


def load_soil_temp_from_obstable(obstable_dir, init_start, init_end,
                                 ts_cols, obs_depths):
    """
    Read TS_* columns from initialization OBSTABLEs and build an
    xr.DataArray with dims=(depth, time) [values in °C].

    Parameters
    ----------
    obstable_dir : str   path that contains OBSTABLE_{yyyy}.sqlite files
    init_start   : pd.Timestamp (UTC)
    init_end     : pd.Timestamp (UTC)
    ts_cols      : list of str   e.g. ['TS_1','TS_2',...]
    obs_depths   : list of float matching depths [m] for each ts_col

    Returns
    -------
    xr.DataArray  dims=(depth, time)
    """
    import xarray as xr

    start_year = init_start.year
    end_year   = init_end.year

    dfs = []
    for year in range(start_year, end_year + 1):
        fpath = os.path.join(obstable_dir, f"OBSTABLE_{year}.sqlite")
        if not os.path.exists(fpath):
            print(f"  ⚠️  {fpath} not found – skipping year {year}.")
            continue
        with sqlite3.connect(fpath) as conn:
            cols_sql = ", ".join([f'"{c}"' for c in ["valid_dttm"] + ts_cols])
            df = pd.read_sql(f"SELECT {cols_sql} FROM SYNOP", conn)
        dfs.append(df)

    if not dfs:
        raise RuntimeError("No initialization OBSTABLE files found in "
                           f"{obstable_dir} for the requested period.")

    df_all = pd.concat(dfs, ignore_index=True)
    df_all["valid_dttm"] = pd.to_datetime(df_all["valid_dttm"], unit="s", utc=True)
    df_all = df_all.sort_values("valid_dttm")

    # Keep only the requested window
    mask = (df_all["valid_dttm"] >= init_start) & (df_all["valid_dttm"] <= init_end)
    df_all = df_all.loc[mask].reset_index(drop=True)

    if df_all.empty:
        raise RuntimeError("Initialization OBSTABLE contains no data in the "
                           f"window {init_start} – {init_end}.")

    # Build xarray DataArray (depth × time)
    times  = df_all["valid_dttm"].values
    data   = df_all[ts_cols].values.T          # shape: (n_depths, n_times)
    temp   = xr.DataArray(data,
                          dims=("depth", "time"),
                          coords={"depth": obs_depths, "time": times})
    return temp


def format_namelist_block(values, variable_name):
    """
    Format a 1-D array as a SURFEX namelist block, e.g.:

        XUNIF_TG_SOIL(1)  = 277.00,
        XUNIF_TG_SOIL(2)  = 277.00,
        ...

    Parameters
    ----------
    values        : array-like of floats
    variable_name : str  e.g. 'XUNIF_TG_SOIL'

    Returns
    -------
    str
    """
    n      = len(values)
    idx_w  = len(str(n))            # width for index field
    lines  = []
    for i, v in enumerate(values, start=1):
        key = f"{variable_name}({i})"
        lines.append(f"                       {key:<{len(variable_name)+idx_w+2+1}}= {v:.2f},")
    return "\n".join(lines)


def plot_soil_temperature_diagnostics(temp_xr, Tz_full, tg_profile_K,
                                      obs_depths, XSOILGRID,
                                      profile_date, profile_path, station_name):
    """
    Produce two PNG diagnostic figures for the soil temperature profile fit.

    Figure 1 — timeseries_{date}.png
        One panel per observation depth: observed (grey) vs modelled (colour)
        temperature over the full initialization period.

    Figure 2 — profile_{date}.png
        Vertical profile at the profile date: observed values at obs_depths
        (dots) vs the modelled profile at XSOILGRID (line).

    Parameters
    ----------
    temp_xr       : xr.DataArray (depth, time) observed temperatures [°C]
    Tz_full       : xr.DataArray (depth, time) modelled temperatures at obs_depths [°C]
    tg_profile_K  : 1-D array  modelled profile at XSOILGRID [K]
    obs_depths    : list of float  observation depths [m]
    XSOILGRID     : list of float  model grid depths [m]
    profile_date  : pd.Timestamp  the initialisation date/time
    profile_path  : str  output directory
    station_name  : str  used in figure titles
    """
    n_depths   = len(obs_depths)
    date_str   = profile_date.strftime("%Y%m%d_%H%M%S")
    date_label = profile_date.strftime("%Y-%m-%d %H:%M UTC")

    # ── Figure 1: timeseries per depth ───────────────────────────────────────
    ncols = min(3, n_depths)
    nrows = int(np.ceil(n_depths / ncols))

    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(6 * ncols, 3 * nrows),
                             sharex=True, squeeze=False)
    fig.suptitle(f"Soil temperature — obs vs model\n{station_name}",
                 fontsize=13, fontweight="bold", y=1.01)

    # Convert time axis to pandas for nicer date formatting
    times_pd = pd.to_datetime(temp_xr.time.values)

    cmap   = plt.get_cmap("plasma", n_depths)

    for idx, depth in enumerate(obs_depths):
        row, col = divmod(idx, ncols)
        ax = axes[row][col]

        obs_ts = temp_xr.sel(depth=depth).values
        mod_ts = Tz_full.sel(depth=depth).values

        ax.plot(times_pd, obs_ts, color="0.65", linewidth=0.8,
                label="Observed", zorder=1)
        ax.plot(times_pd, mod_ts, color=cmap(idx), linewidth=1.4,
                label="Modelled", zorder=2)

        # Mark the profile date
        ax.axvline(profile_date, color="red", linewidth=1.2,
                   linestyle="--", label=date_label)

        ax.set_title(f"z = {depth:.2f} m", fontsize=10)
        ax.set_ylabel("T (°C)", fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right",
                 fontsize=8)
        ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.7)
        if idx == 0:
            ax.legend(fontsize=8, loc="upper right")

    # Hide unused panels
    for idx in range(n_depths, nrows * ncols):
        row, col = divmod(idx, ncols)
        axes[row][col].set_visible(False)

    fig.tight_layout()
    ts_path = os.path.join(profile_path, f"timeseries_{date_str}.png")
    fig.savefig(ts_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  📊 Timeseries figure saved to {ts_path}")

    # ── Figure 2: vertical profile at profile date ────────────────────────────
    # Observed: nearest time step to profile_date in temp_xr
    obs_times  = pd.to_datetime(temp_xr.time.values, utc=True)
    profile_date = pd.to_datetime(profile_date, utc=True)
    nearest_i  = np.argmin(np.abs(obs_times - profile_date))
    obs_profile_C = temp_xr.isel(time=nearest_i).values   # °C at obs_depths
    mod_profile_C = tg_profile_K - 273.15                 # K → °C at XSOILGRID

    fig2, ax2 = plt.subplots(figsize=(5, 7))

    ax2.plot(mod_profile_C, XSOILGRID,
             color="steelblue", linewidth=2, marker=".", markersize=6,
             label="Model (XSOILGRID)")
    ax2.scatter(obs_profile_C, obs_depths,
                color="tomato", zorder=5, s=60, marker="D",
                label=f"Observed ({obs_times[nearest_i].strftime('%Y-%m-%d %H:%M')} UTC)")

    ax2.set_xlabel("Temperature (°C)", fontsize=11)
    ax2.set_ylabel("Depth (m)", fontsize=11)
    ax2.invert_yaxis()
    ax2.set_title(f"Initial soil temperature profile\n{station_name}  —  {date_label}",
                  fontsize=11, fontweight="bold")
    ax2.legend(fontsize=9)
    ax2.grid(True, linestyle=":", linewidth=0.5, alpha=0.7)

    fig2.tight_layout()
    prof_path = os.path.join(profile_path, f"profile_{date_str}.png")
    fig2.savefig(prof_path, dpi=150, bbox_inches="tight")
    plt.close(fig2)
    print(f"  📊 Profile figure saved to {prof_path}")

def load_soil_humidity_from_obstable(obstable_dir, init_start, init_end,
                                     swc_cols, obs_depths):
    """
    Read SWC_* columns from initialization OBSTABLEs at the single timestep
    nearest to init_start and return observed volumetric water content as a
    plain 1-D numpy array (one value per obs depth).

    SWC values in ICOS are in % volumetric; SURFEX expects a dimensionless
    fraction in [0, 1] for XUNIF_HUG_SOIL, so values are divided by 100.

    Parameters
    ----------
    obstable_dir : str
    init_start   : pd.Timestamp (UTC)   target date/time
    init_end     : pd.Timestamp (UTC)   upper bound for search window
    swc_cols     : list of str
    obs_depths   : list of float [m]

    Returns
    -------
    swc_obs : np.ndarray  shape=(n_depths,)  values in [0, 1]
    nearest_time : pd.Timestamp  actual time of the selected record
    """
    dfs = []
    for year in range(init_start.year, init_end.year + 1):
        fpath = os.path.join(obstable_dir, f"OBSTABLE_{year}.sqlite")
        if not os.path.exists(fpath):
            continue
        with sqlite3.connect(fpath) as conn:
            cols_sql = ", ".join([f'"{c}"' for c in ["valid_dttm"] + swc_cols])
            dfs.append(pd.read_sql(f"SELECT {cols_sql} FROM SYNOP", conn))

    if not dfs:
        raise RuntimeError(f"No initialization OBSTABLE files found in {obstable_dir}.")

    df_all = pd.concat(dfs, ignore_index=True)
    df_all["valid_dttm"] = pd.to_datetime(df_all["valid_dttm"], unit="s", utc=True)
    df_all = df_all.sort_values("valid_dttm")

    # Select the row nearest to init_start that has at least one non-NaN SWC value
    mask = (df_all["valid_dttm"] >= init_start) & (df_all["valid_dttm"] <= init_end)
    df_window = df_all.loc[mask].reset_index(drop=True)

    if df_window.empty:
        raise RuntimeError(
            f"No SWC data in window {init_start} – {init_end} in {obstable_dir}."
        )

    # Pick row closest to init_start
    idx_nearest  = (df_window["valid_dttm"] - init_start).abs().argmin()
    nearest_time = df_window.loc[idx_nearest, "valid_dttm"]
    row          = df_window.loc[idx_nearest, swc_cols].values.astype(float)

    # Convert % → fraction
    swc_obs = row / 100.0

    print(f"  SWC snapshot taken at {nearest_time.strftime('%Y-%m-%d %H:%M')} UTC")
    return swc_obs, nearest_time


def interp_to_model_grid(obs_depths, obs_values, model_depths):
    """
    Linearly interpolate an observed soil profile from obs_depths onto
    model_depths.  For model levels deeper than the deepest observation,
    the deepest observed value is used (constant extrapolation).
    For model levels shallower than the shallowest observation, the
    shallowest observed value is used.

    Parameters
    ----------
    obs_depths   : array-like of float [m], sorted shallow→deep
    obs_values   : array-like of float, same length as obs_depths
    model_depths : array-like of float [m]

    Returns
    -------
    np.ndarray  shape=(len(model_depths),)
    """
    obs_z = np.array(obs_depths,   dtype=float)
    obs_v = np.array(obs_values,   dtype=float)
    mod_z = np.array(model_depths, dtype=float)

    return np.interp(mod_z, obs_z, obs_v,
                     left=obs_v[0], right=obs_v[-1])


def plot_soil_humidity_profile(swc_obs, obs_depths, hug_profile,
                               model_depths, nearest_time,
                               profile_date, profile_path, station_name):
    """
    Plot observed SWC profile (fraction) at obs_depths against the
    interpolated XUNIF_HUG_SOIL profile at model_depths.

    Parameters
    ----------
    swc_obs      : np.ndarray  observed values [0-1] at obs_depths
    obs_depths   : list of float [m]
    hug_profile  : np.ndarray  interpolated values [0-1] at model_depths
    model_depths : list of float [m]
    nearest_time : pd.Timestamp  actual obs time used
    profile_date : pd.Timestamp  requested init date
    profile_path : str
    station_name : str
    """
    date_str   = profile_date.strftime("%Y%m%d_%H%M%S")
    date_label = profile_date.strftime("%Y-%m-%d %H:%M UTC")

    fig, ax = plt.subplots(figsize=(5, 7))

    ax.plot(hug_profile, model_depths, "s--", color="steelblue", lw=1.5,
            ms=5, label=f"Interpolated (XSOILGRID)")
    ax.scatter(swc_obs, obs_depths, color="tomato", zorder=5, s=60,
               marker="D",
               label=f"Observed ({nearest_time.strftime('%Y-%m-%d %H:%M')} UTC)")

    ax.invert_yaxis()
    ax.set_xlabel("Volumetric water content (fraction)", fontsize=11)
    ax.set_ylabel("Depth (m)", fontsize=11)
    ax.set_title(
        f"Initial soil humidity profile\n{station_name}  —  {date_label}",
        fontsize=12, fontweight="bold"
    )
    ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.7)
    ax.legend(fontsize=9)

    fig.tight_layout()
    out_path = os.path.join(profile_path, f"humidity_profile_{date_str}.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  📊 Humidity profile figure saved to {out_path}")


def format_namelist_block(values, variable_name):
    """Format a 1-D array as a SURFEX namelist block."""
    n     = len(values)
    idx_w = len(str(n))
    lines = [
        f"                       {f'{variable_name}({i})':<{len(variable_name)+idx_w+2+1}}= {v:.2f},"
        for i, v in enumerate(values, start=1)
    ]
    return "\n".join(lines)


# ── end of soil profile model (heat-equation analytical solution) ──────────────────

## Functions for step 2.8: Update namelists and/or PREP.* with tg profile
def _update_namelist_tg(namelist_path, tg_profile):
    """
    Replace all XUNIF_TG_SOIL(*) lines in OPTIONS.nam with values from
    tg_profile (K, 0-based list).  The new block is inserted before the
    first closing '/' of the namelist so it lands inside &NAM_PREP_ISBA.
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

    # Remove any existing XUNIF_TG_SOIL(*) lines (with or without trailing comma)
    content = _re.sub(r'[ \t]*XUNIF_TG_SOIL\(\d+\)\s*=\s*[0-9.]+,?[ \t]*\n?', '', content)

    # Insert new block before the first closing '/' of the namelist
    new_content = _re.sub(
        r'(?m)^(\s*/\s*)$',
        lambda m: new_lines + "\n" + m.group(0),
        content,
        count=1
    )
    if new_content == content:          # no '/' found — just append
        new_content = content.rstrip() + "\n" + new_lines + "\n"

    with open(namelist_path, 'w') as f:
        f.write(new_content)

    print(f"    ✅ OPTIONS.nam updated with {n} XUNIF_TG_SOIL values.")


# ── Helper: patch PREP.txt ───────────────────────────────────────────────────

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


# ── Helper: patch PREP.nc ────────────────────────────────────────────────────

def _update_prep_nc_tg(prep_path, tg_profile):
    """
    In PREP.nc, overwrite every TGnPm variable whose current value is
    NOT masked (fill value 1e+20) with tg_profile[n-1] (K).
    """
    import netCDF4 as nc
    import numpy as np

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

    # Remove any existing XUNIF_HUG_SOIL(*) lines (with or without trailing comma)
    content = _re.sub(r'[ \t]*XUNIF_HUG_SOIL\(\d+\)\s*=\s*[0-9.]+,?[ \t]*\n?', '', content)

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
    import netCDF4 as nc
    import numpy as np

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



def fetch_flux_data(doi):
    dobj = Dobj(doi)
    df = dobj.data
    return df

def process_data(df, variable_map, station_info, start, end):
    df['valid_dttm'] = pd.to_datetime(df['TIMESTAMP'], utc=True)
    df = df[(df['valid_dttm'] >= start) & (df['valid_dttm'] <= end)].copy()

    # Drop rows with missing required vars
    source_vars = list(variable_map.values())
    df = df.dropna(subset=source_vars)

    # Add station metadata
    df["SID"] = int(station_info["SID"])
    df["SID"] = df["SID"].astype("Int64")  # optional if you want pandas nullable integer type
    df['lat'] = station_info['lat']
    df['lon'] = station_info['lon']
    df['elev'] = station_info['elev']

    # Rename variables
    df = df.rename(columns={v: k for k, v in variable_map.items()})
    selected_columns = ['valid_dttm', 'SID', 'lat', 'lon', 'elev'] + list(variable_map.keys())

    return df[selected_columns]

def upsample_to_common_timedelta(datasets, dfs, common_td):
    dfs_resampled = []

    for name, df in zip(datasets.keys(), dfs):
        orig_td = pd.to_timedelta(datasets[name]["timedelta"], unit="m")
        if orig_td == common_td:
            dfs_resampled.append(df)
        else:
            df = df.set_index("valid_dttm")
            df = df.resample(common_td).interpolate(method="linear")
            df = df.reset_index()
            dfs_resampled.append(df)

    return dfs_resampled

def _to_datetime_series(s):
    """Return datetime64[ns,UTC] series for index or column 'valid_dttm'."""
    # If already datetime
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s).dt.tz_convert('UTC') if s.dt.tz is not None else pd.to_datetime(s).dt.tz_localize('UTC')
    # If numeric -> assume epoch seconds
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_datetime(s, unit='s', utc=True)
    # Else try parse strings
    return pd.to_datetime(s, utc=True)

def enforce_seb_closure(df,
                        closure=1,
                        timestamp_col='valid_dttm'):
    """
    Enforce surface energy balance closure on df, returning a copy with H_cor and LE_cor.
    
    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: H, LE, SW_IN, SW_OUT, LW_IN, LW_OUT
        Optionally: G, S_can, S_T, S_veg, S_q
    closure : int (1,2,3,4)
        1: timestep BR (old-style)
        2: daily BR (use daily sums H and LE to compute BR, then apply per-timestep)
        3: timestep BR, include S_can in SEB (H+LE = Rn - G - S_can)
        4: timestep BR with S_can in SEB and BR uses canopy components:
           BR = (H + S_T + S_veg) / (LE + S_q)
    timestamp_col : str
        Column name holding timestamps (datetime or epoch seconds). Used only for closure==2.
        
    Returns
    -------
    df_out : pd.DataFrame (copy of input with added columns)
        Columns added: AE, BR_used, H_cor, LE_cor
    """
    df_out = df.copy()
    
    # Ensure timestamps
    if timestamp_col in df_out.columns:
        tseries = _to_datetime_series(df_out[timestamp_col])
        df_out['_dt_index_for_daily'] = tseries.dt.floor('D')  # used for closure==2
    else:
        # create a dummy index if no timestamp column
        df_out['_dt_index_for_daily'] = pd.NaT

    # Required radiation columns
    for col in ['SW_IN', 'SW_OUT', 'LW_IN', 'LW_OUT', 'H', 'LE']:
        if col not in df_out.columns:
            raise KeyError(f"Required column '{col}' missing from dataframe")

    # compute net radiation
    df_out['Rn'] = df_out['SW_IN'] - df_out['SW_OUT'] + df_out['LW_IN'] - df_out['LW_OUT']

    # ground heat flux G (if not present assume 0)
    df_out['G'] = df_out['G'] if 'G' in df_out.columns else 0.0

    # canopy storage S_can: prefer S_can column; else sum components if present; else 0.
    if 'S_can' in df_out.columns:
        df_out['S_can'] = df_out['S_can'].fillna(0.0)
    else:
        # component names may or may not exist
        sT = df_out['S_T'] if 'S_T' in df_out.columns else 0.0
        sveg = df_out['S_veg'] if 'S_veg' in df_out.columns else 0.0
        sq = df_out['S_q'] if 'S_q' in df_out.columns else 0.0
        # If any of these exist as Series, ensure fillna(0)
        def _maybe_fill(x):
            return x.fillna(0.0) if isinstance(x, pd.Series) else x
        df_out['S_can'] = _maybe_fill(sT) + _maybe_fill(sveg) + _maybe_fill(sq)

    # Available energy AE depending on closure mode:
    # closure 1 & 2: AE = Rn - G
    # closure 3 & 4: AE = Rn - G - S_can
    if closure in (1, 2):
        df_out['AE'] = df_out['Rn'] - df_out['G']
    elif closure in (3, 4):
        df_out['AE'] = df_out['Rn'] - df_out['G'] - df_out['S_can']
    else:
        raise ValueError("closure must be 1,2,3 or 4")

    # safe helper for division with fallback
    def compute_BR_timestep(Hs, LEs):
        """Return BR series H/LE with safe handling"""
        Hs = pd.Series(Hs).astype(float)
        LEs = pd.Series(LEs).astype(float)
        with np.errstate(divide='ignore', invalid='ignore'):
            br = Hs / LEs
        # When both zero -> set BR to 1 (split equally). When denominator zero but numerator nonzero -> large value
        mask_both_zero = (Hs == 0) & (LEs == 0)
        br.loc[mask_both_zero] = 1.0
        # When LE == 0 and H != 0, we keep br as is (inf) — will be handled later numerically
        return br

    # Determine BR_used per closure option
    if closure == 1:
        BR_used = compute_BR_timestep(df_out['H'], df_out['LE'])

    elif closure == 2:
        # daily BR computed from daily sums
        if '_dt_index_for_daily' not in df_out.columns:
            raise KeyError("Timestamp column required for closure==2")
        grouped = df_out.groupby('_dt_index_for_daily')[['H', 'LE']].sum(min_count=1)
        # compute daily BR safely
        BR_daily = compute_BR_timestep(grouped['H'], grouped['LE'])
        # map daily BR back to rows
        BR_used = df_out['_dt_index_for_daily'].map(BR_daily)
        # if some days missing (NaN) fallback to timestep BR for those rows
        br_tstep = compute_BR_timestep(df_out['H'], df_out['LE'])
        BR_used = BR_used.fillna(br_tstep)

    elif closure == 3:
        # same as 1 but AE already included S_can
        BR_used = compute_BR_timestep(df_out['H'], df_out['LE'])

    elif closure == 4:
        # BR = (H + S_T + S_veg) / (LE + S_q)
        # collect components, default 0 if missing
        S_T = df_out['S_T'] if 'S_T' in df_out.columns else 0.0
        S_veg = df_out['S_veg'] if 'S_veg' in df_out.columns else 0.0
        S_q = df_out['S_q'] if 'S_q' in df_out.columns else 0.0
        # ensure Series with fillna
        def _to_series_or_const(x):
            return x.fillna(0.0) if isinstance(x, pd.Series) else x
        a = _to_series_or_const(S_T) + _to_series_or_const(S_veg)   # added to H numerator
        b = _to_series_or_const(S_q)                                # added to LE denominator
        with np.errstate(divide='ignore', invalid='ignore'):
            BR_used = (df_out['H'] + a) / (df_out['LE'] + b)
        # if both numerator and denominator zero, fallback to 1
        mask_both_zero = ((df_out['H'] + a) == 0) & ((df_out['LE'] + b) == 0)
        BR_used.loc[mask_both_zero] = 1.0
    else:
        raise ValueError("closure must be 1..4")

    # store BR_used
    df_out['BR_used'] = BR_used.astype(float)

    # Solve for H_cor and LE_cor
    # general solution for closure types 1-3:
    #  Hc + Lec = AE
    #  Hc / Lec = BR  =>  Hc = AE * BR / (1 + BR) ; Lec = AE / (1 + BR)
    # For numerical stability, transform when BR is inf or very large or negative
    Hc = pd.Series(index=df_out.index, dtype=float)
    Lec = pd.Series(index=df_out.index, dtype=float)
    AE = df_out['AE'].astype(float)
    BR = df_out['BR_used'].astype(float)

    # handle closure 4 separately because BR definition includes storage terms and solution differs:
    if closure != 4:
        # Avoid dividing by (1+BR) issues. Use safe formula:
        denom = 1.0 + BR
        # If denom is zero (BR == -1) -> can't use ratio formula; fallback to distribute AE proportionally to absolute magnitudes
        mask_bad_denom = np.isclose(denom, 0.0) | (~np.isfinite(denom))
        # regular cases
        mask_regular = ~mask_bad_denom
        Hc.loc[mask_regular] = AE[mask_regular] * BR[mask_regular] / denom[mask_regular]
        Lec.loc[mask_regular] = AE[mask_regular] / denom[mask_regular]

        # fallback for bad denom or NaN BR: distribute AE using observed H and LE proportions
        mask_fallback = mask_bad_denom | (~np.isfinite(BR))
        if mask_fallback.any():
            # proportions from observed magnitudes; use absolute because signs can cancel
            sum_obs = (np.abs(df_out.loc[mask_fallback, 'H']) + np.abs(df_out.loc[mask_fallback, 'LE']))
            # if sum_obs == 0 -> split equally
            eq_mask = sum_obs == 0
            if eq_mask.any():
                Hc.loc[mask_fallback][eq_mask] = 0.5 * AE.loc[mask_fallback][eq_mask]
                Lec.loc[mask_fallback][eq_mask] = 0.5 * AE.loc[mask_fallback][eq_mask]
            # else distribute proportionally
            non_eq_mask = ~eq_mask
            if non_eq_mask.any():
                p = np.abs(df_out.loc[mask_fallback, 'H']) / sum_obs
                Hc.loc[mask_fallback][non_eq_mask] = AE.loc[mask_fallback][non_eq_mask] * p[non_eq_mask]
                Lec.loc[mask_fallback][non_eq_mask] = AE.loc[mask_fallback][non_eq_mask] * (1.0 - p[non_eq_mask])

    else:
        # closure == 4: solve linear system with canopy terms
        # System:
        #   Hc + Lec = AE
        #   (Hc + a) = BR*(Lec + b)  => Hc - BR*Lec = BR*b - a
        # Solve:
        # From Hc = AE - Lec -> AE - Lec - BR*Lec = BR*b - a
        # => Lec * (1 + BR) = AE - (BR*b - a)
        # => Lec = (AE - (BR*b - a)) / (1 + BR)
        S_T = df_out['S_T'] if 'S_T' in df_out.columns else 0.0
        S_veg = df_out['S_veg'] if 'S_veg' in df_out.columns else 0.0
        S_q = df_out['S_q'] if 'S_q' in df_out.columns else 0.0
        a = (S_T if isinstance(S_T, (int,float)) else S_T.fillna(0.0)) + (S_veg if isinstance(S_veg, (int,float)) else S_veg.fillna(0.0))
        b = S_q if isinstance(S_q, (int,float)) else S_q.fillna(0.0)

        denom = 1.0 + BR
        # regular cases
        mask_regular = ~np.isclose(denom, 0.0) & np.isfinite(denom)
        if mask_regular.any():
            Lec.loc[mask_regular] = (AE.loc[mask_regular] - (BR.loc[mask_regular] * b.loc[mask_regular] - a.loc[mask_regular])) / denom.loc[mask_regular]
            Hc.loc[mask_regular] = AE.loc[mask_regular] - Lec.loc[mask_regular]

        # fallback if denom zero or invalid: distribute AE by observed proportions as before
        mask_fallback = ~mask_regular
        if mask_fallback.any():
            sum_obs = (np.abs(df_out.loc[mask_fallback, 'H']) + np.abs(df_out.loc[mask_fallback, 'LE']))
            eq_mask = sum_obs == 0
            if eq_mask.any():
                Hc.loc[mask_fallback][eq_mask] = 0.5 * AE.loc[mask_fallback][eq_mask]
                Lec.loc[mask_fallback][eq_mask] = 0.5 * AE.loc[mask_fallback][eq_mask]
            non_eq_mask = ~eq_mask
            if non_eq_mask.any():
                p = np.abs(df_out.loc[mask_fallback, 'H']) / sum_obs
                Hc.loc[mask_fallback][non_eq_mask] = AE.loc[mask_fallback][non_eq_mask] * p[non_eq_mask]
                Lec.loc[mask_fallback][non_eq_mask] = AE.loc[mask_fallback][non_eq_mask] * (1.0 - p[non_eq_mask])

    # attach to df_out
    df_out['H_cor'] = Hc
    df_out['LE_cor'] = Lec

    # cleanup helper column if created
    if '_dt_index_for_daily' in df_out.columns:
        df_out.drop(columns=['_dt_index_for_daily'], inplace=True)

    return df_out


# In[ ]:


###### OSVAS ###################################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)######################################
#### STEP 2.2: LOAD STATION METADATA AND CONFIGURATION OF  #####################
#### THE GENERATION OF VALIDATION SQLITES FROM THE STATION'S YAML FILE #########

os.chdir(OSVAS)
CONFIG_PATH = f"config_files/Stations/{Station_name}/{Station_name}.yml"

with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)

station_info = config["Station_metadata"]
validation_data = config["Validation_data"]
common_obstable = validation_data.get("common_obstable", False)

start_date = pd.to_datetime(validation_data["validation_start"], utc=True)
end_date = pd.to_datetime(validation_data["validation_end"], utc=True)

closure_type = config.get("Station_metadata", {}).get("closure_type", 1) #Default value is 1.

datasets = {k: v for k, v in validation_data.items() if k.startswith("dataset") or k.startswith("dataset_")}

# Get access to ICOS
# Authenticate using cookie (adjust if needed)
cookie_path = "icos_cookie.txt"  # Or point to config
cookie_token = open(cookie_path, "r").readline().strip()
meta, data = bootstrap.fromCookieToken(cookie_token)
cpauth.init_by(data.auth)

#Test: If the authentication went well, these lines of code will not fail:
import icoscp
from icoscp.dobj import Dobj
obj_flux='https://meta.icos-cp.eu/objects/dDlpnhS3XKyZjB22MUzP_nAm'
dobj_flux=Dobj(obj_flux).data


# In[ ]:


###### OSVAS ###################################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)######################################
#### STEP 2.3: Main loop over datasets, abort if no data in range ##############

dfs = []
timedeltas = []
units_map = {}  # <-- Dict that will be filled with var/units pairs from all datasets
for ds_name, ds_info in datasets.items():
    print(f"Processing {ds_name} from DOI: {ds_info['doi']}")
    doi = ds_info["doi"]
    timedelta_minutes = ds_info["timedelta"]
    timedeltas.append(timedelta_minutes)

    # Fetch raw data first so wildcard expansion can inspect actual column names
    df_raw = fetch_flux_data(doi)

    # Expand any wildcard entries (e.g. SWC_*: SWC_*) against the real columns
    raw_variables = {k: v for k, v in ds_info["variables"].items() if v is not None}
    raw_units     = {k: v for k, v in ds_info.get("units", {}).items() if v is not None}
    variable_map, expanded_units = expand_wildcard_variables(
        raw_variables, raw_units, list(df_raw.columns)
    )
    units_map.update(expanded_units)
    df_processed = process_data(df_raw, variable_map, station_info, start_date, end_date)

    # Abort if no data in the specified time window
    if df_processed.empty:
        raise RuntimeError(
            f"❌ No data found in the time window ({start_date} to {end_date}) "
            f"for dataset {ds_name} (DOI: {doi}). Aborting."
        )

    dfs.append(df_processed)


# In[ ]:


###### OSVAS ############################################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)###############################################
#### STEP 2.4: Harmonize resolution, merge datasets, apply SEB closure if needed ########
common_td = pd.to_timedelta(min(timedeltas), unit="m")  # Choose finest resolution
dfs_resampled = upsample_to_common_timedelta(datasets, dfs, common_td)
# Cell 6: Merge all datasets, produce Hcor and LEcor based in a closure method if necessary and all SEB components available.
from functools import reduce
df_merged = reduce(lambda left, right: pd.merge(left, right, on=['valid_dttm', 'SID', 'lat', 'lon', 'elev'], how='outer'), dfs_resampled)
df_merged = df_merged.sort_values("valid_dttm").reset_index(drop=True)

#df_merged=enforce_seb_closure(df_merged,closure_type)


# In[ ]:


###### OSVAS ############################################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)###############################################
#### STEP 2.5: Convert to Unix timestamp in seconds and save dataframe to SQLite#########

output_dir = (
    "sqlites/validation_data/common_obstables"
    if common_obstable
    else f"sqlites/validation_data/{station_info['Station_name']}"
)

write_obstable(df_merged, output_dir, units_map)


# In[ ]:


###### OSVAS ############################################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)###############################################
#### STEP 2.6: Build soil initialization SQLites from Initialization_data block #########
#### Only datasets containing TS_* or SWC_* variables are processed.            #########

initialization_data = config.get("Initialization_data")

if initialization_data:
    print("\n▶ Building soil initialization OBSTABLEs...")

    init_start = pd.to_datetime(initialization_data["initialization_start"], utc=True)
    init_end   = pd.to_datetime(initialization_data["initialization_end"],   utc=True)

    # Re-use the same dataset blocks from Validation_data, filtered to soil-only variables
    # and limited to the initialization time window.
    init_dfs     = []
    init_tdeltas = []
    init_units   = {}
    init_datasets = {k: v for k, v in validation_data.items()
                     if k.startswith("dataset") or k.startswith("dataset_")}

    for ds_name, ds_info in init_datasets.items():

        # Keep only soil variables (TS_* and SWC_*) from this dataset's variable map
        raw_variables = {k: v for k, v in ds_info["variables"].items() if v is not None}
        soil_variables = {k: v for k, v in raw_variables.items() if is_soil_variable(k)}

        if not soil_variables:
            print(f"  ⏩ {ds_name}: no soil variables – skipping for initialization.")
            continue

        print(f"  Processing {ds_name} for initialization (DOI: {ds_info['doi']})")

        raw_units = {k: v for k, v in ds_info.get("units", {}).items() if v is not None}

        df_raw = fetch_flux_data(ds_info["doi"])

        # Expand wildcards against actual columns, keeping only soil vars
        soil_map, expanded_units = expand_wildcard_variables(
            soil_variables, raw_units, list(df_raw.columns)
        )
        init_units.update(expanded_units)

        df_processed = process_data(df_raw, soil_map, station_info, init_start, init_end)

        if df_processed.empty:
            print(f"  ⚠️  No data in initialization window for {ds_name} – skipping.")
            continue

        init_dfs.append(df_processed)
        init_tdeltas.append(ds_info["timedelta"])

    if init_dfs:
        from functools import reduce as _reduce
        init_common_td = pd.to_timedelta(min(init_tdeltas), unit="m")

        # Build a lightweight datasets dict for upsample_to_common_timedelta
        init_ds_meta = {f"ds{i}": {"timedelta": td} for i, td in enumerate(init_tdeltas)}
        init_dfs_resampled = upsample_to_common_timedelta(init_ds_meta, init_dfs, init_common_td)

        df_init_merged = _reduce(
            lambda l, r: pd.merge(l, r, on=['valid_dttm', 'SID', 'lat', 'lon', 'elev'], how='outer'),
            init_dfs_resampled
        ).sort_values("valid_dttm").reset_index(drop=True)

        init_common_obstable = validation_data.get("common_obstable", False)
        init_output_dir = (
            "sqlites/initialization_data/common_obstables"
            if init_common_obstable
            else f"sqlites/initialization_data/{station_info['Station_name']}"
        )
        write_obstable(df_init_merged, init_output_dir, init_units)
        print("✅ Soil initialization OBSTABLEs written.")
    else:
        print("⚠️  No soil data available for the initialization period – no files written.")
        init_output_dir = None
        df_init_merged  = None
else:
    print("⏩ No Initialization_data block found in config – skipping initialization SQLites.")
    init_output_dir = None
    df_init_merged  = None


# In[ ]:


###### OSVAS ############################################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)###############################################
#### STEP 2.7: Compute initial soil temperature profile for SURFEX namelist      #########
#### Fits an analytical heat-equation model (daily + annual harmonic) to TS_*   #########
#### observations, evaluates it at the model grid (XSOILGRID) for run_start.    #########
#### Observation depths are read from the YAML or from the ICOS metadata file.  #########
#### Output: XUNIF_TG_SOIL namelist block in profiles/{station}/TG_init_*.nam   #########
####                        + diagnostic PNGs in profiles/{station}/            #########
if initialization_data and init_output_dir is not None and df_init_merged is not None:
    print("\n▶ Computing initial soil temperature profile (Step 2.7)...")

    # ── Target model grid (metres, top→bottom) ────────────────────────────────
    # Define here or move to YAML as Initialization_data.XSOILGRID
    XSOILGRID = initialization_data.get(
        "XSOILGRID",
        [0.01, 0.04, 0.10, 0.20, 0.40, 0.60, 0.80,
         1.00, 1.50, 2.00, 3.00, 5.00, 8.00, 12.0]
    )

    # ── Collect TS and SWC column names present in the merged init dataframe ──
    ts_cols  = sorted(
        [c for c in df_init_merged.columns if c.startswith("TS_")],
        key=lambda x: int(x.split("_")[1])
    )
    swc_cols = sorted(
        [c for c in df_init_merged.columns if c.startswith("SWC_")],
        key=lambda x: int(x.split("_")[1])
    )

    if not ts_cols:
        print("⚠️  No TS_* columns found in the initialization data – skipping Step 2.7.")
    else:
        # ── Resolve observation depths (never inferred from column names) ─────
        depths_ts, depths_swc = get_soil_depths(
            initialization_data,
            ts_cols,
            swc_cols,
            OSVAS,
            Station_name
        )

        # ── Profile date = Forcing_data.run_start ─────────────────────────────
        profile_date  = pd.to_datetime(config["Forcing_data"]["run_start"], utc=True)
        profile_times = np.array([profile_date.tz_localize(None)], dtype="datetime64[ns]")
        # ── Load temperature observations from obstable ───────────────────────
        print(f"  Loading TS data from {init_output_dir} …")
        temp_xr = load_soil_temp_from_obstable(
            init_output_dir, init_start, init_end, ts_cols, depths_ts
        )

        # ── Try to reuse saved coefficients ───────────────────────────────────
        profile_path = os.path.join(OSVAS, "profiles", Station_name)
        os.makedirs(profile_path, exist_ok=True)
        coeff_file   = os.path.join(profile_path, "TG_coefficients.txt")

        reuse_coeffs = bool(initialization_data.get("reuse_soil_profile", False))

        coef = None

        if reuse_coeffs:

            try:

                coef = list(np.loadtxt(coeff_file))

                print(f"  ✅ Reusing saved coefficients from {coeff_file}")

            except OSError:

                coef = None

                print("  ℹ️  No saved coefficients found – fitting model to observations.")

        else:

            if os.path.exists(coeff_file):

                print("  ℹ️  Existing coefficients found but reuse_soil_profile is false; recomputing.")

            else:

                print("  ℹ️  Computing fresh coefficients for soil profile initialization.")

        # ── Fit / evaluate model at obs depths (for diagnostics) ─────────────
        coef, Tz_obs = compute_soil_temperature_profile(
            temp_xr, temp_xr.time.values, depths_ts, coef
        )

        # ── Evaluate model at target XSOILGRID for the namelist ──────────────
        _, Tz_target = compute_soil_temperature_profile(
            temp_xr, profile_times, XSOILGRID, coef
        )


        np.savetxt(coeff_file, coef)
        print(f"  Coefficients saved to {coeff_file}")

        # ── Convert °C → K and write TG namelist ─────────────────────────────
        tg_profile     = Tz_target.sel(time=profile_times[0]).values + 273.15
        namelist_block = format_namelist_block(tg_profile, "XUNIF_TG_SOIL")

        print("\n  SURFEX namelist block for initial soil temperatures:")
        print(namelist_block)

        profile_str  = profile_date.strftime("%Y%m%d_%H%M%S")
        out_nam_file = os.path.join(profile_path, f"TG_init_{profile_str}.nam")
        with open(out_nam_file, "w") as f:
            f.write(namelist_block + "\n")
        print(f"\n  ✅ TG namelist block written to {out_nam_file}")

        tg_profile_file = os.path.join(profile_path, "tg_profile.npy")
        np.save(tg_profile_file, tg_profile)
        print(f"  ✅ TG profile saved to {tg_profile_file}")

        # ── Soil humidity: observed profile interpolated to XSOILGRID ────────
        hug_profile = None
        if swc_cols:
            print(f"\n  Loading SWC data from {init_output_dir} …")
            try:
                swc_obs, swc_nearest_time = load_soil_humidity_from_obstable(
                    init_output_dir, init_start, init_end, swc_cols, depths_swc
                )
                hug_profile = interp_to_model_grid(depths_swc, swc_obs, XSOILGRID)

                hug_block = format_namelist_block(hug_profile, "XUNIF_HUG_SOIL")
                print("\n  SURFEX namelist block for initial soil humidity:")
                print(hug_block)

                out_hug_file = os.path.join(profile_path, f"HUG_init_{profile_str}.nam")
                with open(out_hug_file, "w") as f:
                    f.write(hug_block + "\n")
                print(f"\n  ✅ HUG namelist block written to {out_hug_file}")

                hug_profile_file = os.path.join(profile_path, "hug_profile.npy")
                np.save(hug_profile_file, hug_profile)
                print(f"  ✅ HUG profile saved to {hug_profile_file}")

                plot_soil_humidity_profile(
                    swc_obs      = swc_obs,
                    obs_depths   = depths_swc,
                    hug_profile  = hug_profile,
                    model_depths = XSOILGRID,
                    nearest_time = swc_nearest_time,
                    profile_date = profile_date,
                    profile_path = profile_path,
                    station_name = Station_name
                )
            except Exception as e:
                print(f"  ⚠️  Could not compute HUG profile: {e}")
        else:
            print("  ℹ️  No SWC_* columns found – skipping XUNIF_HUG_SOIL.")

        # ── Diagnostic figures (temperature) ─────────────────────────────────
        plot_soil_temperature_diagnostics(
            temp_xr       = temp_xr,
            Tz_full       = Tz_obs,
            tg_profile_K  = tg_profile,
            obs_depths    = depths_ts,
            XSOILGRID     = XSOILGRID,
            profile_date  = profile_date,
            profile_path  = profile_path,
            station_name  = Station_name
        )
else:
    print("⏩ Skipping Step 2.7 (no initialization data available).")



# In[ ]:


###### OSVAS ############################################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)###############################################
#### STEP 2.8: Apply soil temperature initialization profile to OPTIONS.nam     #########
####           and/or PREP files for each experiment.                           #########
####                                                                            #########
#### YAML triggers (under Initialization_data):                                 #########
####   Init_to_namelist: true  → patch XUNIF_TG_SOIL(*) and XUNIF_HUG_SOIL(*) #########
####                             in OPTIONS.nam                                 #########
####   Init_to_prep:     true  → patch defined TGnPm / WGnPm entries in        #########
####                             PREP.txt and/or PREP.nc                        #########
####                                                                            #########
#### tg_profile (K) and hug_profile ([0-1]) from Step 2.7 are used directly.  #########
#### Layer index mapping: TGn/WGn / XUNIF_*_SOIL(n) → profile[n-1]            #########


'''
# ── Step 2.8 execution ───────────────────────────────────────────────────────

init_cfg         = config.get('Initialization_data', {}) if config else {}
init_to_namelist = init_cfg.get('Init_to_namelist', False)
init_to_prep     = init_cfg.get('Init_to_prep',     False)

if not (init_to_namelist or init_to_prep):
    print("⏩ Skipping Step 2.8: Init_to_namelist and Init_to_prep both False "
          "(or Initialization_data absent).")
elif 'tg_profile' not in dir() or tg_profile is None:
    print("⚠️  Step 2.8 skipped: tg_profile not available "
          "(Step 2.7 must run successfully first).")
else:
    print("\n▶ Running Step 2.8: Apply TG/HUG initialization profiles to experiment files")

    expnames = config['OSVAS_steps'].get('Expnames', [])
    if not expnames:
        print("  ⚠️  No Expnames defined in YAML – nothing to update.")
    else:
        for expname in expnames:
            run_dir = os.path.join(OSVAS, "RUNS", Station_name, expname, "run")
            print(f"\n  [{expname}]  run_dir: {run_dir}")

            # ── Namelist update ───────────────────────────────────────────────
            if init_to_namelist:
                namelist_path = os.path.join(run_dir, "OPTIONS.nam")
                if os.path.exists(namelist_path):
                    _update_namelist_tg(namelist_path, tg_profile)
                    if 'hug_profile' in dir() and hug_profile is not None:
                        _update_namelist_hug(namelist_path, hug_profile)
                    else:
                        print("    ℹ️  No HUG profile available – XUNIF_HUG_SOIL not updated.")
                else:
                    print(f"    ⚠️  OPTIONS.nam not found in {run_dir} – skipping.")

            # ── PREP file update ──────────────────────────────────────────────
            if init_to_prep:
                prep_txt  = os.path.join(run_dir, "PREP.txt")
                prep_nc   = os.path.join(run_dir, "PREP.nc")
                found_any = False
                if os.path.exists(prep_txt):
                    print(f"    Updating PREP.txt …")
                    _update_prep_txt_tg(prep_txt, tg_profile)
                    if 'hug_profile' in dir() and hug_profile is not None:
                        _update_prep_txt_wg(prep_txt, hug_profile)
                    found_any = True
                if os.path.exists(prep_nc):
                    print(f"    Updating PREP.nc …")
                    _update_prep_nc_tg(prep_nc, tg_profile)
                    if 'hug_profile' in dir() and hug_profile is not None:
                        _update_prep_nc_wg(prep_nc, hug_profile)
                    found_any = True
                if not found_any:
                    print(f"    ⚠️  No PREP.txt or PREP.nc found in {run_dir} – skipping.")

    print("\n✅ Step 2.8 complete.")
'''

