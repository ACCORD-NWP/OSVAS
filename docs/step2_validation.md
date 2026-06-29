## Step 2. Download validation data from ICOS specialized stations

### Notebook execution
The Python workflow launcher executes the notebook `Flux_downloader.ipynb` to retrieve and process validation data. Like Step 1, this notebook can be executed via:

1. **Automatic conversion** (default): The launcher uses `jupyter nbconvert` to convert the notebook to Python and execute it without requiring a Jupyter server.
2. **Direct Python execution**: A pre-converted `Flux_downloader.py` script is available for standalone execution.
3. **Interactive Jupyter**: The notebook can be run manually with `jupyter notebook` or `jupyter lab`.

### Validation data processing
The notebook downloads ICOS flux data and creates OBSTABLE SQLite files for use with HARP or custom verification tools. The process is configured via the `Validation_data` YAML section, which defines:
- ICOS datasets to download using their DOI
- Variable mapping from ICOS to observation variable names
- Unit conversions
- Validation period

**Configuration example:**
```yaml
Validation_data:
  validation_start: '2021-05-01 00:00:00'  # Validation period start
  validation_end: '2021-07-01 23:30:00'    # Validation period end
  common_obstable: false                   # Write to station-specific directory
  common_fctable: false
  dataset1:
    doi: https://meta.icos-cp.eu/objects/fPAqntOb1uiTQ2KI1NS1CHlB  # ICOS dataset DOI
    timedelta: 30                          # Time step (minutes)
    variables:
      SW_OUT: SW_OUT                       # Map ICOS to observation variable names
      LW_OUT: LW_OUT
      SW_IN: SW_IN
      LW_IN: LW_IN
      TS_*: TS_*                           # Wildcard: include all TS_* variables
      SWC_*: SWC_*                         # Wildcard: include all SWC_* variables
    units:
      SW_OUT: W/m2                         # Specify observation units (for conversion)
      LW_OUT: W/m2
      LW_IN: W/m2
      SW_IN: W/m2
      TS_1: degC
      TS_2: degC
      SWC_1: percent
      SWC_2: percent
  dataset2:
    doi: https://meta.icos-cp.eu/objects/V8Wjs15Fj0aDX1xmiNx2zPA-
    timedelta: 30
    variables:
      H: H                                 # Sensible heat
      LE: LE                               # Latent heat flux
    units:
      H: W/m2
      LE: W/m2
```

### Canopy storage and H/LE closure
The station YAML can activate canopy storage estimation and SEB closure correction in `Station_metadata`.

Example:
```yaml
Station_metadata:
  canopy_storage: true
  closure_type: 1
  Tree_height: 21
  cp: 1004.0
  Lv: 2500000.0
  cveg: 2650.0
  rho_veg: 1.67
```
- `canopy_storage: true` enables canopy energy storage estimation when `Tcan` is available in validation data.
- `Tcan` is required; `Qcan` is optional. If `Qcan` is missing, the vapor storage term `S_q` is treated as zero.
- `closure_type: 0` leaves `H` and `LE` unchanged.
- `closure_type: 1`–`3` perform closure by adjusting `H` and `LE` to match available energy using the Bowen ratio.
- `closure_type: 4` includes canopy storage terms (`S_T`, `S_veg`, `S_q`) when solving closure.
- `Tree_height` is required for canopy storage. `cp`, `Lv`, `cveg`, and `rho_veg` are optional station constants with defaults used when absent.

### OBSTABLE output
The notebook creates SQLite files with validation observations in HARP-compatible format:

**Directory structure:**
- Station-specific: `sqlites/OBSTABLES/validation/{STATION_NAME}/`
- Cross-site (if `common_obstable: true`): `sqlites/OBSTABLES/validation/common_obstables/`

**File structure:**
Monthly OBSTABLE files are created, containing observations from all configured datasets for that month.

### Soil initialization profiles
If `Initialization_data` is configured in the station YAML, the notebook can compute soil temperature and humidity profiles from validation data for use in SURFEX initialization:

```yaml
Initialization_data:
  metadata_filename: 'ICOSETC_ES-LMa_VARINFO_METEO_L2.csv'  # ICOS metadata file
  reuse_soil_profile: false        # Reuse previously computed profiles
  Init_to_namelist: true           # Apply profiles to OPTIONS.nam
  Init_to_prep: false              # Apply profiles to PREP files
  soil_depths_ts: [0.05, 0.1, 0.2, 0.3, 0.4]  # Soil temperature depths (m)
  soil_depths_swc: [0.05, 0.1, 0.2, 0.3, 0.4] # Soil moisture depths (m)
```

When this block is present, the notebook:
1. Reads the ICOS metadata file to locate soil observations at the specified depths
2. Extracts soil temperature (TS_*) and moisture (SWC_*) profiles from validation data
3. Saves profiles as NumPy arrays: `profiles/{STATION_NAME}/tg_profile.npy` and `hug_profile.npy`

These profiles are then applied by Step 3 when `Init_to_namelist` or `Init_to_prep` is enabled.

Soil depths are derived with the following priority:
    1. Explicit lists in YAML:
           Initialization_data.soil_depths_ts   (for TS)
           Initialization_data.soil_depths_swc  (for SWC)
       If only one generic ``soil_depths`` key is found it is used for both.
    2. ICOS Metadata file defined by Initialization_data.metadata_filename,
       looked up in config_files/{station_name}/. Check [here](docs/ICOS_data.md) to learn how to reach these files for every ICOS station.

### Variable sampling rate
If multiple validation datasets with different sampling rates are provided, all data are upsampled to the finest (smallest) timedelta before creating the OBSTABLE.
