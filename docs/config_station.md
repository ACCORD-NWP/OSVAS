## Station Configuration (YAML)
OSVAS station configuration is defined in `config_files/Stations/${STATION_NAME}/${STATION_NAME}.yml`.
The YAML controls workflow steps, data sources, station metadata, and initialization behavior.

### Main blocks
- `OSVAS_steps`: enables or disables workflow steps and lists experiment names.
  - `Create_forcing`
  - `Get_validation`
  - `Run_surfex`
  - `Extract_model_sqlites`
  - `Run_HARP`
  - `Display_HARP`
  - `Expnames`: list of experiment names
  - `Surfex_steps`: ordered list of SURFEX steps to run (`PGD`, `PREP`, `OFFLINE`, ...)

- `Station_metadata`: basic station info such as `Station_name`, `SID`, `elev`, `lat`, `lon`, `vegtype`, and vegetation/lai parameters.

- `Forcing_data`: defines the ICOS datasets used for forcing generation.
  - `height_T`, `height_V`
  - `run_start`, `run_end`
  - `forcing_format`: `netcdf` or `ascii`
  - dataset entries with `doi`, `timedelta`, `variables`, and optional `units`

- `Validation_data`: defines ICOS datasets for validation and output sqlite behaviour.
  - `validation_start`, `validation_end`
  - `common_obstable`: if `true`, write validation obstables to a shared directory for cross-station comparison
  - `common_fctable`: if `true`, extract model FCTABLEs to a common directory structure (`sqlites/model_data/common_fctables/`) shared across stations running the same experiment, identified by SID. Defaults to `false`
  - dataset entries with `doi`, `timedelta`, `variables`, and `units`

- `Initialization_data`: controls soil initialization derived from validation or station metadata.
  - `metadata_filename`
  - `reuse_soil_profile`: reuse previously saved soil profile coefficients if available
  - `Init_to_namelist`: if `true`, patch `OPTIONS.nam` before the SURFEX run
  - `Init_to_prep`: if `true`, patch `PREP.txt`/`PREP.nc` after `PREP`
  - `soil_depths_ts`: soil temperature observation depths (m)
  - `soil_depths_swc`: soil moisture observation depths (m)
  - These settings are consumed by `scripts/python_scripts/apply_soil_initialization.py` when initialization is enabled.

### Example
```yaml
OSVAS_steps:
  Create_forcing: true
  Get_validation: true
  Run_surfex: true
  Extract_model_sqlites: true
  Run_HARP: true
  Display_HARP: true
  Expnames:
    - DIF_v9
  Surfex_steps:
    - PGD
    - PREP
    - OFFLINE

Initialization_data:
  metadata_filename: 'ICOSETC_FR-Tou_VARINFO_METEO_L2.csv'
  reuse_soil_profile: false
  Init_to_namelist: true
  Init_to_prep: true
  soil_depths_ts: [0.05, 0.1, 0.2, 0.3, 0.4]
  soil_depths_swc: [0.05, 0.1, 0.2, 0.3, 0.4]
```
