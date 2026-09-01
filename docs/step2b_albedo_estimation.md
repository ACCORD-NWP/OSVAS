# Surface Albedo Estimation from Validation Data

## Overview

This document describes the **albedo estimation workflow** in OSVAS, which automatically estimates monthly-averaged surface albedo values (NIR and VIS spectra) from validation radiation data for SURFEX simulations.

## TL;DR: Check this short guide [Albedo_estimation_quickref](albedo_estimation_quickref.md) and the [implementation summary](IMPLEMENTATION_SUMMARY.md)

## Motivation

SURFEX requires monthly surface albedo parameters for vegetation and soil surfaces across the NIR, VIS, and UV spectral bands:
- `XUNIF_ALBNIR_VEG` - Vegetation near-infrared albedo (12 monthly values) — **estimated from data**
- `XUNIF_ALBVIS_VEG` - Vegetation visible albedo (12 monthly values) — **estimated from data**
- `XUNIF_ALBUV_VEG` - Vegetation UV albedo (12 monthly values) — **fixed value** (0.015)
- `XUNIF_ALBNIR_SOIL` - Soil near-infrared albedo (12 monthly values) — **estimated from data**
- `XUNIF_ALBVIS_SOIL` - Soil visible albedo (12 monthly values) — **estimated from data**
- `XUNIF_ALBUV_SOIL` - Soil UV albedo (12 monthly values) — **fixed value** (0.06)

