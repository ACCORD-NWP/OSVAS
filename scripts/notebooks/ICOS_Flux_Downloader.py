#!/usr/bin/env python
# coding: utf-8

# In[1]:


###### OSVAS ########################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)###########################
###### STEP 2: Downloading validation data from ICOS #############
#### STEP 2.0: DEFINING STATION and OSVAS PATH ########################
import os
# Default values defined in the notebook for Station and OSVAS install:
OSVAS='/home/pn56/OSVASgh/'  # Main OSVAS path
Station_name='Loobos'

# If an environment variable STATION or OSVAS exists, override the default
Station_name = os.getenv("STATION_NAME", Station_name)
OSVAS = os.getenv("OSVAS", OSVAS)

print(f"Creating Validation files for: {Station_name} with OSVAS installation in {OSVAS}" )


# In[2]:


###### OSVAS ##################################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)#####################################
#### STEP 2.1: IMPORTING NEEDED PACKAGES AND DEFINING FUNCTIONS ###############
import pandas as pd
import numpy as np
import sqlite3
import os
import yaml
from icoscp.cpb.dobj import Dobj
from icoscp_core.icos import bootstrap
from icoscp import cpauth

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


# In[3]:


###### OSVAS ###################################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)######################################
#### STEP 2.2: LOAD STATION METADATA AND CONFIGURATION OF  #####################
#### THE GENERATION OF VALIDATION SQLITES FROM THE STATION'S YAML FILE #########

os.chdir(OSVAS)
CONFIG_PATH = f"config_files/Stations/{Station_name}.yml"

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


# In[4]:


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

    variable_map = {k: v for k, v in ds_info["variables"].items() if v is not None}
    units_map.update({k: v for k, v in ds_info["units"].items() if v is not None})
    # Fetch and process
    df_raw = fetch_flux_data(doi)
    df_processed = process_data(df_raw, variable_map, station_info, start_date, end_date)

    # Abort if no data in the specified time window
    if df_processed.empty:
        raise RuntimeError(
            f"❌ No data found in the time window ({start_date} to {end_date}) "
            f"for dataset {ds_name} (DOI: {doi}). Aborting."
        )

    dfs.append(df_processed)


# In[5]:


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


# In[6]:


###### OSVAS ############################################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)###############################################
#### STEP 2.5: Convert to Unix timestamp in seconds and save dataframe to SQLite#########

import sqlite3
import os
import pandas as pd

# --- 1️⃣ Preprocess dataframe ---
df_merged["valid_dttm"] = pd.to_datetime(df_merged["valid_dttm"], utc=True)
df_merged["year_obs"] =df_merged["valid_dttm"].dt.year  # extract year for splitting
df_merged["valid_dttm"] = df_merged["valid_dttm"].apply(lambda x: int(x.timestamp()))
#df_merged["valid_dttm"] =_to_datetime_series(df_merged["valid_dttm"])

output_dir = (
    "sqlites/validation_data/common_obstables"
    if common_obstable
    else f"sqlites/validation_data/{station_info['Station_name']}"
)
os.makedirs(output_dir, exist_ok=True)

# --- 2️⃣ Loop over years ---
for year, df_year in df_merged.groupby("year_obs"):
    output_file = os.path.join(output_dir, f"OBSTABLE_{year}.sqlite")

    with sqlite3.connect(output_file) as conn:
        incoming_cols = list(df_year.columns)

        # --- 1️⃣ Build CREATE TABLE statement with correct types ---
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

        # --- 2️⃣ Detect existing columns ---
        existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(SYNOP);")]

        # --- 3️⃣ Add new columns as REAL (except SID, which should already exist) ---
        for col in incoming_cols:
            if col not in existing_cols:
                if col in ("SID","valid_dttm"):
                    conn.execute(f'ALTER TABLE SYNOP ADD COLUMN "{col}" INTEGER;')
                else:
                    conn.execute(f'ALTER TABLE SYNOP ADD COLUMN "{col}" REAL;')

        # --- 4️⃣ Refresh column list ---
        existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(SYNOP);")]

        # --- 5️⃣ Fill any missing columns in df ---
        for col in existing_cols:
            if col not in df_year.columns:
                df_year[col] = None

        # --- 6️⃣ Enforce integer type for SID before writing ---
        if "SID" in df_year.columns:
            df_year["SID"] = pd.to_numeric(df_year["SID"], errors="coerce").astype("Int64")

        df_year = df_year[existing_cols]

        # --- 7️⃣ Write to temporary table ---
        df_year.to_sql("SYNOP_tmp", conn, if_exists="replace", index=False)

        # --- 8️⃣ Merge logic ---
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
            if col in skip_cols:
                continue
            if col in existing_params:
                continue
            unit = units_map.get(col, "")   # default to empty string if not in units_map
            rows_to_insert.append((col, 0.0, unit))

        # ---- insert missing parameter rows ----
        if rows_to_insert:
            conn.executemany(
                "INSERT INTO SYNOP_params (parameter, accum_hours, units) VALUES (?, ?, ?);",
                rows_to_insert
            )
            conn.commit()        

    print(f"✅ Year {year} data merged into {output_file}")


# In[ ]:




