## Step 2. Download validation data from ICOS specialized stations.
The Python workflow launcher executes `ICOS_Flux_downloader.ipynb` to retrieve validation data and save it as OBSTABLE sqlite files. These sqlite files can be used by HARP or custom verification tools.

The `Validation_data` YAML section defines the datasets, renaming, units, and validation period.
Stations are identified by `SID`, and `common_obstable` controls whether validation data are written to a shared common obstable or a station-specific obstable directory.

A new initialization block can also be defined in the station YAML so that the validation-derived soil temperature and humidity profiles are reused by the SURFEX run.

Example:
```
Validation_data:
  validation_start: '2020-05-01 00:00:00'
  validation_end: '2020-12-31 23:30:00'
  common_obstable: FALSE
  dataset1:
    doi: https://meta.icos-cp.eu/objects/VIoR-cJnMUUjbaEkuNHMKgSv
    timedelta: 30
    variables:
      SW_OUT: SW_OUT
      LW_OUT: LW_OUT
      SW_IN: SW_IN
      LW_IN: LW_IN  
      TS_*: TS_*
      SWC_*: SWC_*
      G: G
    units:
      SW_OUT: W/m2
      LW_OUT: W/m2
      LW_IN: W/m2
      SW_IN: W/m2
      TS_1: degC
      TS_2: degC
      TS_3: degC
      TS_4: degC
      SWC_1: percent
      SWC_2: percent
      SWC_3: percent
      SWC_4: percent
      G: W/m2
```

If `Initialization_data` is present the workflow can also compute soil initialization profiles from the validation metadata and save them for later use in `OPTIONS.nam` or `PREP` files.

The `Initialization_data` block supports keys such as:
- `metadata_filename`
- `reuse_soil_profile`
- `Init_to_namelist`
- `Init_to_prep`
- `soil_depths_ts`
- `soil_depths_swc`

When used, the notebook writes `tg_profile.npy` and `hug_profile.npy` into `profiles/{station}/`, which are later applied by `scripts/python_scripts/apply_soil_initialization.py`.
```
Validation_data:
  validation_start: '2021-5-01 00:00:00'
  validation_end: '2021-7-1 23:30:00'
  common_obstable: FALSE  # Write obs to a common obstable or to a single-station one
  dataset1:
    doi: https://meta.icos-cp.eu/objects/fPAqntOb1uiTQ2KI1NS1CHlB
    timedelta: 30
    variables:
      SW_OUT: SW_OUT
      LW_OUT: LW_OUT
      SW_IN: SW_IN
      LW_IN: LW_IN
      TS_1: TS_1
      TS_2: TS_2
      SWC_1: SWC_1
      SWC_2: SWC_2
    units:  # These should be similar to units attribute in output netcdf files
      SW_OUT: W/m2
      LW_OUT: W/m2
      LW_IN: W/m2
      SW_IN: W/m2
      TS_1: K
      TS_2: K
      SWC_1: m3/m3
      SWC_2: m3/m3
  dataset2:
    doi: https://meta.icos-cp.eu/objects/tONKGY9pOYqVInayCYac-4LI
    timedelta: 30
    variables:
      H: H
      LE: LE
    units:
      H: W/m2
      LE: W/m2
```
- The configuration file above will be treated by `Write_ICOS_forcing.ipynb` to generate forcing files in ascii or netcdf format according to the defined datasets and transformations, and by `ICOS_Flux_downloader.ipynb` to generate a validation dataset from the different ICOS datasets specified in the Validation_data block. 
- **Sampling rate**: If several datasets with different sampling rates are provided, the data will be upsampled to a common (smallest) timedelta.
