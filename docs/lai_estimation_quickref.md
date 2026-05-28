# LAI Estimation - Quick Reference

## TL;DR - Enable LAI Estimation

### 1. Configure Your Station

Edit your station YAML (e.g., `config_files/Stations/Cabauw/Cabauw.yml`):

```yaml
Station_metadata:
  ...
  estimate_lai: true
```

### 2. Run OSVAS Workflow

```bash
export STATION_NAME=Cabauw
export OSVAS=$HOME/OSVASgh
export HARPSCRIPTS=$OSVAS/HARPSCRIPTS

python3 scripts/python_scripts/surfex_OSVAS_run_linux.py
```

The workflow automatically:
1. Downloads validation data (Step 2)
2. Estimates surface albedos from observations (Step 2b)
3. **Estimates LAI from CGLS satellite data** (Step 2c) ✨
4. Updates namelists with estimated LAI values
5. Runs SURFEX simulations with new LAI parameters (Step 3)

### 3. First Run: Authenticate

On first run, OIDC authentication is required:
1. Script prints a URL and device code
2. Visit the URL in a browser and enter the code
3. Credentials are cached automatically

Subsequent runs use cached credentials automatically.

## What Gets Computed?

- **Data source**: CGLS LAI from Sentinel-3 OLCI + PROBA-V via openEO BIOPAR process
- **Spatial resolution**: 300 m
- **Temporal resolution**: 10-day composites
- **Processing**: All valid 10-day observations per month → monthly average
- **One parameter**:
  - `XUNIF_LAI` - Vegetation Leaf Area Index [m²/m²]

## Output Files

| File | Purpose |
|------|---------|
| `namelists/{station}/lai_estimates.nam` | Raw LAI namelist blocks |
| `namelists/{station}/OPTIONS.nam_{expname}.backup_lai` | Backup of original namelist |
| `namelists/{station}/OPTIONS.nam_{expname}` | Updated with new LAI |

## Disable LAI Estimation

Set `estimate_lai: false` in Station_metadata to skip this step (not yet implemented in launcher—edit manually).

## Key Parameters

| Parameter | Value | Notes |
|---|---|---|
| Data source | CGLS LAI 300m (BIOPAR) | Via openEO, Copernicus Data Space |
| Fetch method | 10-day composites | Physical LAI units (m²/m²) |
| Monthly aggregation | Mean of 10-day values | Simple average, gap-filled if needed |
| Typical grass LAI | 0.2-0.5 (winter), 2-4 (summer) | Depends on phenology |
| Typical crop LAI | 0.1-0.5 (harvest), 1.5-3.5 (growing) | Seasonal vegetation cycle |
| Saturation limit | ~6-8 m²/m² | Dense forest max (CGLS may saturate) |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No LAI data found" | Extend period: `--run-period 2017-01-01 2018-12-31` or use multi-year: `--start-year 2017 --end-year 2022` |
| "Authentication failed" | Check internet; ensure Copernicus account active (free at https://dataspace.copernicus.eu/) |
| "LAI values unrealistic" | Verify vegetation type matches site; check seasonal patterns plotted |
| Namelist update fails | Verify vegtype is consistent between LAI file and namelist |

## Manual Commands

### Generate LAI estimates only
```bash
python3 scripts/python_scripts/estimate_lai.py Cabauw $OSVAS --run-period 2017-11-01 2018-01-31
```

### Update namelists only
```bash
python3 scripts/python_scripts/update_namelist_lais.py Cabauw $OSVAS
```

### Use pre-computed LAI values (no openEO connection needed)
```bash
python3 scripts/python_scripts/estimate_lai.py Cabauw $OSVAS \
    --print-only \
    --monthly-lai '{"1":0.5,"2":0.4,"3":0.6,"4":0.8,"5":1.2,"6":1.5,"7":1.6,"8":1.4,"9":1.0,"10":0.7,"11":0.5,"12":0.4}'
```

## Full Documentation

See [docs/step2c_lai_estimation.md](step2c_lai_estimation.md) for detailed information.
