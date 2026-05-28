## The OSVAS Workflow
### OSVAS's central control scripts
OSVAS uses Python workflow launchers in `scripts/python_scripts/` for platform-specific execution:

- **`scripts/python_scripts/surfex_OSVAS_run_linux.py`** — Runs the workflow on local Linux systems.
- **`scripts/python_scripts/surfex_OSVAS_run_atos.py`** — Runs the workflow on ATOS HPC.

Both scripts read the station configuration from `config_files/Stations/${STATION_NAME}/${STATION_NAME}.yml` and control which workflow steps execute via the `OSVAS_steps` block. The YAML also defines forcing data sources, validation datasets, and station metadata.

#### Notebook execution
The workflow includes data processing steps implemented as **Jupyter notebooks**:
- `scripts/notebooks/WRITE_Station_forcing.ipynb` — Generates SURFEX forcing data
- `scripts/notebooks/Flux_downloader.ipynb` — Downloads and processes validation data, including an SURFEX initialization module for soil temperature & moisture

These notebooks are **automatically converted to Python scripts** using `jupyter nbconvert` when the launcher runs, enabling execution in environments without Jupyter. Pre-converted `.py` versions are also available and can be executed directly when setting jupyter = False in the central control scripts.

#### Command Line Arguments

Both launcher scripts accept command line arguments to override environment variables:

- `--stations STATION1 STATION2 ...`: Process multiple stations serially (overrides `STATION_NAME` env var)
- `--condaenv CONDAENV`: Override conda environment name (overrides `CONDAENV` env var)
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
- **Step 2** downloads and processes ICOS flux data, creates OBSTABLES (sqlite validation data), and optionally computes soil initialization profiles, albedos from radiation data and LAIs from Copernicus data, and updates the experiment's namelists accordingly.
- **Step 3** prepares run directories for each experiment, links forcing and physiography files, updates the namelist with simulation dates, optionally applies initialization profiles, and executes the selected SURFEX steps (PGD, PREP, OFFLINE).
- **Step 4** converts SURFEX NetCDF outputs to SQLite FCTABLES (monthly files by variable) for use with HARP or other validation tools.
- **Step 5** generates and runs HARP point verification, producing validation statistics and plots.
- **Step 6** displays verification results via interactive Shiny apps with intelligent port detection.

### SURFEX and physiography setup
The Python launchers expect SURFEX binaries and environment files to be available on the host system.

**For local Linux:**
- Uses a SURFEX profile like `profile_surfex-LXgfortran-SFX-V8-1-1-NOMPI-OMP-O2-X0`.
- Links physiography files from the SURFEX installation and `$HOME/PHYSIO/`.

**For ATOS:**
- Uses ATOS-specific SURFEX profile and compilation environment.
- May link climate data from the HPC filesystem (e.g., `ECOCLIMAP-SG`, `GMTED2010`, `SOILGRID`).

### Initialization workflow
Soil initialization can derive from validation data or station metadata via the `Initialization_data` block in the station YAML:

- `Init_to_namelist: true` — Patches `OPTIONS.nam` with soil temperature/humidity profiles before the SURFEX run.
- `Init_to_prep: true` — Patches `PREP` files with profiles after the PREP step completes.

Profiles are stored as NumPy arrays (`tg_profile.npy`, `hug_profile.npy`) in `profiles/{station}/` and applied by `scripts/python_scripts/apply_soil_initialization.py`.

### Paths
- **Station config:** `config_files/Stations/${STATION_NAME}/${STATION_NAME}.yml`
- **Forcing data:** `forcings/${STATION_NAME}/`
- **Run directories:** `RUNS/${STATION_NAME}/${EXPNAME}/run/`
- **Output files:** `RUNS/${STATION_NAME}/${EXPNAME}/output/`
- **HARP verification:** `RUNS/${STATION_NAME}/HARPVERIF/`
- **Model SQLites (FCTABLES):** `sqlites/FCTABLES/{STATION_NAME}/` or `sqlites/FCTABLES/common_fctables/` (if `common_fctable: true`)
- **Validation SQLites (OBSTABLES):** `sqlites/OBSTABLES/validation_data/{STATION_NAME}/` or `sqlites/OBSTABLES/validation_data/common_obstables/` (if `common_obstable: true`)
