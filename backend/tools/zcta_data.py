import geopandas as gpd
import pandas as pd
import requests

# 1. Load ZCTA polygon shapefile directly from Census Bureau
shapefile_url = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip"
gdf = gpd.read_file(shapefile_url)

# 2. Fetch Total Population (B01003) via the Census API
api_url = "https://api.census.gov/data/2022/acs/acs5?get=B01003_001E&for=zip%20code%20tabulation%20area:*"
resp = requests.get(api_url).json()
pop_df = pd.DataFrame(resp[1:], columns=resp[0])
pop_df.rename(
    columns={"B01003_001E": "population", "zip code tabulation area": "ZCTA5CE20"},
    inplace=True,
)
pop_df["population"] = pd.to_numeric(pop_df["population"])

# 3. Merge attributes and calculate density (ALAND20 is in square meters)
gdf = gdf.merge(pop_df, on="ZCTA5CE20")
gdf["land_sq_mi"] = gdf["ALAND20"] / 2_589_988.110336
gdf["pop_density_sq_mi"] = gdf["population"] / gdf["land_sq_mi"]

# 4. Save to GeoParquet or Shapefile
gdf.to_parquet("us_zcta_density_2020.parquet")