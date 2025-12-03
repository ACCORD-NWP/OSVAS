#!/usr/bin/env python
# coding: utf-8

# In[ ]:


###### OSVAS ########################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)###########################
###### STEP 1: Downloading forcing data from ICOS #############
#### STEP 1.0: DEFINING STATION and OSVAS PATH ###############
import os
# Default values defined in the notebook for Station and OSVAS install:
OSVAS='/home/pn56/OSVASgh/'  # Main OSVAS path
Station_name='Majadas_del_tietar'

# If an environment variable STATION or OSVAS exists, override the default
Station_name = os.getenv("STATION_NAME", Station_name)
OSVAS = os.getenv("OSVAS", OSVAS)

print(f"Creating forcing for {Station_name} with OSVAS installation in {OSVAS}" )


# In[ ]:


###### OSVAS ########################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)###########################
#### STEP 1.1: IMPORTING NEEDED PACKAGES AND DEFINING FUNCTIONS ###############
import icoscp
from icoscp.dobj import Dobj
import sys
sys.path.append("~/.local/lib/python3.10/site-packages/")
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import scipy.stats as stats
import numpy as np
from datetime import date, datetime, timedelta, timezone
import os
import time
import metpy
#import meteo
#import meteo.humidity
#import meteo.air
# Note: meteo package available here: https://github.com/hendrikwout/meteo
from pathlib import Path
import datetime as dt
import xarray as xr
from netCDF4 import Dataset, date2num
import cftime
from metpy.calc import (
    mixing_ratio_from_relative_humidity,
    specific_humidity_from_mixing_ratio,
    saturation_vapor_pressure,
)
from metpy.units import units
import yaml
from icoscp.dobj import Dobj
from icoscp_core.icos import bootstrap
from icoscp import cpauth
import re

plt.rcParams['figure.dpi'] = 500
##############################################################################
##Here comes a series of functions for handling the forcing creation easily ##
##############################################################################
def datespan(startDate, endDate, delta=timedelta(days=1)):
    currentDate = startDate
    while currentDate < endDate:
        yield currentDate
        currentDate += delta

def despike(pandas_column, sigma_delta):
   # This function substitutes spikes in data (replaced by nan)
   # The finding criteria for a spike is that contiguous values differ by
   # more than 3*sigma wrt the distribution of series of differences between consecutive
   # values
   delta_z_abs=np.abs(stats.zscore(pandas_column.diff(1),nan_policy='omit'))
   delta_z_abs[0]=0 # Make first value zero instead of nan
   pandas_column_filtered=pandas_column.where(delta_z_abs<sigma_delta, np.nan)
   return pandas_column_filtered

def reduce_pres(pandas_column,station_height):
    #This function reduces pressure in Pa from surface to station height
    #It assumes a pressure gradient of 100 Pa each 9m
    pandas_column_reduced=pandas_column-100*station_height/9
    return pandas_column_reduced


def rh2sh(RH, p, T):
    """Convert relative humidity (0–1), pressure (Pa), and temperature (K) to specific humidity."""
    RH = RH.to_numpy() * units.dimensionless
    p = p.to_numpy() * units.Pa
    T = T.to_numpy() * units.kelvin

    mixr = mixing_ratio_from_relative_humidity(p, T, RH)
    sh = specific_humidity_from_mixing_ratio(mixr)
    return sh.magnitude

def rh2ah(RH, p, T):
    """Convert RH (0–1), pressure (Pa), and temperature (K) to absolute humidity (kg/m³)."""
    RH = RH.to_numpy() * units.dimensionless
    T = T.to_numpy() * units.kelvin

    # Calculate saturation vapor pressure (Pa)
    esat = saturation_vapor_pressure(T)

    # Vapor pressure (Pa)
    e = RH * esat

    # Absolute humidity: AH = e / (R_v * T)
    R_v = 461.5 * units.joule / (units.kilogram * units.kelvin)
    AH = e / (R_v * T)

    return AH.magnitude  # returns kg/m³

def compute_esat(T_C_array):
    """Compute saturation vapor pressure from Celsius temperatures (pandas Series or NumPy array)."""
    T_kelvin = (T_C_array.to_numpy() + 273.15) * units.kelvin  # ✅ Use numpy array
    esat = saturation_vapor_pressure(T_kelvin).to('Pa').magnitude  # Return float array
    return esat

#def rh2ah(RH,p,T):
#   '''conversion relative humidity to absolute humidity (kg Water per m^3 Air)'''
#   mixr=meteo.humidity.rh2mixr(RH, p,T)
#   sh=meteo.humidity.mixr2sh(mixr)
#   return  sh*meteo.air.rhov(T,p)

        
def create_lockfile(Forcing_path):
    lockfile = os.path.join(Forcing_path, ".lockfile")
    if os.path.exists(lockfile):
        raise FileExistsError(f"Error: A lockfile already exists in {Forcing_path}. Delete it before re-running.")
    with open(lockfile, "w") as f:
        f.write("LOCKED")

################ Write forcing and Params_config file in ascii  ##############################3
################ Write forcing and Params_config file in ascii  ##############################3

def write_forcing_ascii(Forcing_vars, Forcing_path, Station_forcing, run_start, run_end, 
                        delta_t, lon, lat, elev, height_T, height_V, write_forcing='yes'):
    """
    Writes forcing variable files and a Params_config.txt metadata file for a simulation run.

    Args:
        Forcing_vars (list): List of forcing variable names.
        Forcing_path (str): Path to save the forcing files.
        Station_forcing (DataFrame): Dataframe containing forcing data.
        run_start (str): Start time index for data selection.
        run_end (str): End time index for data selection.
        delta_t (float): Time step (seconds).
        lon (float): Longitude of the station.
        lat (float): Latitude of the station.
        elev (float): Altitude of the station.
        height_T (float): Temperature measurement height.
        height_V (float): Wind measurement height.
        write_forcing (str, optional): Whether to write output files ('yes' to write). Default is 'yes'.

    Returns:
        None
    """    
    os.makedirs(Forcing_path, exist_ok=True)
    lockfile = os.path.join(Forcing_path, ".lockfile")
    if write_forcing.lower() == 'yes':
        if os.path.exists(lockfile):
            raise FileExistsError(f"Error: A lockfile exists in {Forcing_path}. Delete the lockfile before re-running.")
        create_lockfile(Forcing_path)
    
    try:
        Station_forcing_run = Station_forcing[
          (Station_forcing["valid_dttm"] >= run_start) &
          (Station_forcing["valid_dttm"] <= run_end)
        ]
        for var in Forcing_vars:
            print(f"{var} with {Station_forcing_run[var].isna().sum()} NaNs")
            fig, ax = plt.subplots(figsize=(17, 5))
            Station_forcing_run[var].plot(ax=ax, label=f"{var} no_filter")
            ax.set_ylabel(var)
            plt.legend()
            plt.show()
            if write_forcing.lower() == 'yes':
                np.savetxt(os.path.join(Forcing_path, f"{var}.txt"), 
                           Station_forcing_run[var].bfill().ffill().values, fmt='%.6f')
        
        params_lines = [
            1, len(Station_forcing_run), delta_t,
            Station_forcing_run.valid_dttm[1].year, Station_forcing_run.valid_dttm[1].month,
            Station_forcing_run.valid_dttm[1].day, 3600*Station_forcing_run.valid_dttm[1].hour,
            lon, lat, elev, height_T, height_V
        ]
        
        if write_forcing.lower() == 'yes':
            with open(os.path.join(Forcing_path, "Params_config.txt"), 'w') as f:
                f.write("\n".join(map(str, params_lines)) + "\n")
    except Exception as e:
        print(f"Error encountered: {e}")
        raise


################ Write daily forcing files in netcdf  ##############################
        
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from netCDF4 import Dataset, date2num
from datetime import datetime, timezone, timedelta

def write_forcing_netcdf(Forcing_vars, Forcing_path, Station_forcing, run_start, run_end,
                         delta_t, lon, lat, elev, height_T, height_V, write_forcing='yes'):
    """
    Writes daily forcing NetCDF files (FORCING.nc_YYYYMMDD) with time measured as
    seconds since 2014-01-01 00:00:00 UTC. All missing values are forward/backward filled.
    """
    os.makedirs(Forcing_path, exist_ok=True)
    existing_files = set()
    time_range = pd.date_range(run_start, run_end, freq="D")

    for date in time_range:
        forcing_filename = os.path.join(Forcing_path, f"FORCING.nc_{date.strftime('%Y%m%d')}")
        if os.path.exists(forcing_filename):
            existing_files.add(forcing_filename)

    if write_forcing.lower() == 'yes' and existing_files:
        raise FileExistsError(
            f"Error: Existing forcing files would be overwritten: {existing_files}. "
            "Delete them before re-running."
        )

    try:
        # Extract time subset
        Station_forcing_run = Station_forcing[
            (Station_forcing["valid_dttm"] >= run_start) &
            (Station_forcing["valid_dttm"] <= run_end)
        ].copy()

        # Fill missing values globally
        Station_forcing_run[Forcing_vars] = (
            Station_forcing_run[Forcing_vars]
            .bfill()
            .ffill()
        )

        forcing_vars = [
            "CO2air", "Wind_DIR", "PSurf", "Rainf", "Snowf", "Wind",
            "DIR_SWdown", "LWdown", "Qair", "SCA_SWdown", "Tair"
        ]
        forcing_var_map = dict(zip(Forcing_vars, forcing_vars))

        # Plot diagnostic (optional)
        for forcing_key in Forcing_vars:
            print(f"{forcing_key} with {Station_forcing_run[forcing_key].isna().sum()} NaNs after filling")
            fig, ax = plt.subplots(figsize=(17, 5))
            Station_forcing_run[forcing_key].plot(ax=ax, label=f"{forcing_key} (filled)")
            ax.set_ylabel(forcing_key)
            plt.legend()
            plt.show()

        # Time origin (fixed)
        origin_utc = datetime(2014, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        for date in time_range:
            daily_data = Station_forcing_run[
                Station_forcing_run["valid_dttm"].dt.date == date.date()
            ]

            if daily_data.empty:
                print(f"⚠️ No data for {date.strftime('%Y-%m-%d')}, skipping.")
                continue

            nsteps = daily_data.shape[0]
            first_ts = pd.Timestamp(daily_data["valid_dttm"].iloc[0]).tz_convert("UTC")

            # Compute elapsed seconds since origin
            base_seconds = (first_ts - origin_utc).total_seconds()
            time_seconds = base_seconds + np.arange(nsteps) * delta_t

            # Time-aware datetimes
            time_values = [origin_utc + timedelta(seconds=s) for s in time_seconds]

            # Sanity check on Δt
            secs = np.array([int((dt - origin_utc).total_seconds()) for dt in time_values])
            unique_deltas = np.unique(np.diff(secs))
            print(f"Δt unique values for {date.strftime('%Y-%m-%d')}: {unique_deltas}")

            expected_steps = int(86400 / delta_t)
            if nsteps != expected_steps:
                print(f"⚠️ Expected {expected_steps} timesteps, got {nsteps} on {date.date()}")

            forcing_filename = os.path.join(Forcing_path, f"FORCING.nc_{date.strftime('%Y%m%d')}")

            # === Write NetCDF ===
            with Dataset(forcing_filename, "w", format="NETCDF4") as nc:
                nc.createDimension("time", len(time_values))
                nc.createDimension("Number_of_points", 1)

                # Time variable
                time_var = nc.createVariable("time", "f8", ("time",))
                time_var.units = "seconds since 2014-01-01 00:00:00"
                time_var.calendar = "gregorian"
                time_var[:] = date2num(time_values, units=time_var.units, calendar="gregorian")

                # Static/meta variables
                meta_vars = {
                    "FRC_TIME_STP": ("Forcing_Time_Step", delta_t, None),
                    "LON": ("Longitude", lon, "Number_of_points"),
                    "LAT": ("Latitude", lat, "Number_of_points"),
                    "ZS": ("Surface_Orography", elev, "Number_of_points"),
                    "ZREF": ("Reference_Height", height_T, "Number_of_points"),
                    "UREF": ("Reference_Height_for_Wind", height_V, "Number_of_points"),
                }

                for var_name, (long_name, value, dim) in meta_vars.items():
                    var = nc.createVariable(var_name, "f4", (dim,) if dim else ())
                    var.long_name = long_name
                    if var_name in ["ZREF", "UREF"]:
                        var.units = "m"
                    var[...] = value

                # Forcing variables
                attr_map = {
                    "Tair": ("Near_Surface_Air_Temperature", "2m", "K"),
                    "Qair": ("Near_Surface_Specific_Humidity", "2m", "Kg/Kg"),
                    "PSurf": ("Surface_Pressure", "2m", "Pa"),
                    "DIR_SWdown": ("Surface_Indicent_Direct_Shortwave_Radiation", None, "W/m2"),
                    "SCA_SWdown": ("Surface_Incident_Diffuse_Shortwave_Radiation", None, "W/m2"),
                    "LWdown": ("Surface_Incident_Longwave_Radiation", None, "W/m2"),
                    "Rainf": ("Rainfall_Rate", None, "Kg/m2/s"),
                    "Snowf": ("Snowfall_Rate", None, "Kg/m2/s"),
                    "Wind": ("Wind_Speed", None, "m/s"),
                    "Wind_DIR": ("Wind_Direction", None, "deg"),
                    "CO2air": ("Near_Surface_CO2_Concentration", None, "Kg/m3"),
                }

                forcing_data_vars = {}
                for var in forcing_vars:
                    forcing_data_vars[var] = nc.createVariable(
                        var, "f4", ("time", "Number_of_points"), fill_value=np.nan
                    )

                for var_name, (long_name, height, unit) in attr_map.items():
                    var = forcing_data_vars[var_name]
                    var.long_name = long_name
                    if height:
                        var.measurement_height = height
                    var.units = unit

                if write_forcing.lower() == 'yes':
                    for forcing_key, nc_var in forcing_var_map.items():
                        forcing_data_vars[nc_var][:] = (
                            daily_data[forcing_key]
                            .bfill()
                            .ffill()
                            .values.reshape(len(time_values), 1)
                        )

            print(f"✅ Wrote {forcing_filename}")

    except Exception as e:
        print(f"❌ Error encountered: {e}")
        raise


################ Merge netcdf files for a period which is already downloaded as daily files #############
'''
def merge_forcing_netcdf(Forcing_path, start_date, end_date, output_filename="FORCING.nc"):
    """
    Merges daily NetCDF forcing files into a single file with the correct structure.
    """
    merged_filepath = os.path.join(Forcing_path, output_filename)
    
    # Generate list of daily forcing files to merge
    time_range = pd.date_range(start_date, end_date, freq="D")
    forcing_files = [os.path.join(Forcing_path, f"FORCING.nc_{date.strftime('%Y%m%d')}") for date in time_range]
    forcing_files = [f for f in forcing_files if os.path.exists(f)]
    
    if not forcing_files:
        raise FileNotFoundError("No forcing files found for the specified date range.")
    
    # Read first file to get metadata
    with Dataset(forcing_files[0], "r") as sample_nc:
        forcing_vars = [var for var in sample_nc.variables if var not in ["time", "Number_of_points", "FRC_TIME_STP", "LON", "LAT", "ZS", "ZREF", "UREF"]]
        static_vars = [var for var in sample_nc.variables if var in ["FRC_TIME_STP", "LON", "LAT", "ZS", "ZREF", "UREF"]]
    
    # Initialize storage
    merged_data = {var: [] for var in forcing_vars}
    merged_time = []
    static_data = {}
    
    for file in forcing_files:
        with Dataset(file, "r") as nc:
            merged_time.extend(nc.variables["time"][...])
            for var in forcing_vars:
                merged_data[var].append(nc.variables[var][...])
            if not static_data:
                for var in static_vars:
                    static_data[var] = nc.variables[var][...]
    
    # Concatenate data along the time dimension
    for var in forcing_vars:
        print(f"Variable: {var}, Data: {merged_data[var]}")
        merged_data[var] = np.concatenate(merged_data[var], axis=0)
    
    # Write merged data to new NetCDF file
    with Dataset(merged_filepath, "w", format="NETCDF4") as nc:
        nc.createDimension("time", len(merged_time))
        nc.createDimension("Number_of_points", 1)
        
        # Create time variable
        time_var = nc.createVariable("time", "f8", ("time",))
        time_var.units = "seconds since 2014-01-01 00:00:00"
        time_var[:] = merged_time
        
        # Create static variables
        for var, data in static_data.items():
            nc_var = nc.createVariable(var, "f4", ("Number_of_points",))
            nc_var.long_name = var.replace("_", " ")
            nc_var[:] = data
        
        # Create forcing variables
        for var in forcing_vars:
            nc_var = nc.createVariable(var, "f4", ("time", "Number_of_points"))
            nc_var.long_name = var.replace("_", " ")
            nc_var[:] = merged_data[var]
    
    print(f"Merged NetCDF file created: {merged_filepath}")
'''

def merge_forcing_netcdf(Forcing_path, start_date, end_date, output_filename="FORCING.nc"):
    """
    Merges daily NetCDF forcing files into a single file with the correct structure.
    Preserves the original timestamps exactly (no recomputation, no rounding drift).
    """

    merged_filepath = os.path.join(Forcing_path, output_filename)

    # List daily files to merge
    time_range = pd.date_range(start_date, end_date, freq="D")
    forcing_files = [
        os.path.join(Forcing_path, f"FORCING.nc_{date.strftime('%Y%m%d')}")
        for date in time_range
    ]
    forcing_files = [f for f in forcing_files if os.path.exists(f)]
    if not forcing_files:
        raise FileNotFoundError("No forcing files found for the specified date range.")

    print(f"🔗 Merging {len(forcing_files)} daily forcing files...")

    # Inspect first file
    with Dataset(forcing_files[0], "r") as sample_nc:
        forcing_vars = [
            v for v in sample_nc.variables
            if v not in ["time", "Number_of_points", "FRC_TIME_STP", "LON", "LAT", "ZS", "ZREF", "UREF"]
        ]
        static_vars = ["FRC_TIME_STP", "LON", "LAT", "ZS", "ZREF", "UREF"]
        time_units = sample_nc.variables["time"].units
        time_dtype = sample_nc.variables["time"].datatype  # <- keep original dtype (likely float32)

    merged_data = {v: [] for v in forcing_vars}
    merged_time = []
    static_data = {}

    # Read all data preserving dtype exactly
    for file in forcing_files:
        with Dataset(file, "r") as nc:
            time_var = nc.variables["time"]
            time_vals = time_var[:].copy()  # exact dtype from file (usually float32)
            merged_time.append(time_vals)

            for var in forcing_vars:
                merged_data[var].append(nc.variables[var][:])

            if not static_data:
                for var in static_vars:
                    static_data[var] = nc.variables[var][:]

    # Concatenate directly without dtype casting
    merged_time = np.concatenate(merged_time)  # keeps float32 if that was source dtype
    for var in forcing_vars:
        merged_data[var] = np.concatenate(merged_data[var], axis=0)

    print(f"✅ Total timesteps merged: {len(merged_time)}")

    # Write output NetCDF
    with Dataset(merged_filepath, "w", format="NETCDF4") as nc:
        nc.createDimension("time", len(merged_time))
        nc.createDimension("Number_of_points", 1)

        # Create time variable with the same dtype as in the original files
        time_var = nc.createVariable("time", time_dtype, ("time",))
        time_var.units = time_units
        time_var[:] = merged_time  # bit-exact copy

        # Static vars
        for var, data in static_data.items():
            nc_var = nc.createVariable(var, data.dtype.str[1:], ("Number_of_points",))
            nc_var.long_name = var.replace("_", " ")
            nc_var[:] = data

        # Forcing vars
        for var in forcing_vars:
            first_dtype = merged_data[var][0].dtype if isinstance(merged_data[var], list) else merged_data[var].dtype
            nc_var = nc.createVariable(var, first_dtype.str[1:], ("time", "Number_of_points"))
            nc_var.long_name = var.replace("_", " ")
            nc_var[:] = merged_data[var]

    print(f"🎉 Merged NetCDF file created successfully: {merged_filepath}")

    # Check step spacing quickly
    diffs = np.diff(merged_time.astype("float64"))
    print(f"Δt mean = {np.mean(diffs):.6f} s, unique Δt values: {np.unique(np.round(diffs, 5))}")


def process_data(df, variable_map, station_info, start, end, transform_map=None, timedelta_minutes=None):
    df['valid_dttm'] = pd.to_datetime(df['TIMESTAMP'], utc=True)
    df = df[(df['valid_dttm'] >= start) & (df['valid_dttm'] <= end)].copy()

    source_vars = list(variable_map.values())
    df = df.dropna(subset=source_vars)

    df['SID'] = station_info['SID']
    df['lat'] = station_info['lat']
    df['lon'] = station_info['lon']
    df['elev'] = station_info['elev']

    # Rename columns
    df = df.rename(columns={v: k for k, v in variable_map.items()})

    # Apply transformations
    if transform_map:
        for target_var, expr in transform_map.items():
            # Replace "timedelta" in expression with numeric value (in minutes)
            safe_expr = expr.replace("timedelta", str(timedelta_minutes))
            try:
                df[target_var] = df.eval(f"{target_var} {safe_expr}")
            except Exception as e:
                raise RuntimeError(f"Error applying transformation for {target_var}: {expr}\n{e}")

    selected_columns = ['valid_dttm', 'SID', 'lat', 'lon', 'elev'] + list(variable_map.keys())
    return df[selected_columns]


def fetch_flux_data(doi):
    dobj = Dobj(doi)
    df = dobj.data
    return df

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

def parse_variable_entry(entry_str, timedelta_minutes):
    if entry_str is None or entry_str.strip() == "":
        return None, "const", 0.0

    parts = [p.strip() for p in entry_str.split(",", maxsplit=1)]

    # Case: constant only
    if len(parts) == 1:
        val = parts[0]
        if val in ["-", "None", ""]:
            return None, "zero", 0.0
        try:
            return None, "const", float(val)
        except ValueError:
            return val, None, None  # just a direct mapping

    # Case: transformation
    src, transform = parts
    if src in ["-", "None", ""]:
        try:
            return None, "const", float(transform)
        except ValueError:
            raise ValueError(f"Invalid constant value in entry: {entry_str}")

    if "timedelta" in transform:
        transform = transform.replace("timedelta", str(timedelta_minutes))

    op = transform[0]
    expr = transform[1:].strip()

    try:
        val = eval(expr, {}, {})  # safe eval of math expression
    except Exception as e:
        raise ValueError(f"Failed to evaluate expression '{expr}' in entry '{entry_str}': {e}")

    return src, op, val



def apply_transformation(series, op, val):
    if op == "+":
        return series + val
    elif op == "-":
        return series - val
    elif op == "*":
        return series * val
    elif op == "/":
        return series / val
    else:
        return series  # No op


# In[ ]:


###### OSVAS #####################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)########################
#### STEP 1.2: LOAD STATION METADATA AND CONFIGURATION OF  #########
#### THE FORCING GENERATION FROM THE STATION'S YAML FILE #########

#3.1 Read YAML config for station, define paths, set Station,
#    get station metadata

write_forcing='yes' #Set to yes to write forcing
CONFIG_PATH = os.path.join(OSVAS, "config_files", "Stations", f"{Station_name}.yml")

with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)

station_info = config["Station_metadata"]
forcing_data = config["Forcing_data"]
lon=config["Station_metadata"]["lon"]
lat=config["Station_metadata"]["lat"]
elev=config["Station_metadata"]["elev"]
height_T=forcing_data["height_T"]
height_V=forcing_data["height_V"]
forcing_format = forcing_data["forcing_format"]

start_date = pd.to_datetime(forcing_data["run_start"], utc=True)
end_date = pd.to_datetime(forcing_data["run_end"], utc=True)

# Surfex vegetation types : 
#1: no vegetation (smooth) - NO    2: no vegetation (rocks) - ROCK    3: permanent snow and ice - SNOW
#4: temperate broadleaf cold-deciduous summergreen - TEBD    5: boreal needleleaf evergreen - BONE
#6: tropical broadleaf evergreen - EVER    7: C3 cultures types - C3    8: C4 cultures types - C4
#9: irrigated crops - IRR10: grassland (C3) - GRAS     11: tropical grassland (C4) - TROG
#12: peat bogs, parks and gardens (irrigated grass) - PARK     13: tropical broadleaf deciduous - TRBD
#14: temperate broadleaf evergreen - TEBE     15: temperate needleleaf evergreen - TENE
#16: boreal broadleaf cold-deciduous summergreen - BOBD    17: boreal needleleaf cold-deciduous summergreen - BOND
#18: boreal grass - BOGR    19: shrub - SHRB

###### OSVAS ###################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)######
#### STEP 1.3: ICOS AUTHENTICATION ###############

# More info : https://icos-carbon-portal.github.io/pylib//icoscp/authentication/

# There are several ways to authenticate yourself into ICOS
# In the example below, the temporal API token is used, which is available 
# at the bottom of https://cpauth.icos-cp.eu/home/ after you authenticate
# into the portal. The token lasts for 100.000 seconds, ~28 hours.

# Authenticate using cookie (adjust if needed)
cookie_path = os.path.join(OSVAS,"icos_cookie.txt")  # Or point to config
cookie_token = open(cookie_path, "r").readline().strip()
meta, data = bootstrap.fromCookieToken(cookie_token)
cpauth.init_by(data.auth)

#Test: If the authentication went well, these lines of code will not fail:
import icoscp
from icoscp.dobj import Dobj
obj_flux='https://meta.icos-cp.eu/objects/dDlpnhS3XKyZjB22MUzP_nAm'
dobj_flux=Dobj(obj_flux).data


# In[ ]:


###### OSVAS #####################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)########################
#### STEP 1.4: LOAD STATION DATA, READ VARIABLES ###############
#### TRANSFORM TO UNITS USED BY SURFEX ######################################


#Read all datasets from the Forcing_data section of the yaml file,
#loop over datasets to get all forcing variables, abort if no data in range
dfs = []
timedeltas = []
datasets = {k: v for k, v in forcing_data.items() if k.startswith("dataset") or k.startswith("dataset_")}

for ds_name, ds_info in datasets.items():
    print(f"Processing {ds_name} from DOI: {ds_info['doi']}")
    doi = ds_info["doi"]
    timedelta_minutes = ds_info["timedelta"]
    timedeltas.append(timedelta_minutes)

    variable_map_raw = ds_info["variables"]

    df_raw = fetch_flux_data(doi)
    df_raw['valid_dttm'] = pd.to_datetime(df_raw['TIMESTAMP'], utc=True)
    df_raw = df_raw[(df_raw['valid_dttm'] >= start_date) & (df_raw['valid_dttm'] <= end_date)].copy()

    if df_raw.empty:
        raise RuntimeError(
            f"❌ No data found in the time window ({start_date} to {end_date}) "
            f"for dataset {ds_name} (DOI: {doi}). Aborting."
        )

    df_processed = pd.DataFrame()
    df_processed['valid_dttm'] = df_raw['valid_dttm'].copy()
    df_processed['SID'] = station_info['SID']
    df_processed['lat'] = station_info['lat']
    df_processed['lon'] = station_info['lon']
    df_processed['elev'] = station_info['elev']

    for target_var, entry in variable_map_raw.items():
        src, op, val = parse_variable_entry(entry, timedelta_minutes)
    
        if src is None:
            if op == "zero":
                df_processed[target_var] = 0.0
            elif op == "const":
                df_processed[target_var] = val
            else:
                raise ValueError(f"Unknown operation {op} for {target_var}")
        else:
            if op is None:
                df_processed[target_var] = df_raw[src].values
            elif op == "+":
                df_processed[target_var] = df_raw[src] + val
            elif op == "-":
                df_processed[target_var] = df_raw[src] - val
            elif op == "*":
                df_processed[target_var] = df_raw[src] * val
            elif op == "/":
                df_processed[target_var] = df_raw[src] / val
            else:
                raise ValueError(f"Unknown transformation operator {op}")
    dfs.append(df_processed)

#  Harmonize resolution
common_td = pd.to_timedelta(min(timedeltas), unit="m")  # Choose finest resolution
dfs_resampled = upsample_to_common_timedelta(datasets, dfs, common_td)

#  Merge all datasets
from functools import reduce
Station_forcing = reduce(lambda left, right: pd.merge(left, right, on=['valid_dttm', 'SID', 'lat', 'lon', 'elev'], how='outer'), dfs_resampled)
Station_forcing = Station_forcing.sort_values("valid_dttm").reset_index(drop=True)

#  Compute Forc_QA from ICOS RH or VPD variables if needed:

# Step 1: If Forc_RH doesn't exist, compute it from Forc_VPD (if available)
if "Forc_RH" not in Station_forcing.columns and "Forc_VPD" in Station_forcing.columns:
    esat = compute_esat(Station_forcing["Forc_TA"])
    df["Forc_RH"] = 100 * (esat - Station_forcing["Forc_VPD"]) / esat

# Step 2: If Forc_QA is full of zeros, compute it from Forc_RH, Forc_PS, and Forc_TA
if "Forc_QA" in Station_forcing.columns and np.all(Station_forcing["Forc_QA"] == 0):
    required_cols = ["Forc_RH", "Forc_PS", "Forc_TA"]
    if all(col in Station_forcing.columns for col in required_cols):
        # Create a valid mask for non-NaN and physically reasonable values
        valid_mask = (
            Station_forcing["Forc_RH"].between(0, 100) &
            Station_forcing["Forc_PS"].between(1e3, 1.2e5) &  # Pressure between 1kPa and 120kPa
            Station_forcing["Forc_TA"].between(150, 330) &    # Temp between -123°C and 57°C
            Station_forcing[["Forc_RH", "Forc_PS", "Forc_TA"]].notnull().all(axis=1)
        )

        if valid_mask.any():
            Station_forcing.loc[valid_mask, "Forc_QA"] = rh2sh(
                Station_forcing.loc[valid_mask, "Forc_RH"] / 100,
                Station_forcing.loc[valid_mask, "Forc_PS"],
                Station_forcing.loc[valid_mask, "Forc_TA"]
            )
        else:
            print("No valid rows to compute Forc_QA.")
    else:
        print("Cannot compute Forc_QA: missing Forc_RH, Forc_PS, or Forc_TA")

# Step 3: Set negative Forc_DIR_SW values to zero
if "Forc_DIR_SW" in Station_forcing.columns:
    neg_count = (Station_forcing["Forc_DIR_SW"] < 0).sum()
    if neg_count > 0:
        print(f"Setting {neg_count} negative Forc_DIR_SW values to zero.")
        Station_forcing.loc[Station_forcing["Forc_DIR_SW"] < 0, "Forc_DIR_SW"] = 0
# Step 4: Compute wet-bulb temperature Tw2m and split precipitation ---

required_cols = ["Forc_TA", "Forc_RH", "Forc_RAIN"]
if all(col in Station_forcing.columns for col in required_cols):

    T2m = Station_forcing["Forc_TA"]
    RH2m = Station_forcing["Forc_RH"]

    # Avoid NaN or impossible humidity
    valid = RH2m.notna() & T2m.notna()

    if valid.any():
        # Compute wet-bulb temperature Tw2m (°C) using given formula
        Tw2m = (
            (T2m-273.15) * np.arctan(0.151977 * np.sqrt(RH2m + 8.313659))
            + 0.00391838 * np.sqrt(RH2m ** 3) * np.arctan(0.023101 * RH2m)
            - np.arctan(RH2m - 1.676331)
            + np.arctan(T2m-273.15 + RH2m)
            - 4.686035
        )

        Station_forcing["Forc_Tw2m"] = Tw2m

        # Initialize Snow column if missing
        if "Forc_Snow" not in Station_forcing.columns:
            Station_forcing["Forc_Snow"] = 0.0

        # Rows where temperature is at or below freezing → all precip becomes snow
        snow_mask = valid & (Tw2m <= 0)

        if snow_mask.any():
            # Move liquid precip (Forc_RAIN) to Forc_Snow
            Station_forcing.loc[snow_mask, "Forc_Snow"] += Station_forcing.loc[snow_mask, "Forc_RAIN"]
            Station_forcing.loc[snow_mask, "Forc_RAIN"] = 0.0

            print(f"Converted {snow_mask.sum()} precipitation records to snowfall based on Tw2m ≤ 0°C.")
    else:
        print("Wet-bulb temperature calculation skipped: no valid TA/RH rows.")
else:
    print("Cannot compute wet-bulb temperature or split precipitation: missing Forc_TA, Forc_RH, or Forc_RAIN.")



# In[ ]:


###### OSVAS ####################################################
###### ( OFFLINE SURFEX VALIDATION SYSTEM)#######################
#### STEP 1.5: PLOT FORCING VARIABLES FOR THE SELECTED PERIOD #####
#### WRITE THE FORCING FILES IN THE SELECTED FILE TYPE ##########


Forcing_vars=['Forc_CO2','Forc_DIR','Forc_PS','Forc_RAIN','Forc_SNOW','Forc_WIND','Forc_DIR_SW','Forc_LW','Forc_QA','Forc_SCA_SW','Forc_TA']
Forcing_path=os.path.join(OSVAS,'forcings',Station_name)
write_forcing='yes' #Set to yes for writing forcing
print(f"Writing forcing data in {forcing_format} format")
if forcing_format=='ascii':
    write_forcing_ascii(
    Forcing_vars=Forcing_vars, 
    Forcing_path=Forcing_path,
    Station_forcing=Station_forcing, 
    run_start=start_date, 
    run_end=end_date, 
    delta_t=common_td.seconds, 
    lon=lon, lat=lat, elev=elev, 
    height_T=height_T, height_V=height_V,
    write_forcing=write_forcing
    )
    
if forcing_format=='netcdf':
    write_forcing_netcdf(
    Forcing_vars=Forcing_vars, 
    Forcing_path=Forcing_path,
    Station_forcing=Station_forcing, 
    run_start=start_date, 
    run_end=end_date, 
    delta_t=common_td.seconds, 
    lon=lon, lat=lat, elev=elev, 
    height_T=height_T, height_V=height_V,
    write_forcing=write_forcing
    )

#Construct single forcing file for a period from the individual netcdf files
if forcing_format=='netcdf':
    merge_forcing_netcdf(Forcing_path=Forcing_path,start_date=start_date, end_date=end_date, output_filename="FORCING.nc")


#### Example on how to reconstruct a forcing file for a period from the individual netcdf files
#run_start='2016-5-1 00:00:00'    # Timestamp for the forcing start
#run_end='2016-7-1 00:00:00'  
#run_start='2018-6-1 00:00:00'    # Timestamp for the forcing start
#run_end='2022-6-6 00:00:00' 
#merge_forcing_netcdf(Forcing_path=Forcing_path,start_date=run_start, end_date=run_end, output_filename="FORCING.nc")


# In[ ]:





# In[ ]:


dfs


# In[ ]:


Station_forcing["Forc_TA"]


# In[ ]:




