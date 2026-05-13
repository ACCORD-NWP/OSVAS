## Step 6: Display HARP verification results

### Visualization apps
OSVAS uses Shiny apps from the `oper-harp-verif` project to visualize HARP verification results. Two complementary visualization approaches are available:

1. **Dynamic App** (port 9999): Interactive Shiny app for exploring verification statistics by variable, location, and metric
2. **Static Visualization** (port 9998): Generates and displays pre-rendered plots from verification outputs

### Intelligent port detection and app management
When Step 6 is enabled, the launcher performs intelligent port detection before launching visualization apps:

- **Both ports available:** Launches both dynamic and static apps in background processes
- **Port 9999 in use:** Dynamic app is already running; only launches static app if port 9998 is free
- **Port 9998 in use:** Static visualization already running; only launches dynamic app if port 9999 is free
- **Both ports in use:** Both apps are already running; no action taken

This allows you to run the workflow multiple times without port conflicts or errors.

### Accessing the apps

**Local system:**
- Dynamic app: http://localhost:9999/
- Static visualization: http://localhost:9998/

**Remote system (ATOS via SSH):**
Use SSH port forwarding to expose remote apps locally:
```bash
ssh -L 9999:localhost:9999 -L 9998:localhost:9998 user@atos-host
```

Then access apps at:
- http://localhost:9999/ (dynamic)
- http://localhost:9998/ (static)

### Troubleshooting visualization apps

**Apps not loading or crashing:**
- Check log files: `$OSVAS/dynamicapp.log` and `$OSVAS/visapp.log`
- Restart the apps by killing them and re-running the workflow

**Port still in use after stopping apps:**
```bash
# Find and kill process on port 9999
lsof -ti:9999 | xargs kill -9

# Find and kill process on port 9998
lsof -ti:9998 | xargs kill -9
```

**Verification output locations:**
- HARP verification outputs: `RUNS/${STATION_NAME}/HARPVERIF/`
- Verification statistics figures and tables are stored in this directory and displayed by the apps
