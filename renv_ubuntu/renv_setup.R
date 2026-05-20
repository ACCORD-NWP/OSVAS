#!/usr/bin/env Rscript
# renv_setup.R
# Sets up an renv environment and installs HARP + dependencies.
# Designed to run on any Linux system (Ubuntu, ATOS, etc.).
# Called by ubuntu_harp_setup.sh, but can also be run standalone:
#   Rscript renv_setup.R

# ---------------------------------------------------------------------------
# R_LIBS_USER: fall back to a portable default if not set by the caller
# ---------------------------------------------------------------------------
userlib <- Sys.getenv("R_LIBS_USER")
if (nchar(userlib) == 0) {
  rv <- paste(R.version$major, substr(R.version$minor, 1, 1), sep = ".")
  userlib <- file.path(Sys.getenv("HOME"), "R",
                       "x86_64-pc-linux-gnu-library", rv)
}
if (!dir.exists(userlib)) dir.create(userlib, recursive = TRUE)
.libPaths(c(userlib, .libPaths()))

# ---------------------------------------------------------------------------
# Optional: set your GitHub PAT to avoid rate-limiting on installs
# (more info here https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/
# /managing-your-personal-access-tokens
# ---------------------------------------------------------------------------
 Sys.setenv(GITHUB_PAT = "Put_your_github_personal_access_token_here")

# ---------------------------------------------------------------------------
# CRAN mirror
# ---------------------------------------------------------------------------
options(repos = c(CRAN = "https://cloud.r-project.org"))

# ---------------------------------------------------------------------------
# Bootstrap renv
# ---------------------------------------------------------------------------
if (!("renv" %in% rownames(installed.packages()))) {
  install.packages("renv")
}
library(renv)

# init(bare=TRUE): creates renv infrastructure without installing anything yet.
# We snapshot AFTER installing so the lockfile captures all packages.
renv::init(bare = TRUE)

# ---------------------------------------------------------------------------
# remotes: needed to install from GitHub
# ---------------------------------------------------------------------------
install.packages("remotes")

# ---------------------------------------------------------------------------
# HARP
# ---------------------------------------------------------------------------
harp_dev_version <- Sys.getenv("HARP_DEV_VERSION")
if (identical(harp_dev_version, "yes")) {
  cat("==> Installing the develop branch of harp\n")
  remotes::install_github("harphub/harp", ref = "develop")
} else {
  cat("==> Installing the main branch of harp\n")
  remotes::install_github("harphub/harp")
}

# Uncomment if you also need Rgrib2 or Rfa:
# remotes::install_github("harphub/Rgrib2")
# remotes::install_github("harphub/Rfa")

# ---------------------------------------------------------------------------
# Additional packages used by verification / plotting workflows
# ---------------------------------------------------------------------------
pkg_list <- c(
  "argparse", "cowplot", "dplyr", "forcats", "ggnewscale", "grid",
  "gridExtra", "here", "lubridate", "ncdf4", "pals", "pracma",
  "purrr", "RColorBrewer", "RSQLite", "scales", "scico",
  "shiny", "shinyWidgets", "stringr", "tidyr", "yaml"
)

cat("==> Installing additional packages:", paste(pkg_list, collapse = ", "), "\n")
install.packages(pkg_list)

# ---------------------------------------------------------------------------
# Snapshot: lock all installed packages into renv.lock NOW that everything
# is installed (snapshotting before installation would capture nothing).
# ---------------------------------------------------------------------------
cat("==> Writing renv.lock\n")
renv::snapshot()

cat("\n==> renv_setup.R complete.\n")
cat("    renv.lock written. Commit it to version control to ensure\n")
cat("    reproducible installs via renv::restore().\n")
