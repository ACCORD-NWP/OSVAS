## Step 3: Configure and run the simulations
For each experiment defined in `OSVAS_steps.Expnames`:
- The launcher loads SURFEX installation settings from `config_files/SURFEX/surfex_configuration.yaml`. Shared settings are defined in `general`, with optional overrides in the selected runner's `platforms.linux` or `platforms.atos` block.
- Optional top-level blocks named exactly after an experiment can override individual settings for that experiment. For example, a `MY_EXPERIMENT` block overrides matching keys from `general` and the platform block; keys omitted there continue to use the inherited settings. These overrides belong in `surfex_configuration.yaml`, not the station YAML.
- A run directory is created at `RUNS/${STATION_NAME}/${EXPNAME}/run/`.
- Forcing files are linked from `forcings/${STATION_NAME}/` into the run directory.
- Required physiography files are linked from the SURFEX setup and local physiography paths.
- The station-specific template namelist `namelists/${STATION_NAME}/OPTIONS.nam_${EXPNAME}` is copied into the run directory as `OPTIONS.nam`.
- The launcher updates `NYEAR`, `NMONTH`, `NDAY`, `XTIME`, and `CFORCING_FILETYPE` in `OPTIONS.nam` to match the configured forcing period.

The SURFEX steps listed in `OSVAS_steps.Surfex_steps` are then executed in the run directory.

In the shared configuration, `surfex_exe` and `paramfiles` may be relative to `surfex_home` or specified as absolute paths. `physiography_paths` is an optional list of additional directories linked into each run directory. See [How to make your SURFEX installation known to OSVAS](installation.md#how-to-make-your-surfex-installation-known-to-osvas) for the configuration layout and an example.

If `Initialization_data.Init_to_namelist` is true, soil initialization profiles are applied to `OPTIONS.nam` before the first SURFEX step.
If `Initialization_data.Init_to_prep` is true, profiles are applied to `PREP.txt`/`PREP.nc` immediately after `PREP` completes.
These initialization operations are implemented by `scripts/python_scripts/apply_soil_initialization.py`.

After execution, important output files are moved or copied from the run directory into `RUNS/${STATION_NAME}/${EXPNAME}/output/`.

This current workflow therefore supports:
- reusing validation-derived initialization profiles for SURFEX runs,
- running only part of the SURFEX chain and then applying initialization before continuing,
- keeping both raw run directory contents and a cleaned output directory.
