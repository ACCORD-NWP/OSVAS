## The OSVAS Workflow
### OSVAS's central control scripts
OSVAS uses Python workflow launchers in `scripts/python_scripts/` for platform-specific execution:

- **`scripts/python_scripts/surfex_OSVAS_run_linux.py`** — Runs the workflow on local Linux systems.
- **`scripts/python_scripts/surfex_OSVAS_run_atos.py`** — Runs the workflow on ATOS HPC.

Both scripts read the station configuration from `config_files/Stations/${STATION_NAME}/${STATION_NAME}.yml` and execute the workflow steps activated in its `OSVAS_steps` block. The YAML file also defines station metadata, sources for forcing and validation datasets, and multiple other options and features of the workflow.

#### Notebook execution
The workflow includes data processing steps implemented as **Jupyter notebooks**:
- `scripts/notebooks/WRITE_Station_forcing.ipynb` — Generates SURFEX forcing data
- `scripts/notebooks/Flux_downloader.ipynb` — Downloads and processes validation data, including an SURFEX initialization module for soil temperature & moisture

These notebooks are **automatically converted to Python scripts** using `jupyter nbconvert` when the launcher runs, enabling execution in environments without Jupyter. Pre-converted `.py` versions are also available and can be executed directly when setting jupyter = False in the central control scripts.

#### Command Line Arguments

Both launcher scripts accept command line arguments to override environment variables:

- `--stations STATION1 STATION2 ...`: Process multiple stations serially (overrides `STATION_NAME` env var)
- `--osvas OSVAS_PATH`: Override OSVAS root directory (overrides `OSVAS` env var)
- `--harpscripts HARPSCRIPTS_PATH`: Override HARP scripts directory (overrides `HARPSCRIPTS` env var)

**Example:**
```bash
# Process the workflow for multiple stations in sequence
python3 scripts/python_scripts/surfex_OSVAS_run_linux.py --stations Majadas_del_tietar Loobos Meteopole

# Override default paths
python3 scripts/python_scripts/surfex_OSVAS_run_linux.py --osvas /custom/path/to/osvas
```

### Key workflow behavior
- **Step 1** generates SURFEX forcing data from ICOS atmospheric datasets, following the configuration in `Forcing_data`.
- **Step 2** downloads and processes ICOS flux data, creates OBSTABLES (sqlite validation data), and optionally computes soil initialization profiles from soil moisture and temperature data, albedos from SW_IN/SW_OUT radiation data and LAIs from Copernicus data, and updates the experiment's namelists accordingly.
- **Step 3** prepares run directories for each experiment, links forcing and physiography files, updates the namelists with simulation dates, optionally applies initialization profiles, and executes the selected SURFEX steps (PGD, PREP, OFFLINE).
- **Step 4** converts SURFEX NetCDF outputs to SQLite FCTABLES (monthly files by variable) for use with HARP or other validation tools if needed.
- **Step 5** generates and runs HARP point verification, producing validation statistics and plots.
- **Step 6** displays verification results via interactive Shiny apps with intelligent port detection.

### SURFEX setup
The Python launchers expect SURFEX binaries and environment files to be available on the host system. See more info in [SURFEX installation setup](installation.md#how-to-make-your-surfex-installation-known-to-osvas).
### Linkage of Physiography data
**For local Linux:**
- The Linux launcher links physiography files from the SURFEX installation and `$HOME/PHYSIO/`
  
**For ATOS:**
- The ATOS launcher links more weigthy climate data (e.g., `ECOCLIMAP-SG`, `GMTED2010`, `SOILGRID`) from accord's or other shared folders in the HPC filesystem

### Initialization workflow
Soil initialization profiles for the different soil levels in the DIF scheme can be derived from validation data if available. This is controlled by the `Initialization_data` block in the station YAML, where it is possible to specify the observed soil levels and the strategy for the use of the profiles:

- `Init_to_namelist: true` — Patches `OPTIONS.nam` with soil temperature/humidity profiles before the SURFEX run (only available after SURFEXv9)
- `Init_to_prep: true` — Patches `PREP` files with profiles after the PREP step completes.

Profiles are stored as NumPy arrays (`tg_profile.npy`, `hug_profile.npy`) in `profiles/{station}/` and applied by `scripts/python_scripts/apply_soil_initialization.py`. More info available in [soil initialization profiles](https://github.com/ACCORD-NWP/OSVAS/blob/develop/docs/step2_validation.md#soil-initialization-profiles).

### Relevant paths:
- **Station config:** `config_files/Stations/${STATION_NAME}/${STATION_NAME}.yml`
- **Forcing data:** `forcings/${STATION_NAME}/`
- **Run directories:** `RUNS/${STATION_NAME}/${EXPNAME}/run/`
- **Output files:** `RUNS/${STATION_NAME}/${EXPNAME}/output/`
- **HARP verification:** `RUNS/${STATION_NAME}/HARPVERIF/`
- **Model SQLites (FCTABLES):** `sqlites/FCTABLES/{STATION_NAME}/` or `sqlites/FCTABLES/common_fctables/` (if `common_fctable: true`)
- **Validation SQLites (OBSTABLES):** `sqlites/OBSTABLES/validation_data/{STATION_NAME}/` or `sqlites/OBSTABLES/validation_data/common_obstables/` (if `common_obstable: true`)
