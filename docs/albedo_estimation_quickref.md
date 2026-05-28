# Albedo Estimation - Quick Reference

## TL;DR - Enable Albedo Estimation

### 1. Configure Your Station

Edit your station YAML (e.g., `config_files/Stations/Cabauw/Cabauw.yml`):

```yaml
Station_metadata:
  ...
  estimate_albedo: true
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
2. **Estimates albedos from SW_OUT/SW_IN** (Step 2b) ✨
3. Updates namelists with estimated values
4. Runs SURFEX simulations with new albedos (Step 3)

## What Gets Computed?

- **Midday SZA**: SW_OUT/SW_IN between 11:00-13:00 UTC (high solar elevation)
- **Daily averages**: Mean albedo for each day
- **Monthly values**: Average of daily values per calendar month
- **Four parameters**:
  - `XUNIF_ALBNIR_VEG` - Vegetation NIR
  - `XUNIF_ALBVIS_VEG` - Vegetation VIS
  - `XUNIF_ALBNIR_SOIL` - Soil NIR (same as vegetation initially)
  - `XUNIF_ALBVIS_SOIL` - Soil VIS (same as vegetation initially)

## Output Files

| File | Purpose |
|------|---------|
| `namelists/{station}/albedo_estimates.nam` | Raw albedo namelist blocks |
| `namelists/{station}/OPTIONS.nam_{expname}.backup` | Backup of original namelist |
| `namelists/{station}/OPTIONS.nam_{expname}` | Updated with new albedos |

## Disable Albedo Estimation

Set `estimate_albedo: false` in Station_metadata to skip this step.

## Key Parameters

| Parameter | Value | Notes |
|---|---|---|
| Time window | 11:00-13:00 UTC | High solar angle, minimal geometric effects |
| Minimum SW_IN | 0 | Only daylight conditions |
| Albedo range | [0.0, 1.0] | Remove unphysical values |
| Monthly method | Mean of daily | Simple average |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No SW_OUT/SW_IN data" | Check Validation_data config includes SW_OUT/SW_IN |
| "No midday data" | Check UTC time zone of OBSTABLEs; adjust time window if needed |
| "Albedo values unrealistic" | Check measurement quality; likely sensor issues or calibration drift |
| Namelist update fails | Verify vegtype matches in namelist and YAML config |

## Full Documentation

See [docs/step2b_albedo_estimation.md](step2b_albedo_estimation.md) for detailed information.
