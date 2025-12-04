## ICOS documentation
### How to find meta data related to diffetent sites
At the ICOS data portal it is far from obvious to find meta data related to each site,  e.g. height of instruments/variables. It seems like the standard way is to first select a site at the ICOS data portal AND then select Data level = 2. Like in this example for Sodankylä:
https://data.icos-cp.eu/portal/#%7B%22filterCategories%22%3A%7B%22level%22%3A%5B2%5D%2C%22station%22%3A%5B%22iES_FI-Sod%22%5D%7D%7D

There, in the list of data objects you find an object called "ETC L2 ARCHIVE from Sodankyla". This is the key object! So, for each ICOS STATION, if you select Data level = 2, you will find this object "ETC L2 ARCHIVE from STATION".

Then go to the object and download the zip file. After unpacking you find files named "*VARINFO*" which includes the meta data on height or depth of observations.

