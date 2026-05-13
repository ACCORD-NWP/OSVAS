## Step 1. Preparation of forcing data 

### Notebook execution
The Python workflow launcher executes the notebook `WRITE_Station_forcing.ipynb` to generate SURFEX forcing data. The notebook is executed using one of these methods:

1. **Automatic conversion** (default): The launcher uses `jupyter nbconvert` to convert the notebook to a Python script on-the-fly and executes it. This approach works in environments without a Jupyter server.
2. **Direct Python execution**: A pre-converted `WRITE_Station_forcing.py` script is available and can be executed directly if notebooks are unavailable.
3. **Interactive Jupyter**: The notebook can be manually executed with `jupyter notebook` or `jupyter lab` for development and debugging.

### Forcing data generation
The notebook generates SURFEX forcing files in ASCII or NetCDF format based on the `Forcing_data` block in the station YAML:

```yaml
Forcing_data:
  height_T: 2                       # Height of the temperature measurement (meters)
  height_V: 10                      # Height of the windspeed measurement (meters)
  run_start: '2021-05-01 00:00:00'  # Timestamp for the forcing start
  run_end: '2021-07-01 23:30:00'    # Timestamp for the forcing end
  forcing_format: 'ascii'           # Choose between 'netcdf' or 'ascii'
  dataset1:
    doi: https://meta.icos-cp.eu/objects/fPAqntOb1uiTQ2KI1NS1CHlB
    timedelta: 30  # in minutes
    variables:
      Forc_CO2: -, 0.00062
      Forc_PS: PA, *1000
      Forc_RAIN: P, /(timedelta*60)
      Forc_SNOW:
      Forc_WIND: WS
      Forc_DIR: WD
      Forc_DIR_SW: SW_IN
      Forc_LW: LW_IN
      Forc_QA:
      Forc_SCA_SW:
      Forc_TA: TA, +273.15
      Forc_RH: RH
```

### Output formats

**ASCII format:**
- Forcings are generated for the entire simulation period in a single ASCII file
- Simple columnar format suitable for small domains or single-point models like SURFEX OFFLINE
- File: `forcings/{STATION_NAME}/Forc_*.txt`

**NetCDF format:**
- Daily NetCDF files are created by the notebook
- A merge function combines daily files into a single `FORCING.nc` file
- Files: `forcings/{STATION_NAME}/FORCING.nc` and `forcings/{STATION_NAME}/Forc_*.txt`

### Variable transformations
The `variables` section supports:
- **Pass-through**: `Forc_WIND: WS` — Use the ICOS variable directly
- **Arithmetic**: `Forc_TA: TA, +273.15` — Convert to Kelvin; `Forc_PS: PA, *1000` — Convert to pascals
- **Rate conversion**: `Forc_RAIN: P, /(timedelta*60)` — Convert accumulation to rate (automatically substitutes timedelta value)
- **Wildcards**: `TS_*: TS_*`, `SWC_*: SWC_*` — Expand to all matching ICOS variables
- **Constants**: `Forc_CO2: -, 0.00062` — Use a fixed value

### Sampling rate
If multiple datasets with different sampling rates are provided, all data are upsampled to the finest (smallest) timedelta. For example, if dataset1 has 30-minute data and dataset2 has hourly data, both will be interpolated to 30-minute intervals.

### Lockfile mechanism
A lockfile (`FORCING.lock`) prevents overwriting of existing forcing files. To regenerate forcing data, manually delete the corresponding `.txt` or `.nc` files.
