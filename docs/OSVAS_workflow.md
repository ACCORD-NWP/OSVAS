## The OSVAS Workflow
### OSVAS's central control scripts
OSVAS now uses Python workflow launchers in `scripts/python_scripts/` rather than a single bash wrapper.

- `scripts/python_scripts/surfex_OSVAS_run_linux.py` runs the Linux workflow.
- `scripts/python_scripts/surfex_OSVAS_run_atos.py` runs the ATOS workflow.

Both scripts read the station YAML under `config_files/Stations/${STATION_NAME}/${STATION_NAME}.yml` and control the selected steps via the `OSVAS_steps` block. This YAML also defines forcing, validation, and station metadata.

The workflow may execute notebook steps by converting them to Python scripts with `jupyter nbconvert` when `jupyter = True` in the launcher.

#### Command Line Arguments

Both launcher scripts support command line arguments to override environment variables and specify multiple stations:

- `--stations STATION1 STATION2 ...`: Process multiple stations serially
- `--condaenv CONDAENV`: Override conda environment name
- `--osvas OSVAS_PATH`: Override OSVAS root directory
- `--harpscripts HARPSCRIPTS_PATH`: Override HARP scripts directory

When multiple stations are specified, the workflow runs serially for each station.

### Key workflow behavior
- `Step 1` creates forcing data from ICOS datasets.
- `Step 2` downloads and processes validation data, writes sqlite obstables, and can also compute initialization profiles.
- `Step 3` prepares run directories, copies namelists, links forcings and physiography, updates date/timestamp settings, optionally applies soil initialization, and runs the selected SURFEX steps.
- `Step 4` converts SURFEX outputs to SQLite using `nc2sqlite.py`.
- `Step 5` generates HARP verification config and optionally runs HARP verification.

### SURFEX and physiography setup
The Python launchers expect SURFEX binaries and environment variables to be available on the host system.

For local Linux, the launcher currently uses a SURFEX profile like `profile_surfex-LXgfortran-SFX-V8-1-1-NOMPI-OMP-O2-X0` and links physiography files from the SURFEX setup and `$HOME/PHYSIO/`.

For ATOS, the launcher uses a SURFEX profile specific to ATOS and may also link climate data from the host filesystem (e.g. `ECOCLIMAP-SG`, `GMTED2010`, `SOILGRID`).

### Initialization workflow
A new initialization subsystem is available via the `Initialization_data` block in station YAML:
- `Init_to_namelist: true` patches `OPTIONS.nam` before the SURFEX run.
- `Init_to_prep: true` patches `PREP` files after the PREP step.
- This is handled by `scripts/python_scripts/apply_soil_initialization.py` using precomputed `tg_profile.npy` and `hug_profile.npy` files stored in `profiles/{station}/`.

### Paths
- Station config: `config_files/Stations/${STATION_NAME}/${STATION_NAME}.yml`
- Run directories: `RUNS/${STATION_NAME}/${EXPNAME}/run/`
- Output directories: `RUNS/${STATION_NAME}/${EXPNAME}/output/`
- HARP verification output: `RUNS/${STATION_NAME}/HARPVERIF/`