Rather than using generic parameterizations, the albedo estimation workflow derives the NIR and VIS values from actual observations at the validation site, improving model realism for the study location. The UV bands are not observed by the standard SW_OUT/SW_IN validation instruments, so `update_namelist_albedos.py` fills them with fixed constants (0.015 for vegetation, 0.06 for soil) rather than estimated values — see [Output Files](#output-files) below for when these constants are written.

## Physical Basis

Surface albedo is calculated as:

$$\alpha = \frac{SW_{OUT}}{SW_{IN}}$$

where:
- $SW_{OUT}$ is upwelling (reflected) shortwave radiation [W m⁻²]
- $SW_{IN}$ is downwelling (incident) shortwave radiation [W m⁻²]
- Only observations between **11:00-13:00 UTC** are used (high solar elevation, minimal geometric effects)

Monthly albedos are computed as the average of daily mean albedos within each calendar month during the validation period.

## Configuration

### 1. Enable Albedo Estimation in Station Configuration

Edit your station's YAML config file (e.g., `config_files/Stations/Cabauw/Cabauw.yml`):

```yaml
Station_metadata:
  Station_type: KNMI
  Station_name: Cabauw
  SID: 4300000008
  elev: 0
  lat: 51.9703
  lon: 4.9264
  vegtype: 10
  estimate_albedo: true        # ← Set to true to enable albedo estimation
```

### 2. Ensure Validation Data is Enabled

Make sure validation data download is enabled and configured with SW_OUT and SW_IN variables:

```yaml
OSVAS_steps:
  Get_validation: true          # ← Must be true

Validation_data:
  validation_start: '2017-11-01 00:00:00'
  validation_end: '2018-01-31 23:59:00'
  dataset1:
    doi: https://api.dataplatform.knmi.nl/.../cesar_surface_radiation_lc1_t10/...
    timedelta: 10
    variables:
      SW_OUT: SWU               # ← Required
      SW_IN: SWD                # ← Required
      LW_OUT: LWU
      LW_IN: LWD
```

## Workflow Integration

When `estimate_albedo: true` is set and validation data downloading is enabled, the albedo estimation executes automatically as **Step 2b** in the OSVAS workflow:

```
Step 1: Create forcing data
Step 2: Get validation data
Step 2b: ✨ Estimate surface albedos from validation data (NEW)
         ├─ Read SW_OUT/SW_IN from SQLite OBSTABLEs
         ├─ Select midday observations (11:00-13:00 UTC)
         ├─ Calculate daily albedos
         ├─ Compute monthly averages
         ├─ Generate namelist format blocks
         └─ Update all experiment namelists
Step 3: Run SURFEX simulations (with updated albedos)
Step 4: Extract model outputs
...
```

## Output Files

### 1. Estimated Albedo Namelist
**Location:** `namelists/{STATION_NAME}/albedo_estimates.nam`

**Content:** Formatted namelist blocks ready to be included in SURFEX namelists. Note that `estimate_albedo.py` only produces the NIR and VIS blocks — the UV blocks are added later by `update_namelist_albedos.py` itself (see below), not read from this file:
```fortran
! Estimated albedos from validation data (SW_OUT/SW_IN 11:00-13:00 UTC)
! Monthly averages for vegetation and soil surfaces

! Vegetation NIR albedo (monthly)
                       XUNIF_ALBNIR_VEG(10,1)  = 0.19024633,
                       XUNIF_ALBNIR_VEG(10,2)  = 0.18576372,
                       ...
                       XUNIF_ALBNIR_VEG(10,12) = 0.1538921,

! Vegetation VIS albedo (monthly)
                       XUNIF_ALBVIS_VEG(10,1)  = 0.19024633,
                       ...
                       XUNIF_ALBVIS_VEG(10,12) = 0.1538921,

! Soil NIR albedo (monthly)
                       XUNIF_ALBNIR_SOIL(10,1)  = 0.19024633,
                       ...

! Soil VIS albedo (monthly)
                       XUNIF_ALBVIS_SOIL(10,1)  = 0.19024633,
                       ...
```

### 2. Updated Experiment Namelists
**Location:** `namelists/{STATION_NAME}/OPTIONS.nam_{EXPNAME}`

`update_namelist_albedos.py` handles two cases, depending on whether the namelist already contains albedo blocks:

- **Blocks already present** (typical case): the four estimated blocks (`XUNIF_ALBNIR_VEG`, `XUNIF_ALBVIS_VEG`, `XUNIF_ALBNIR_SOIL`, `XUNIF_ALBVIS_SOIL`) are replaced in place with the new values from `albedo_estimates.nam`, preserving indentation. If `XUNIF_ALBUV_VEG`/`XUNIF_ALBUV_SOIL` blocks already exist in the namelist, they are left untouched (there is no estimated UV data to replace them with).
- **No albedo blocks found**: the script falls back to inserting all six blocks — the four estimated NIR/VIS blocks plus fixed-value `XUNIF_ALBUV_VEG` (0.015) and `XUNIF_ALBUV_SOIL` (0.06) blocks — directly into the `&NAM_DATA_ISBA` namelist group, just before its closing `/`. This previously required manual intervention (see [Troubleshooting](#troubleshooting)); it is now automatic.

Backup copies are created before either path writes to the file:
- `OPTIONS.nam_{EXPNAME}.backup_alb` - Original namelist before update

## Manual Execution

You can also run the albedo estimation scripts manually for testing or batch processing:

### Step 1: Estimate Albedos

```bash
python3 scripts/python_scripts/estimate_albedo.py \
    Cabauw \
    $OSVAS \
    --validation-period 2017-11-01 2018-01-31
```

**Parameters:**
- `station_name`: Station name (e.g., Cabauw, Loobos)
- `osvas_root`: Path to OSVAS root directory
- `--validation-period START_DATE END_DATE` (optional): Only process data within this period (YYYY-MM-DD format)
- `--output PATH` (optional): Save estimates to custom path (default: `namelists/{station}/albedo_estimates.nam`)

**Output:**
```
======================================================================
Estimating surface albedos for Cabauw
======================================================================

Step 1: Reading validation data from OBSTABLEs
  Found 3 OBSTABLE files
  Read: OBSTABLE_2017.sqlite
  Read: OBSTABLE_2018.sqlite
  Read: OBSTABLE_2019.sqlite
  Loaded 8760 records with valid SW_OUT/SW_IN

Step 2: Selecting midday observations (11:00-13:00 UTC)
  Selected 1460 records between 11:00-13:00 UTC

Step 3: Calculating daily albedos (SW_OUT/SW_IN)
  Calculated 365 daily average albedos

Step 4: Computing monthly averages
  Monthly albedo averages:
    Month  1: 0.34562891
    Month  2: 0.32891234
    ...
    Month 12: 0.35123456

Step 5: Generating namelist format
  Using vegtype: 10

Step 6: Saving results
  ✅ Albedo estimates saved to: /home/user/OSVAS/namelists/Cabauw/albedo_estimates.nam

  NIR albedo:  min=0.12345678, max=0.45678901, mean=0.28901234
  VIS albedo:  min=0.12345678, max=0.45678901, mean=0.28901234

======================================================================
✅ Albedo estimation completed successfully
======================================================================
```

### Step 2: Update Namelists

```bash
python3 scripts/python_scripts/update_namelist_albedos.py \
    Cabauw \
    $OSVAS \
    --expnames DIFMEB_v9 DIFMEB_v9DSL \
    --albedo-file namelists/Cabauw/albedo_estimates.nam
```

**Parameters:**
- `station_name`: Station name
- `osvas_root`: OSVAS root directory
- `--expnames EXP1 EXP2 ...` (optional): Experiment names to update (default: read from config YAML)
- `--albedo-file PATH` (optional): Path to albedo estimates (default: `namelists/{station}/albedo_estimates.nam`)
- `--no-backup` (optional): Don't create backup copies

**Output:**
```
======================================================================
Updating namelists with estimated albedos for Cabauw
======================================================================

Using experiments from config: DIFMEB_v9, DIFMEB_v9DSL

Step 1: Reading albedo estimates
  Read albedo estimates from: namelists/Cabauw/albedo_estimates.nam

Step 2: Updating experiment namelists

  Processing: DIFMEB_v9
    ✓ Found XUNIF_ALBNIR_VEG block
    ✓ Found XUNIF_ALBVIS_VEG block
    ✓ Found XUNIF_ALBUV_VEG block
    ✓ Found XUNIF_ALBNIR_SOIL block
    ✓ Found XUNIF_ALBVIS_SOIL block
    ✓ Found XUNIF_ALBUV_SOIL block
    ✓ Backup created: OPTIONS.nam_DIFMEB_v9.backup_alb
    ✓ Updated XUNIF_ALBNIR_VEG
    ✓ Updated XUNIF_ALBVIS_VEG
    ✓ Updated XUNIF_ALBNIR_SOIL
    ✓ Updated XUNIF_ALBVIS_SOIL
    ✓ Namelist updated: namelists/Cabauw/OPTIONS.nam_DIFMEB_v9

  (XUNIF_ALBUV_VEG/SOIL are found and left as-is — there are no estimated UV
  values in albedo_estimates.nam to update them with.)

  Processing: DIFMEB_v9DSL
    ...

======================================================================
✅ Updated 2/2 experiment namelists
======================================================================
```

## Validation and Quality Control

### Data Quality Checks

The albedo estimation script performs the following QC checks:

1. **Valid radiation data**: Only observations with non-null SW_OUT and SW_IN are used
2. **Positive SW_IN**: Only records with SW_IN > 0 are selected (daylight condition)
3. **Physical albedo range**: Only daily albedos in [0.0, 1.0] are retained
4. **Temporal coverage**: Monthly averages use all available daily values (partial months acceptable)

### Expected Ranges

Realistic albedo values depend on surface type and season:

| Surface Type | Season | NIR Albedo Range | VIS Albedo Range |
|---|---|---|---|
| Dense vegetation (grass) | Summer | 0.30-0.45 | 0.15-0.25 |
| Dense vegetation (grass) | Winter | 0.25-0.35 | 0.12-0.20 |
| Crops | Growing | 0.25-0.35 | 0.15-0.20 |
| Crops | Harvest | 0.25-0.40 | 0.12-0.25 |
| Bare soil | Wet | 0.15-0.25 | 0.08-0.15 |
| Bare soil | Dry | 0.25-0.40 | 0.15-0.25 |

If estimated albedos fall outside reasonable ranges, check:
- Whether SW_OUT/SW_IN data quality is good
- Presence of clouds in measurements (cloud albedos artificially high)
- Sensor calibration or drift issues

### Diagnostic Output

The script prints monthly albedo values:
```
  Monthly albedo averages:
    Month  1: 0.28905634
    Month  2: 0.29123456
    Month  3: 0.30456789
    ...
```

Plot these values to identify seasonal patterns and anomalies:
```python
import matplotlib.pyplot as plt
months = range(1, 13)
albedo = [0.289, 0.291, 0.304, ...]  # from output
plt.plot(months, albedo, 'o-')
plt.xlabel('Month')
plt.ylabel('Albedo')
plt.title('Seasonal albedo cycle')
plt.show()
```

## Troubleshooting

### Issue: "No SW_OUT/SW_IN data found"

**Causes:**
- Validation data not downloaded (`Get_validation: false`)
- SW_OUT/SW_IN not configured in Validation_data section
- OBSTABLEs not created or corrupted
- SW_OUT/SW_IN values are NULL in database

**Solution:**
1. Check that validation data download completed successfully
2. Verify OBSTABLEs exist: `ls sqlites/OBSTABLES/validation_data/{STATION_NAME}/`
3. Inspect OBSTABLE contents: `sqlite3 sqlites/OBSTABLES/validation_data/{STATION_NAME}/OBSTABLE_YYYY.sqlite "SELECT COUNT(*), COUNT(SW_OUT), COUNT(SW_IN) FROM SYNOP;"`

### Issue: "No midday data found"

**Causes:**
- Observations only available at different UTC times
- Timezone mismatch in OBSTABLEs
- Insufficient daytime data during validation period (e.g., winter at high latitude)

**Solution:**
1. Modify time window in `estimate_albedo.py` (default: 11:00-13:00 UTC)
2. Check UTC times in OBSTABLEs: `sqlite3 sqlites/OBSTABLES/validation_data/{STATION_NAME}/OBSTABLE_YYYY.sqlite "SELECT min(valid_dttm), max(valid_dttm) FROM SYNOP;" | awk '{print strftime("%Y-%m-%d %H:%M:%S", $1), strftime("%Y-%m-%d %H:%M:%S", $2)}'`

### Issue: "Could not calculate daily albedos"

**Causes:**
- Too many unrealistic albedos removed (SW_OUT/SW_IN ratio outside [0,1])
- Measurement issues (e.g., sensor malfunction, wrong units)
- Too few observations in time window

**Solution:**
1. Examine daily albedo calculations manually
2. Relax time window constraints if needed
3. Check units of SW_OUT and SW_IN (must be W/m²)

### Issue: Albedo blocks missing from a namelist

**Behavior:** This is no longer a hard failure. If `update_namelist_albedos.py` doesn't find existing `XUNIF_ALB*` blocks in a namelist, it automatically falls back to inserting all six blocks (estimated NIR/VIS + fixed UV) into the `&NAM_DATA_ISBA` group, just before its closing `/`. You'll see:
```
  ℹ️  No existing albedo blocks found — inserting into &NAM_DATA_ISBA
  ✓ Inserted NIR/VIS/UV SOIL/VEG albedo blocks into &NAM_DATA_ISBA
```

**This can still fail if:**
- The namelist has no `&NAM_DATA_ISBA` group at all → `❌ &NAM_DATA_ISBA group not found in namelist`
- The `&NAM_DATA_ISBA` group's closing `/` can't be located → `❌ Could not find closing '/' for &NAM_DATA_ISBA`
- `albedo_estimates.nam` doesn't contain the expected parameter blocks → `⚠️  Could not extract estimated albedo blocks from albedo file`

**Solution:**
1. Check the namelist actually defines a `&NAM_DATA_ISBA` group: `grep NAM_DATA_ISBA namelists/{STATION_NAME}/OPTIONS.nam_*`
2. Verify `vegtype` matches in both namelist and YAML config
3. Manually locate any existing albedo blocks: `grep XUNIF_ALB namelists/{STATION_NAME}/OPTIONS.nam_*`
4. Check `albedo_estimates.nam` was generated correctly and contains `XUNIF_ALBNIR_VEG`/`XUNIF_ALBVIS_VEG`/`XUNIF_ALBNIR_SOIL`/`XUNIF_ALBVIS_SOIL` blocks

## Advanced Usage

### Customizing NIR vs VIS Albedos

By default, the script uses the same albedo value for both NIR and VIS bands. To differentiate them (e.g., vegetation typically has higher NIR than VIS albedo), modify `estimate_albedo.py`:

In the `main()` function, replace:
```python
nir_albedos = monthly_albedos
vis_albedos = monthly_albedos
```

With a differentiation factor:
```python
# Vegetation typically has higher NIR albedo than VIS
# Use a typical ratio for grass/crop (e.g., NIR = 2.0 × VIS)
nir_ratio = 1.8  # NIR/VIS ratio
vis_albedos = monthly_albedos
nir_albedos = [a * nir_ratio for a in vis_albedos]
```

Then rerun the scripts:
```bash
python3 scripts/python_scripts/estimate_albedo.py Cabauw $OSVAS
python3 scripts/python_scripts/update_namelist_albedos.py Cabauw $OSVAS
```

### Separate Soil and Vegetation Albedos

By default, soil and vegetation use the same estimated values. To differentiate them (e.g., soil typically darker than vegetation), modify the namelist generation in `estimate_albedo.py`:

```python
# Different soil albedo (e.g., 80% of vegetation albedo)
soil_nir_albedos = [a * 0.8 for a in nir_albedos]
soil_vis_albedos = [a * 0.8 for a in vis_albedos]
```

### Running for Multiple Stations

To estimate albedos for all stations in batch:

```bash
for station in Cabauw Loobos Majadas_del_tietar Meteopole; do
    echo "Processing $station..."
    python3 scripts/python_scripts/estimate_albedo.py $station $OSVAS
    python3 scripts/python_scripts/update_namelist_albedos.py $station $OSVAS
done
```

## References

- SURFEX documentation: Surface vegetation Interactions with Growing season inferred from Satellite (SURFEX)
- Briegleb, B. P. (1992), Delta-Eddington approximation for solar radiation in the NCAR Community Climate Model, *J. Geophys. Res.*, 97, 7603–7612.
- Wang, Z., T. L'Ecuyer, R. Sinneroni, S. Kato, and Y. Hu (2015), Cross-validated linear regression for top-of-atmosphere albedo estimation from Clouds and the Earth's Radiant Energy System (CERES) observations, *J. Geophys. Res.*, 120, 6007–6027.

## See Also

- [step2_validation.md](step2_validation.md) - Validation data configuration and download
- [step3_surfex_runs.md](step3_surfex_runs.md) - SURFEX simulation setup
- [config_station.md](config_station.md) - Station configuration reference
