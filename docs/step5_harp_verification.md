### Step 5: Run a HARP point verification for the runs
OSVAS currently uses HARP for point verification. When enabled, the workflow copies the HARP YAML template from `config_files/HARP/yaml_files/OSVAS_HARP_verif_template.yml` to `config_files/HARP/yaml_files/OSVAS_HARP_verif_${STATION_NAME}.yml` and updates it with:
- `project_name`
- `fcst_model` (experiment names)
- `fcst_path` (model SQLite outputs)
- `obs_path` (validation obstables)
- `verif_path` and `plot_output`

The verification period is read from `Validation_data.validation_start` and `Validation_data.validation_end`.

The workflow supports HARP verification for variables configured in the YAML template and the selected observation dataset. H and LE are commonly used, but additional variables can be added by editing the HARP YAML template and the station validation configuration.

Outputs are stored in `RUNS/${STATION_NAME}/HARPVERIF/`.
