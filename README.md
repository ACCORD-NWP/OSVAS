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

## 📚 Documentation Structure

All documentation is available inside the `docs/` folder, organized as follows:

### 🔧 **Setup & Configuration**: Install requirements in a conda environment

### 🧪 **OSVAS Workflow**
1. **Step 0:** Paths & Global Configuration
2. **Step 1:** Forcing Data Generation
3. **Step 2:** Validation Data Download
4. **Step 3:** SURFEX Simulation Runs
5. **Step 4:** Extraction of Model Outputs (`nc2sqlite`)
6. **Step 5:** HARP Verification
7. **Step 6:** Visualization Apps

---

## ⚡ Quick Start

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

