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

### 🔧 <u>[**Setup & Configuration: Install requirements in a conda environment**](https://accord-nwp.github.io/OSVAS/installation.html)</u>

### 🧪 <u>[**OSVAS central control script**](https://accord-nwp.github.io/OSVAS/OSVAS_workflow.html)</u>

### 🧪 <u>**Detailed description of steps in the OSVAS Workflow:**</u>

**Step 0:** [Paths & Global Configuration](https://accord-nwp.github.io/OSVAS/step0_paths_and_config.html)
   
**Step 1:** [Forcing Data Generation](https://accord-nwp.github.io/OSVAS/step1_forcing.html)
 
**Step 2:** [Validation Data Download](https://accord-nwp.github.io/OSVAS/step2_validation.html)
 
**Step 3:** [SURFEX Simulation Runs](https://accord-nwp.github.io/OSVAS/step3_surfex_runs.html)

**Step 4:** [Extraction of Model Outputs (`nc2sqlite`)](https://accord-nwp.github.io/OSVAS/step4_nc2sqlite.html)

**Step 5:** [HARP Verification](https://accord-nwp.github.io/OSVAS/step5_harp_verification.html)

**Step 6:** [Visualization Apps](https://accord-nwp.github.io/OSVAS/step6_visualization.html)

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
./create_conda_environment.sh
conda activate OSVASENV
```

### 3️⃣ Choose your entrypoint and set paths

Set the station name and paths in your shell:

```bash
export STATION_NAME=Majadas_del_tietar
export OSVAS=$HOME/OSVASgh
export HARP=$HOME/operharpverif
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

