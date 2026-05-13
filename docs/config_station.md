## Station Configuration (YAML)
OSVAS station configuration is defined in `config_files/Stations/${STATION_NAME}/${STATION_NAME}.yml`.
The YAML controls workflow execution, data sources, station metadata, and soil initialization behavior.

### OSVAS_steps block
Controls which workflow steps execute and what experiments to run:

```yaml
OSVAS_steps:
  Create_forcing: true/false        # Step 1: Generate forcing from ICOS data
  Get_validation: true/false        # Step 2: Download validation data
  Run_surfex: true/false            # Step 3: Run SURFEX simulations
  Extract_model_sqlites: true/false # Step 4: Convert outputs to SQLite
  Run_HARP: true/false              # Step 5: Run HARP verification
  Display_HARP: true/false          # Step 6: Display verification results
  Expnames:                         # List of experiment names to run. For each one, a namelist
    - MEBREFOL                      # is expected at $OSVAS/namelists/$STATION_NAME/OPTIONS.nam_$EXPNAME
    - DIFMEB
  Surfex_steps:                     # SURFEX steps to execute in order
    - pgd
    - PREP
    - OFFLINE
```

### Station_metadata block
Station information for model output and verification:

```yaml
Station_metadata:
  Station_type: ICOS                 # Station type identifier
  Station_name: Majadas_del_tietar   # Human-readable station name
  SID: 4300000005                    # ICOS Station ID (must match validation data)
  elev: 265.0                        # Elevation (meters)
  lat: 39.94033                      # Latitude (decimal degrees)
  lon: -5.77465                      # Longitude (decimal degrees)
  vegtype: 19                        # SURFEX vegetation type (integer)
  lai: 1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0  # Leaf Area Index by month. Merge into PREP or namelist not yet implemented
  closure_type: 1                    # SEB closure type. Option currently not activated.
```

The `SID` is defined for each new station in  `$OSVAS/sqlites/station_list_SURFEX.csv`.

### Forcing_data block
Defines ICOS datasets for generating SURFEX forcing:

```yaml
Forcing_data:
  height_T: 2                        # Temperature measurement height (meters)
  height_V: 10                       # Wind speed measurement height (meters)
  run_start: '2021-05-01 00:00:00'   # Forcing period start (YYYY-MM-DD HH:MM:SS)
  run_end: '2021-07-01 23:30:00'     # Forcing period end
  forcing_format: 'ascii'            # Output format: 'ascii' or 'netcdf'
  dataset1:
    doi: https://meta.icos-cp.eu/objects/...  # ICOS dataset DOI
    timedelta: 30                    # Time step (minutes)
    variables:                       # Variable mapping and transformations
      Forc_TA: TA, +273.15           # Convert to Kelvin
      Forc_PS: PA, *1000             # Convert to Pa
      Forc_RAIN: P, /(timedelta*60)  # Convert to rate
      Forc_WIND: WS                  # Pass through
    units:                           # Optional: specify units for validation
      Forc_TA: K
      Forc_PS: Pa
```

**Variable transformations:**
- `+`, `-`, `*`, `/` for arithmetic: `TA, +273.15` adds 273.15
- `timedelta` is automatically substituted with the dataset's time step


### Validation_data block
Defines ICOS datasets for validation and soil initialization:

```yaml
Validation_data:
  validation_start: '2021-05-01 00:00:00'   # Validation period start
  validation_end: '2021-07-01 23:30:00'     # Validation period end
  common_obstable: false             # Write to common directory for cross-site comparison
  common_fctable: false              # Use common FCTABLE directory for shared experiments
  dataset1:
    doi: https://meta.icos-cp.eu/objects/...
    timedelta: 30
    variables:                       # Map ICOS variables to observation names
      SW_OUT: SW_OUT
      TS_1: TS_1
      SWC_1: SWC_1
    units:                           # Observation data units (for conversion)
      SW_OUT: W/m2
      TS_1: degC
      SWC_1: percent
  dataset2:
    # Additional dataset for energy fluxes...
```
- Wildcard variables: `TS_*`, `SWC_*` expand to all matching ICOS variables

**Cross-site comparison:**
- `common_obstable: true` — Writes validation SQLites to `sqlites/OBSTABLES/validation_data/common_obstables/` (shared across stations)
- `common_fctable: true` — Writes model SQLites to `sqlites/FCTABLES/common_fctables/` (shared across stations running the same experiment)

When enabled, multiple stations can contribute to the same OBSTABLE/FCTABLE files, identified by their `SID`, enabling cross-site verification of identical experiment configurations.

### Initialization_data block
Controls soil initialization derived from validation or station metadata:

```yaml
Initialization_data:
  metadata_filename: 'ICOSETC_ES-LMa_VARINFO_METEO_L2.csv'  # ICOS metadata CSV stored in config_files/Stations/$STATION_NAME/. Used to read instruments depths automatically
  reuse_soil_profile: false          # Reuse previously computed profiles if available
  Init_to_namelist: true             # Patch OPTIONS.nam before SURFEX run
  Init_to_prep: false                # Patch PREP files after PREP step
  soil_depths_ts: [0.05, 0.1, 0.2, 0.3, 0.4]   # Soil temperature obs depths (m)
  soil_depths_swc: [0.05, 0.1, 0.2, 0.3, 0.4]  # Soil moisture obs depths (m)
```

Soil initialization profiles are computed from validation data and stored as NumPy arrays in `profiles/{$STATION_NAME}/`:
- `tg_profile.npy` — Soil temperature profiles (K) at specified depths
- `hug_profile.npy` — Soil humidity profiles

**When initialization is used:**
1. Step 2 computes profiles from validation data and saves them to `profiles/{$STATION_NAME}/`
2. Step 3 applies these profiles to the SURFEX run based on flags:
   - `Init_to_namelist: true` — Modifies `OPTIONS.nam` before running PGD/PREP/OFFLINE
   - `Init_to_prep: true` — Modifies `PREP.nc`/`PREP.txt` after PREP completes

### Creating a new station configuration
To add a new ICOS station:

1. Create the directory: `config_files/Stations/{NEW_STATION_NAME}/`
2. Create the YAML file: `config_files/Stations/{NEW_STATION_NAME}/{NEW_STATION_NAME}.yml`
3. Add the station to `sqlites/station_list_SURFEX.csv` with metadata (SID, name, lat, lon, elev)
4. Create the station's namelist directory: `namelists/{NEW_STATION_NAME}/`
5. Add experiment namelists: `namelists/{NEW_STATION_NAME}/OPTIONS.nam_{EXPNAME}`
6. Optionally: Copy the ICOS metadata file (e.g., `ICOSETC_COUNTRY-CODE_VARINFO_METEO_L2.csv`) from the ICOS portal

Example YAML structure for a minimal station:
```yaml
OSVAS_steps:
  Create_forcing: true
  Get_validation: true
  Run_surfex: false
  Extract_model_sqlites: false
  Run_HARP: false
  Display_HARP: false
  Expnames:
    - TEST
  Surfex_steps:
    - pgd
    - PREP
    - OFFLINE

Station_metadata:
  Station_type: ICOS
  Station_name: My_Station
  SID: 4300000099       # Must be unique and match station list
  elev: 100.0
  lat: 45.0
  lon: 10.0
  vegtype: 15

Forcing_data:
  height_T: 2
  height_V: 10
  run_start: '2024-05-01 00:00:00'
  run_end: '2024-05-31 23:30:00'
  forcing_format: 'ascii'
  dataset1:
    doi: https://meta.icos-cp.eu/objects/YOUR_DOI_HERE
    timedelta: 30
    variables:
      Forc_TA: TA, +273.15
      Forc_PS: PA, *1000
      Forc_WIND: WS
      # ... add other variables as needed

Validation_data:
  validation_start: '2024-05-01 00:00:00'
  validation_end: '2024-05-31 23:30:00'
  common_obstable: false
  common_fctable: false
  dataset1:
    doi: https://meta.icos-cp.eu/objects/YOUR_VALIDATION_DOI
    timedelta: 30
    variables:
      SW_IN: SW_IN
      SW_OUT: SW_OUT
```
