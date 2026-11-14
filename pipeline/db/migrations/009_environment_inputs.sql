-- 009: environment inputs for the five priorities (DATA-03): slope, soil quality, crop water demand,
-- ET0 water balance and a relative erosion context. All keyed by region (and month / crop), new tables only.
-- Sources: FAO GAEZ v5 (LR-SLC, SQX, RES05-WDC, RES01-ET0), NASA POWER (ET0 inputs), CHIRPS v3 (rain).
SET search_path TO field_shift;

CREATE TABLE terrain_slope (
  region_id        text PRIMARY KEY REFERENCES dim_region,
  sc01_pct double precision, sc02_pct double precision, sc03_pct double precision, sc04_pct double precision,
  sc05_pct double precision, sc06_pct double precision, sc07_pct double precision, sc08_pct double precision,
  sc09_pct double precision, sc10_pct double precision,
  slope_mean_pct   double precision NOT NULL CHECK (slope_mean_pct BETWEEN 0 AND 100),
  share_gt12_pct   double precision NOT NULL CHECK (share_gt12_pct BETWEEN 0 AND 100),
  share_gt24_pct   double precision NOT NULL CHECK (share_gt24_pct BETWEEN 0 AND 100),
  n_px             smallint NOT NULL CHECK (n_px > 0),
  CHECK (share_gt24_pct <= share_gt12_pct)
);
COMMENT ON TABLE terrain_slope IS 'Share of land (percent) in 10 slope classes (sc01 0-0.5, 02 0.5-2, 03 2-5, 04 5-8, 05 8-12, 06 12-16, 07 16-24, 08 24-30, 09 30-45, 10 >45 percent gradient) around the region, GAEZ LR-SLC 30 arc-seconds from ALOS AW3D30. slope_mean_pct uses class midpoints (55 for the open >45 class). ~1 km pixels: the surroundings, not one field.';

CREATE TABLE soil_quality (
  region_id    text NOT NULL REFERENCES dim_region,
  factor       text NOT NULL CHECK (factor IN ('SQ0', 'SQ1', 'SQ2', 'SQ3', 'SQ4', 'SQ5', 'SQ6', 'SQ7')),
  factor_name  text NOT NULL,
  input_level  text NOT NULL CHECK (input_level IN ('HIM', 'LIM')),
  rating_mean  double precision NOT NULL CHECK (rating_mean BETWEEN 0 AND 1),
  rating_min   double precision CHECK (rating_min BETWEEN 0 AND 1),
  rating_max   double precision CHECK (rating_max BETWEEN 0 AND 1),
  n_px         smallint NOT NULL,
  n_rated      smallint NOT NULL,
  PRIMARY KEY (region_id, factor, input_level),
  CHECK (n_rated > 0 AND n_rated <= n_px)
);
COMMENT ON TABLE soil_quality IS 'GAEZ SQX soil quality ratings (0 worst .. 1 best; SQ0 = most limiting factor, SQ1 nutrient availability, SQ2 nutrient retention, SQ3 rooting, SQ4 oxygen availability, SQ5 salinity/sodicity, SQ6 lime/gypsum, SQ7 workability) for high (HIM) and low (LIM) input management. Class bins 1-10 are turned into their midpoint; water/permafrost/not-evaluated pixels are excluded (n_px - n_rated). HWSD-based, ~1 km: no soil texture, organic carbon or infiltration here.';

CREATE TABLE crop_water_demand (
  region_id   text NOT NULL REFERENCES dim_region,
  crop_code   text NOT NULL REFERENCES dim_crop,
  input_mode  text NOT NULL CHECK (input_mode IN ('HILM', 'LILM')),
  n_px        smallint NOT NULL,
  n_valid     smallint NOT NULL,
  mm_mean     double precision CHECK (mm_mean >= 0),
  mm_median   double precision CHECK (mm_median >= 0),
  mm_max      double precision CHECK (mm_max >= 0),
  PRIMARY KEY (region_id, crop_code, input_mode),
  CHECK (n_valid <= n_px),
  CHECK ((n_valid = 0) = (mm_mean IS NULL))
);
COMMENT ON TABLE crop_water_demand IS 'GAEZ RES05-WDC: water deficit = net irrigation requirement (mm) during the crop cycle, current cropland, 20-year mean 2001-2020, irrigated management levels only (rain-fed levels need none by definition). 0 = no deficit modelled in the cycle, NULL = no data. It is the irrigation need, NOT total crop water use. 5 arc-minute (~9 km) pixels.';

CREATE TABLE water_balance_monthly (
  region_id    text NOT NULL REFERENCES dim_region,
  month        text NOT NULL CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  rain_mm      double precision NOT NULL CHECK (rain_mm >= 0),
  et0_raw_mm   double precision NOT NULL CHECK (et0_raw_mm >= 0),
  et0_mm       double precision NOT NULL CHECK (et0_mm >= 0),
  balance_mm   double precision NOT NULL,
  rain_source  text NOT NULL CHECK (rain_source IN ('chirps', 'power_fallback')),
  PRIMARY KEY (region_id, month),
  CHECK (abs(balance_mm - (rain_mm - et0_mm)) < 0.2)
);
COMMENT ON TABLE water_balance_monthly IS 'Monthly rain (rain_monthly_best, CHIRPS) minus reference evapotranspiration, mm/month. et0_raw_mm = FAO-56 Penman-Monteith from NASA POWER daily; et0_mm = et0_raw_mm x a per-region factor that makes the 11-year mean equal the GAEZ RES01-ET0 layer (factor 1.0 when not applied); see the gold climate block for the factor. ET0 is the reference crop, not a specific crop: multiply by a crop coefficient for a crop.';

CREATE TABLE erosion_context (
  region_id        text PRIMARY KEY REFERENCES dim_region,
  mfi              double precision NOT NULL CHECK (mfi >= 0),
  mfi_class        text NOT NULL CHECK (mfi_class IN ('very_low', 'low', 'moderate', 'high', 'very_high')),
  n_years          smallint NOT NULL CHECK (n_years > 0),
  slope_mean_pct   double precision NOT NULL,
  share_gt12_pct   double precision NOT NULL,
  slope_class      text NOT NULL CHECK (slope_class IN ('low', 'moderate', 'high')),
  base_hazard      text NOT NULL CHECK (base_hazard IN ('low', 'moderate', 'high'))
);
COMMENT ON TABLE erosion_context IS 'RELATIVE erosion context, not tonnes per hectare. mfi = Modified Fournier Index (mean over years of sum(monthly rain^2)/annual rain, CHIRPS); base_hazard is a project rule on slope class and mfi_class, not calibrated for Viet Nam. No soil erodibility or crop cover is included: multiply by crop_profile.erosion_protection.';

INSERT INTO schema_migrations (version) VALUES ('009_environment_inputs');
