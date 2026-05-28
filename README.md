# 🚀 OSVAS — Offline Surfex Validation System

**OSVAS** is a workflow developed within the **ACCORD community** to automate the full SURFEX offline validation chain:

* **Generate** SURFEX forcing data from ICOS atmospheric datasets
* **Download & process** ICOS flux data for validation
* **Run** SURFEX OFFLINE simulations (PGD, PREP, OFFLINE)
* **Convert** SURFEX outputs to SQLite FCTABLES (via `nc2sqlite`)
* **Validate** model outputs using **HARP**
* **Visualize** results with interactive **Shiny apps**

OSVAS automates the entire cycle:
**Forcing → Simulation → Extraction → Validation → Visualization**

---

## 📚 Documentation

All documentation is available inside the `docs/` folder and in https://accord-nwp.github.io/OSVAS/ , organized as follows:

### 🔧 <u>[**Setup & Configuration: Install requirements conda & R environments **](docs/installation.md)</u>

### 🧪 <u>[**OSVAS central control script**](docs/OSVAS_workflow.md)</u>

### 🧪 <u>**Detailed description of steps in the OSVAS Workflow:**</u>

**Step 0:** [Paths & Global Configuration](docs/step0_paths_and_config.md)
   
**Step 1:** [Forcing Data Generation](docs/step1_forcing.md)
 
**Step 2:** [Validation Data Download](docs/step2_validation.md)

**Step 2b:** [Albedo_estimation from site data](docs/step2_albedo_estimation.md)

**Step 2c:** [LAI estimation from satellite data](docs/step2c_lai_estimation.md)
 
**Step 3:** [SURFEX Simulation Runs](docs/step3_surfex_runs.md)

**Step 4:** [Extraction of Model Outputs (`nc2sqlite`)](docs/step4_nc2sqlite.md)

**Step 5:** [HARP Verification](docs/step5_harp_verification.md)

**Step 6:** [Visualization Apps](docs/step6_visualization.md)

In addition, [a pdf presentation is available](docs/OSVAS_Workflow.pdf)

### 🧪 <u>[**ICOS data**](docs/ICOS_data.md)</u>

---
## ⚡ Quick Start guide

### 1️⃣ Clone the repository

```bash
git clone https://github.com/ACCORD-NWP/OSVAS.git
cd OSVAS
```

### 2️⃣ Create the conda environment

```bash
cd scripts/bash_scripts
./create_conda_and_R_envs.sh
conda activate OSVASENV
```

### 3️⃣ Choose your entrypoint and set paths

Set the station name and paths in your shell (or override via command line arguments):

```bash
export STATION_NAME=Majadas_del_tietar
export OSVAS=$HOME/OSVASgh
export HARPSCRIPTS=$HOME/operharpverif
```

### 4️⃣ Run OSVAS

For local Linux:
```bash
python3 scripts/python_scripts/surfex_OSVAS_run_linux.py
```

For ATOS:
```bash
python3 scripts/python_scripts/surfex_OSVAS_run_atos.py
```

These Python launcher scripts read the station YAML under `config_files/Stations/${STATION_NAME}/${STATION_NAME}.yml`, execute the selected workflow steps, and apply station-specific initialization and forcing configuration.

#### Command Line Options

Both launcher scripts support the following command line arguments:

- `--stations STATION1 STATION2 ...`: List of station names to process serially (overrides `STATION_NAME` environment variable)
- `--condaenv CONDAENV`: Conda environment name (overrides `CONDAENV` environment variable)
- `--osvas OSVAS_PATH`: OSVAS root directory (overrides `OSVAS` environment variable)  
- `--harpscripts HARPSCRIPTS_PATH`: HARP scripts directory (overrides `HARPSCRIPTS` environment variable)

Example usage:
```bash
# Run multiple stations serially
python3 scripts/python_scripts/surfex_OSVAS_run_linux.py --stations Majadas_del_tietar Meteopole Loobos

# Override environment variables
python3 scripts/python_scripts/surfex_OSVAS_run_linux.py --osvas /path/to/osvas --harpscripts /path/to/harp
```

