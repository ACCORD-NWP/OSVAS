## Installation
### Get the OSVAS code
```
mkdir OSVAS
cd OSVAS
git clone https://github.com/ACCORD-NWP/OSVAS.git .
``` 
### Conda Environment
  It is advised to install the needed python packages as a conda environment.
  On atos, it is available by loading its module:
```
  module load conda/24.11.3-2
``` 
  If it's not installed in your system, we recommend to use a Miniconda distribution:
```
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
    bash Miniconda3-latest-Linux-x86_64.sh
```
You will be asked if you wish to update your shell profile to automatically initialize conda? The recommendation is "yes". This will modify your profile to have the conda commands available in your terminal on startup. The con is that it automatically activates the "base" environment in every new shell. But this can be easily avoided with this command:
```
    conda config --set auto_activate_base false
```
After installing or loading conda's module:
```
cd scripts/bash_scripts
./create_conda_environment.sh
```
  - This will create an `OSVASENV` conda environment and install the dependencies, including Python packages used by the workflow launcher and notebook conversion.
  - The workflow entrypoints are Python scripts in `scripts/python_scripts/`, and station-specific settings are read from `config_files/Stations/${STATION_NAME}/${STATION_NAME}.yml`.
  - For running the verification step:
    - A functional HARP installation. If you installed OSVAS on ATOS, HARP is already installed by the installation script. Otherwise, you can follow e.g. these instructions: https://harphub.github.io/harp_training_2024/get-started.html#installation.
    - `oper-harp-verif` scripts (https://github.com/harphub/oper-harp-verif.git) must be available. They are not bundled with OSVAS and may require additional R package dependencies.

### Workflow entrypoints
OSVAS is launched through Python control scripts rather than a single shell wrapper.
- Local Linux: `python3 scripts/python_scripts/surfex_OSVAS_run_linux.py`
- ATOS: `python3 scripts/python_scripts/surfex_OSVAS_run_atos.py`

These Python scripts read station YAML and may convert notebooks into Python before execution when `jupyter=True`.

#### Command Line Arguments

Both launcher scripts accept the following command line arguments:

- `--stations STATION1 STATION2 ...`: List of station names to process serially (overrides `STATION_NAME` env var)
- `--condaenv CONDAENV`: Conda environment name (overrides `CONDAENV` env var)  
- `--osvas OSVAS_PATH`: OSVAS root directory (overrides `OSVAS` env var)
- `--harpscripts HARPSCRIPTS_PATH`: HARP scripts directory (overrides `HARPSCRIPTS` env var)

Example:
```bash
# Process multiple stations
python3 scripts/python_scripts/surfex_OSVAS_run_linux.py --stations Majadas_del_tietar Meteopole
```

### Required dependencies
The Conda environment script installs the Python packages used by the workflow launchers and notebook conversion. In addition, OSVAS relies on several R packages for HARP verification and visualization.
  ```
  pkg_list <- c("here","argparse","yaml","dplyr","tidyr",
              "purrr","forcats","stringr","RColorBrewer","grid",
              "gridExtra","pracma","RSQLite","scales","pals",
              "shiny","shinyWidgets","lubridate","scico","cowplot")
for (pkg in pkg_list) {
  install.packages(pkg)
}
``` 
  - Activate the conda environment to start using OSVAS.
```
conda env activate OSVASENV
```
### SURFEX
- A functional **SURFEX installation** is required, and the namelist to run it must of course be compatible with this version: Here are a few suggestions:
    - Opensurfex8.1 https://www.umr-cnrm.fr/surfex/spip.php?article387
    - ACCORD's SURFEX_NWP: https://github.com/ACCORD-NWP/SURFEX-NWP
### ICOS login & token
In order to download ICOS data from their python API, it is necessary to create an account there, login and get an access token which must be stored in $OSVAS/icos_cookie.txt . This cookie must be renewed every 27.8h (10⁵  seconds). Follow instructions in https://cpauth.icos-cp.eu/login/ . After logging in, you'll find your token at the bottom of your user profile info.
## The OSVAS Workfow
