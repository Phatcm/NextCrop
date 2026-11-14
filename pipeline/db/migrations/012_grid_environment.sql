-- 012: slope, soil quality and crop water deficit for every grid cell inside Viet Nam (DATA-17, 14/11).
-- Same GAEZ v5 layers and rules as terrain_slope / soil_quality / crop_water_demand (migration 009), but for the
-- whole nationwide grid, so a point clicked anywhere has the same inputs as the six demo regions.
SET search_path TO field_shift;

CREATE TABLE grid_environment (
  lat                 double precision NOT NULL,       -- cell centre, same values as gaez_grid.lat / lon
  lon                 double precision NOT NULL,
  slope_mean_pct      double precision CHECK (slope_mean_pct >= 0),   -- share-weighted class midpoint, the >45 % class counts 55 %
  share_gt12_pct      double precision CHECK (share_gt12_pct BETWEEN 0 AND 100.01),
  share_gt24_pct      double precision CHECK (share_gt24_pct BETWEEN 0 AND 100.01),
  slope_class         text CHECK (slope_class IN ('low', 'moderate', 'high')),   -- slope half of the erosion rule (no rain)
  n_px_slope          smallint,                        -- ~1 km pixels with land in the cell (max 100)
  soil_limiting_him   double precision CHECK (soil_limiting_him BETWEEN 0 AND 1),   -- SQ0 most limiting rating, high inputs
  soil_limiting_lim   double precision CHECK (soil_limiting_lim BETWEEN 0 AND 1),
  soil_nutrient_him   double precision CHECK (soil_nutrient_him BETWEEN 0 AND 1),   -- SQ1 nutrient availability
  soil_nutrient_lim   double precision CHECK (soil_nutrient_lim BETWEEN 0 AND 1),
  soil_salinity_him   double precision CHECK (soil_salinity_him BETWEEN 0 AND 1),   -- SQ5 salinity and sodicity
  soil_salinity_lim   double precision CHECK (soil_salinity_lim BETWEEN 0 AND 1),
  PRIMARY KEY (lat, lon)
);
COMMENT ON TABLE grid_environment IS 'FAO GAEZ v5 LR-SLC (slope classes, 30 arc-second) and SQX (soil quality ratings, ~1 km) averaged into the 5 arc-minute grid cells inside Viet Nam (grid_vietnam.in_vietnam). Ratings are 0 (worst) to 1 (best) bin midpoints; classes 11-13 (permafrost, not evaluated, water) are not ratings and are excluded. NULL = no valid pixel, never 0. slope_class only reflects terrain: erosion also needs rain erosivity, available only for the demo regions (erosion_context).';

CREATE TABLE grid_water_demand (
  lat         double precision NOT NULL,
  lon         double precision NOT NULL,
  crop_code   text NOT NULL REFERENCES dim_crop,
  input_mode  text NOT NULL CHECK (input_mode IN ('HILM', 'LILM')),   -- irrigated; rain-fed modes need no irrigation by definition
  wdc_mm      double precision NOT NULL CHECK (wdc_mm >= 0),          -- net irrigation requirement during the crop cycle
  PRIMARY KEY (lat, lon, crop_code, input_mode)
);
COMMENT ON TABLE grid_water_demand IS 'FAO GAEZ v5 RES05-WDC water deficit of CURRENT CROPLAND (mm of net irrigation during the crop cycle, 5 arc-minute, same cells as gaez_grid). A missing row means GAEZ has no value for that cell and crop (no cropland or no data), not 0. A 0 row is a real "no deficit modelled".';
CREATE INDEX ix_grid_water_demand_cell ON grid_water_demand (lat, lon);

INSERT INTO schema_migrations (version) VALUES ('012_grid_environment');
