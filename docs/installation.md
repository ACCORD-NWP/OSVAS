## Installation
### Get the OSVAS code
```bash
mkdir OSVAS
cd OSVAS
git clone https://github.com/ACCORD-NWP/OSVAS.git .
```

### Setup OSVAS installation (clone HARPSCRIPTS)
After cloning the OSVAS repository, run the installation setup script to automatically clone the HARP verification scripts:
```bash
cd OSVAS
./scripts/bash_scripts/setup_osvas_installation.sh
```

This script will:
1. **Clone the HARPSCRIPTS repository** from `git@github.com:harphub/oper-harp-verif.git` into `$OSVAS/HARPSCRIPTS/`
2. **Apply OSVAS compatibility patches** to the cloned HARPSCRIPTS files
3. **Display environment variable configuration** for your shell (`.bashrc` or `.bash_profile`)
4. **Verify the setup** by checking that all directories and expected files are present

**Typical usage:**
```bash
# Basic usage (auto-detects OSVAS from script location)
./scripts/bash_scripts/setup_osvas_installation.sh

# Or specify OSVAS directory explicitly
./scripts/bash_scripts/setup_osvas_installation.sh --osvas /path/to/OSVAS
```

After running the script, you can set the environment variables in your shell by copying the suggested export commands, or by adding them to your `~/.bashrc` file.

**Note:** The launcher scripts automatically detect the OSVAS root directory from their script location, so you typically only need to set the environment variables if you plan to call the scripts from a different directory.

### Conda Environment
It is recommended to install the required Python packages in a conda environment.

On ATOS (ECMWF HPC), conda is available via a module:
```bash
module load conda/24.11.3-2
``` 

If not installed on your system, install Miniconda:
```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
```

You will be prompted to initialize conda for your shell. We recommend accepting this. To avoid auto-activating the base environment, you can disable it:
```bash
conda config --set auto_activate_base false
```

After conda is available, next step is to create the OSVAS conda environment OSVASENV,
including the installation of HARP's R libraries inside an Renv. This is done by renv_{atos,ubuntu}/renv_setup.R
Since there is a strict rate limit on "anonymous" installs of libraries from CRAN mirrors, renv_setup.R must be edited to add your
personal github pat:
```# Optional: set your GitHub PAT to avoid rate-limiting on installs
# (more info here https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/
# /managing-your-personal-access-tokens
# ---------------------------------------------------------------------------
 Sys.setenv(GITHUB_PAT = "Put_your_github_personal_access_token_here")
```
Next, simply run the script to complete the installation with conda & R environments:
```bash
cd scripts/bash_scripts
./create_conda_and_R_envs.sh
```

This will:
1. Create an `OSVASENV` conda environment with Python 3.11 and required packages
2. Install Python dependencies from `requirements.txt`
3. On ATOS: Set up an isolated R environment (renv) for HARP libraries

The conda environment includes:
- **Python data packages:** pandas, numpy, scipy, matplotlib, xarray, netCDF4, cftime
- **ICOS API:** icoscp (for accessing ICOS datasets)
- **Notebook tools:** notebook, nbconvert, jupyterlab (for Jupyter notebook support)

### Python launcher scripts and Jupyter notebooks
The OSVAS workflow is orchestrated by two Python launcher scripts in `scripts/python_scripts/`:

- **`surfex_OSVAS_run_linux.py`** — Runs on local Linux systems
- **`surfex_OSVAS_run_atos.py`** — Runs on ATOS HPC

These scripts execute Jupyter notebooks for data processing steps:
- `scripts/notebooks/WRITE_Station_forcing.ipynb` — Generates forcing from ICOS data
- `scripts/notebooks/Flux_downloader.ipynb` — Downloads and processes validation data & performs optional soil initialization

**Notebook execution modes:**
- **Via nbconvert (default):** The launcher converts notebooks to Python scripts using `jupyter nbconvert` and executes them. This supports headless environments and doesn't require a Jupyter server.
- **Direct Python execution:** Pre-converted `.py` versions are available (`WRITE_Station_forcing.py`, `Flux_downloader.py`) and can be executed standalone.
- **Interactive Jupyter:** Notebooks can also be run manually with `jupyter notebook` or `jupyter lab` for development and debugging.

### HARP and verification setup

