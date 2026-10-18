GENERAL INFORMATION

G01. Dataset version 2.1.2
G02. Name of the dataset: Global river flood hazard maps
G03. Description of the dataset: Global river flood hazard maps is a gridded data set representing inundation along the river network, for seven different flood return periods. The input river flow data for the new maps are produced by means of the open-source hydrological model LISFLOOD, while inundation simulations are performed with the hydrodynamic model LISFLOOD-FP.
G04. Creator of data set: Copernicus Emergency Management Service
G05. DOI of dataset: NA
G06. PID of dataset: NA
G07. Keywords (author defined): riverine flood, hazard, global
G08. Language(s) used in the dataset: English
G09. Last update of the README file: 12.01.2026

DATA DESCRIPTION

D01. Horizontal coverage: Global
D02. Horizontal resolution: 3 arc seconds (~90 m)
D03. Spatial gaps: Only land areas are covered by this data set
D04. Temporal coverage: NA
D05. Temporal resolution: NA
D06. Temporal gaps: NA
D07. Number of available variables: 1 (flood water depth)
D08. Variables available at daily resolution: NA
D09. Variables available at 6-hourly resolution: NA
D10. Units: meters
D11. Update frequency: irregular
D12. Projection: wgs_1984
D13. Data type: 3 arc seconds (~90m) grid
D14. Available version(s): 2

PROJECT INFORMATION

P01. Project information: Global river flood hazard maps have been produced as part of the Global Flood Awareness System (GloFAS) of the Copernicus Emergency Management Service.
P02. Project website: https://emergency.copernicus.eu/
P03. Project funder: European Commission

FILE OVERVIEW

F01. Number of files described by the README-file: 542 files of hazard maps per return period which are stored in separate folders for each return period (RP<XXX>/). 271 files for permanent water bodies (Permanent_WaterBodies/). 271 files for spurious depth areas (Spurious_Depth/). A GeoJSON file (tile_extents.geojson) is provided in the main directory and can be used for spatial reference of the tile system.
F02. The different files represent:
(i) Flood hazard map tiles for different return periods. For each return period and for each tile, two maps are provided:
- a raw water depth map, and
- a categorized water depth map consistent with the GloFAS “Flood hazard 100-year return period” static layer, excluding the “Permanent water” class.
Water depth classification:
1: <1 m
2: 1–<3 m
3: 3–<10 m
4: >10 m;
(ii) the permanent water bodies used to patch the flood hazard maps;
(iii) the spurious depth map that identifies areas where depths >10m are predicted in small channels (<3,000km^2) for the 10-year return period, plus a 2km buffer.

Note: Very high water depths may result from limitations in the hydraulic modelling approach, in combination with the spatial resolution, or from artificial sinks in the DEM. In some areas, water depths may also be unrealistic due to boundary effects between individual tiles or due to residual DEM issues. These artefacts are known and users should exercise caution when interpreting depth values in the affected areas.

F03. Naming conventions for file names: <IDXXX_N/SXX_E/WXX_RPXXX>_depth<_reclass>.tif
F04. Explanation of abbreviations: RP = Return period, XXX denotes the return period year or the tile identifier, N/S/W/E - North/South/East/West;
F05. File formats: Tagged Image File Format tif
F06. Software necessary to open the file: any software that opens tif, e.g. ArcGIS, QGIS etc.

STORAGE INFORMATION

S01. Where are the data stored?: JRC Data Store, https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard/

DATA ACCESS AND SHARING

A01. Recommended citation for the dataset: Baugh, Calum; Colonese, Juan; D'Angelo, Claudia; Francesco, Dottori; Neal, Jeffrey; Prudhomme; Christe; Salamon, Peter (2024): Modelled flood inundation for different return period scenarios at the global scale. European Commission, Joint Research Centre (JRC)
A02. License information, restrictions on use: no restrictions, free and open Copernicus product
A03. Copyright statement: https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/copyright.txt
A04. User support service: contact person outlined in the JRC Data Catalogue

RELATIONSHIPS

R01. Reference publication of this dataset: Baugh, Calum; Colonese, Juan; D'Angelo, Claudia; Francesco, Dottori; Neal, Jeffrey; Prudhomme, Christel; Salamon, Peter. (2024): An updated dataset of global and European flood hazard maps. Manuscript under preparation.
R02. Grimaldi, Stefania; Salamon, Peter; Disperati, Juliana; Zsoter, Ervin; Russo, Carlo; Ramos, Arthur; Carton, Corentin; Barnard, Chris; Hansford, Eleanor; Gomes, Goncalo; Prudhomme, Christel (2022): GloFAS v4.0 hydrological reanalysis. European Commission, Joint Research Centre (JRC) [Dataset] PID: http://data.europa.eu/89h/f96b7a19-0133-4105-a879-0536991ca9c5
R03. This dataset incorporates the following other datasets: MERIT-DEM, MERIT-HYDRO, GloFAS v4.0 hydrological reanalysis
