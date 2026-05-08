## Step 1. Preparation of forcing data 
- A Python notebook (`WRITE_Station_forcing.ipynb`) is executed via the Python workflow launcher. The notebook may be converted on the fly to a `.py` script with `jupyter nbconvert` if `jupyter=True` in the launcher.
- It generates SURFEX forcing files in ASCII or NetCDF format based on the `Forcing_data` block in the station YAML.
- `Forcing_data` specifies ICOS or KNMI datasets, variables, unit conversions, and the simulation period.
``` 
Forcing_data:
  height_T: 2                       # Height of the temperature measurement
  height_V: 10                      # Height of the windspeed   measurement
  run_start: '2021-5-01 00:00:00'    # Timestamp for the forcing start
  run_end: '2021-7-1 23:30:00'      # Timestamp for the forcing end
  forcing_format: 'ascii'          # Choose between netcdf or ascii
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
- Example config files currently available for stations: **Majadas_del_tietar (ES), Meteopole (FR), and Loobos (NL)** (Fluxnet data format, accessible via ICOS Data Portal).
- Available formats:
  - **ASCII format**: Forcings are generated for the entire simulation period.
  - **NetCDF format**: Daily NetCDF files are created, then a merging function in the notebook is used to join daily files in a single FORCING.nc file
- **Sampling rate**: If several datasets with different sampling rates are provided, the data will be upsampled to a common (smallest) timedelta.
- **Lockfile mechanism**: Prevents overwriting of forcing files unless manually deleted.