**HARP installation:**
- On ATOS: HARP and R dependencies are automatically installed by the setup script in `renv_atos/`.
- On other systems: Follow the HARP installation guide: https://harphub.github.io/harp_training_2024/get-started.html#installation

**HARP verification scripts (oper-harp-verif):**
The `oper-harp-verif` repository (https://github.com/harphub/oper-harp-verif.git) is automatically cloned during installation into `$OSVAS/HARPSCRIPTS/` by the `setup_osvas_installation.sh` script. It includes:
- Point verification scripts (`point_verif.R`)
- Visualization apps (Shiny apps for dynamic and static displays)

**Automatic path detection:**
The launcher scripts (`surfex_OSVAS_run_linux.py` and `surfex_OSVAS_run_atos.py`) automatically:
1. Detect the OSVAS root directory from their script location (no need for manual configuration in most cases)
2. Default `HARPSCRIPTS` to `$OSVAS/HARPSCRIPTS`

You can override these defaults by:
- Setting environment variables: `export OSVAS=/path/to/osvas` and `export HARPSCRIPTS=/path/to/harpscripts`
- Using command line arguments when running the launcher scripts: `--osvas` and `--harpscripts`

**Required R packages** (on non-ATOS systems):
```r
pkg_list <- c("here","argparse","yaml","dplyr","tidyr",
              "purrr","forcats","stringr","RColorBrewer","grid",
              "gridExtra","pracma","RSQLite","scales","pals",
              "shiny","shinyWidgets","lubridate","scico","cowplot")
for (pkg in pkg_list) {
  install.packages(pkg)
}
```

### Activate the conda environment
Once setup is complete, activate the environment:
```bash
conda activate OSVASENV
```

### SURFEX installation
A functional SURFEX installation is required. The workflow expects:
- SURFEX binaries compiled and available in the system PATH or via environment modules
- A profile script (e.g., `profile_surfex-LXgfortran-SFX-V8-1-1-NOMPI-OMP-O2-X0`) that sets up the compilation environment

Recommended SURFEX versions:
- **OpenSurfex 8.1:** https://www.umr-cnrm.fr/surfex/spip.php?article387
- **ACCORD's SURFEX_NWP:** https://github.com/ACCORD-NWP/SURFEX-NWP
- **ACCORD-NWP:** , v9 branch at https://github.com/ACCORD-NWP/SURFEX/tree/SURFEX_V9_DEV_NWP 
On ATOS, the compilation environment is typically set up via modules. On local systems, ensure the SURFEX home directory is configured (usually via the launcher script's `surfex_home` variable).

### ICOS login & token
To download ICOS data via the Python API, you must:
1. Create an account at https://cpauth.icos-cp.eu/login/
2. Log in and retrieve your access token from your user profile
3. Store the token in `$OSVAS/icos_cookie.txt`
**Important:** ICOS tokens expire after 27.8 hours (100,000 seconds) and must be renewed regularly.

### KNMI login & API_key
1. Register at https://developer.dataplatform.knmi.nl/register/
2. Login at https://developer.dataplatform.knmi.nl/login
3. Get API key at https://developer.dataplatform.knmi.nl/member/ and store at $OSVAS/knmi_apikey.txt

**Important:** To access the soil moisture datasets for Cabauw https://dataplatform.knmi.nl/dataset/cesar-soil-water-lb1-t10-v1-1,
 a special request must be addressed to opendata@knmi.nl

### Environment variables and paths
The launcher scripts automatically detect paths based on their script location. However, you can optionally set these environment variables to override the defaults:

```bash
export STATION_NAME=Majadas_del_tietar       # Station to process (required)
export OSVAS=$HOME/OSVASgh                    # OSVAS root (auto-detected if not set)
export CONDAENV=OSVASENV                      # Conda environment name (default: OSVHARP)
export HARPSCRIPTS=$OSVAS/HARPSCRIPTS         # HARP scripts path (auto-detected if not set)
```

**Typical usage:**
In most cases, you only need to set `STATION_NAME`. The launcher scripts will automatically:
- Detect `OSVAS` from their location in `scripts/python_scripts/`
- Set `HARPSCRIPTS` to `$OSVAS/HARPSCRIPTS`
- Use `OSVHARP` as the default conda environment

**Command line override:**
You can also pass these as command line arguments:
```bash
python surfex_OSVAS_run_linux.py --stations Cabauw Loobos --osvas /path/to/osvas --harpscripts /path/to/harpscripts
```
