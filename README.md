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

All documentation is available inside the `docs/` folder, organized as follows:

### 🔧 <u>[**Setup & Configuration: Install requirements in a conda environment**](docs/installation.md)</u>

### 🧪 <u>[**OSVAS central control script**](docs/OSVAS_workflow.md)</u>

### 🧪 <u>**Detailed description of steps in the OSVAS Workflow:**</u>

**Step 0:** [Paths & Global Configuration](docs/step0_paths_and_config.md)
   
**Step 1:** [Forcing Data Generation](docs/step1_forcing.md)
 
**Step 2:** [Validation Data Download](docs/step2_validation.md)
 
**Step 3:** [SURFEX Simulation Runs](docs/step3_surfex_runs.md)

**Step 4:** [Extraction of Model Outputs (`nc2sqlite`)](docs/step4_nc2sqlite.md)

**Step 5:** [HARP Verification](docs/step5_harp_verification.md)

**Step 6:** [Visualization Apps](docs/step6_visualization.md)

In addition, [a pdf presentation is available](docs/OSVAS_Workflow.pdf)

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

### 3️⃣ Edit your run script

Set the station name and paths:

```bash
export STATION_NAME=Majadas_del_tietar
export OSVAS=$HOME/OSVAS
export HARP=$HOME/operharpverif
```

### 4️⃣ Run OSVAS

```bash
./surfex_OSVAS_run_linux.sh
```

