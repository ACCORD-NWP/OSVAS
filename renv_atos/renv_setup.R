#!/usr/bin/env Rscript

#IF R_LIBS_USER is not set, it is set to $HOME/x86_64-pc-linux-gnu-library/{Rversion}
#and the local R libraries are installed there

userlib <- Sys.getenv("R_LIBS_USER")
if (!dir.exists(userlib)) dir.create(userlib, recursive = TRUE)
.libPaths(c(userlib, .libPaths()))


# Github token here if desired
#Sys.setenv(GITHUB_PAT="ADD_YOUR_TOKEN_HERE")

if (!("renv" %in% rownames(installed.packages()))) {
  install.packages("renv",repos="https://cloud.r-project.org")
}

library(renv)
renv::init(bare = T)
renv::snapshot()

install.packages("remotes",repos="https://cloud.r-project.org")

harp_dev_version <- Sys.getenv("HARP_DEV_VERSION")
if (harp_dev_version == "yes") {
  cat("Installing the develop version of harp\n")
  remotes::install_github("harphub/harp", ref = "develop")
} else {
  cat("Installing the main version of harp\n")
  remotes::install_github("harphub/harp")
}
#remotes::install_github("harphub/Rgrib2")
#remotes::install_github("harphub/Rfa")

pkg_list <- c(
  "argparse", "cowplot", "dplyr", "forcats", "ggnewscale", "grid",
  "gridExtra", "here", "lubridate", "ncdf4", "pals", "pracma",
  "purrr", "RColorBrewer", "RSQLite", "scales", "scico",
  "shiny", "shinyWidgets", "stringr", "tidyr", "yaml"
)

for (pkg in pkg_list) {
  install.packages(pkg)
}
