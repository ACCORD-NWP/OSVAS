## Step 6: Display HARP verification results
OSVAS delegates visualization to external tools such as those provided by `oper-harp-verif`.

The Python workflow launcher does not include a dedicated visualization server, but you can use `oper-harp-verif` visualization scripts to inspect HARP output and sqlite results.

Common behavior:
- Visualization apps are typically served as local Shiny apps on ports such as `9999` and `9998`.
- If the apps log output to files, those may include `dynamicapp.log` and `visapp.log`.
- If a port is already in use, stop the conflicting service or change the port mapping in the visualization launcher.

On ATOS, use SSH port forwarding to expose the remote app locally, for example:
```bash
ssh -L 9999:localhost:9999 user@atos-host
```
Then open `http://127.0.0.1:9999/` in a local browser.
