## Installation
### Get the OSVAS code
```bash
mkdir OSVAS
cd OSVAS
git clone https://github.com/ACCORD-NWP/OSVAS.git .
``` 

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

After conda is available, create the OSVAS environment:
```bash
cd scripts/bash_scripts
./create_conda_environment.sh
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

**HARP verification scripts:**
The `oper-harp-verif` repository (https://github.com/harphub/oper-harp-verif.git) must be cloned separately and available for the verification steps. It includes:
- Point verification scripts (`point_verif.R`)
- Visualization apps (Shiny apps for dynamic and static displays)

Set the path to `oper-harp-verif` via the `HARPSCRIPTS` environment variable or the `--harpscripts` command line argument.

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
Set these environment variables before running the workflow (or use command line arguments to override):
```bash
export STATION_NAME=Majadas_del_tietar       # Station to process
export OSVAS=$HOME/OSVASgh                    # OSVAS root directory
export CONDAENV=OSVASENV                      # Conda environment name
export HARPSCRIPTS=$HOME/operharpverif        # Path to oper-harp-verif clone
```
