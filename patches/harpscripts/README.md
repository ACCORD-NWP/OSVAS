# HARPSCRIPTS git-apply patches

Use these patch files to apply the OSVAS HARPSCRIPTS changes directly via `git apply`.

From the repository root:

```bash
bash patches/harpscripts/apply_harpscripts_patches.sh
```

This script changes into `HARPSCRIPTS` and applies the six patch files in order.

If the patches fail because the repository is already modified, reset or reclone `HARPSCRIPTS` before running.
