#!/usr/bin/env Rscript

#IF R_LIBS_USER is not set, it is set to $HOME/x86_64-pc-linux-gnu-library/{Rversion}
#and the local R libraries are installed there

userlib <- Sys.getenv("R_LIBS_USER")
if (!dir.exists(userlib)) dir.create(userlib, recursive = TRUE)
.libPaths(c(userlib, .libPaths()))


# Github token here if desired
#Sys.setenv(GITHUB_PAT="ADD_YOUR_TOKEN_HERE")

# Non-interactive batch mode settings
options(download.file.method = "libcurl")
Sys.setenv(R_REMOTES_NO_ERRORS_FROM_WARNINGS = "true")

# Skip arrow installation - not needed for GRIB/SQLite workflows and
# causes C++20 compiler crash on RHEL 8 / ATOS HPC
Sys.setenv(NOT_CRAN = "false")
options(arrow.skip_nonfatal_install = TRUE)

if (!("renv" %in% rownames(installed.packages()))) {
  install.packages("renv", repos = "https://cloud.r-project.org")
}

library(renv)
renv::init(bare = TRUE)
renv::snapshot()

install.packages("remotes", repos = "https://cloud.r-project.org")

github_pat <- Sys.getenv("GITHUB_PAT")
harp_dev_version <- Sys.getenv("HARP_DEV_VERSION")
if (harp_dev_version == "yes") {
  cat("Installing the develop version of harp\n")
  remotes::install_github("harphub/harp", ref = "develop",
                           auth_token = github_pat, upgrade = "never")
} else {
  cat("Installing the main version of harp\n")
  remotes::install_github("harphub/harp",
                           auth_token = github_pat, upgrade = "never")
}
#remotes::install_github("harphub/Rgrib2", auth_token = github_pat, upgrade = "never")
#remotes::install_github("harphub/Rfa",    auth_token = github_pat, upgrade = "never")

pkg_list <- c(
  "argparse", "cowplot", "dplyr", "forcats", "ggnewscale", "grid",
  "gridExtra", "here", "lubridate", "ncdf4", "pals", "pracma",
  "purrr", "RColorBrewer", "RSQLite", "scales", "scico",
  "shiny", "shinyWidgets", "stringr", "tidyr", "yaml"
)

for (pkg in pkg_list) {
  install.packages(pkg, repos = "https://cloud.r-project.org", upgrade = "never")
}

# Sync lockfile with what is actually installed
renv::snapshot()

