-- 001_init: relational model of the pipeline's silver layer for the Field Shift app (PostgreSQL 14+).
-- One table per silver dataset, same names and columns, so loading is a plain COPY of the silver CSVs.
-- Dates are DATE, missing values are NULL (never 0). Everything lives in schema field_shift:
--   app connections should set  search_path = field_shift  (or qualify names).

CREATE SCHEMA IF NOT EXISTS field_shift;
SET search_path TO field_shift;

CREATE TABLE schema_migrations (
  version     text PRIMARY KEY,
  applied_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pipeline_run (               -- lineage: which R2 run produced the data currently loaded
  run_id               text PRIMARY KEY,
  loaded_at            timestamptz NOT NULL DEFAULT now(),
  manifest_key         text,
  gold_schema_version  text,
  row_counts           jsonb NOT NULL
);

CREATE TABLE dim_region (
  region_id             text PRIMARY KEY,
  name                  text NOT NULL,
  status                text NOT NULL CHECK (status IN ('sample', 'candidate')),
  province_2025         text,
  zone                  text,
  lon_min double precision NOT NULL, lat_min double precision NOT NULL,
  lon_max double precision NOT NULL, lat_max double precision NOT NULL,
  center_lat double precision NOT NULL, center_lon double precision NOT NULL,
  year_start            smallint,
  year_end              smallint,
  ndvi_primary          text,
  mcd12q1_cropland_frac double precision CHECK (mcd12q1_cropland_frac BETWEEN 0 AND 1),
  mcd12q1_dominant      text,
  mcd12q1_is_cropland   boolean,
  gfsad_bbox_crop_frac  double precision CHECK (gfsad_bbox_crop_frac BETWEEN 0 AND 1),
  CHECK (lon_min < lon_max AND lat_min < lat_max)
);
COMMENT ON TABLE dim_region IS 'Demo regions (bbox ~0.1 deg). status=candidate means coordinates are not yet confirmed on the ground.';

CREATE TABLE dim_crop (
  crop_code      text PRIMARY KEY,           -- FAO GAEZ 3-5 letter code (RCW, MZE, ...)
  name_vi        text NOT NULL,
  name_verified  boolean NOT NULL            -- false: value matched the GAEZ portal, name not officially confirmed
);

CREATE TABLE power_daily (
  region_id text NOT NULL REFERENCES dim_region,
  date      date NOT NULL,
  t2m double precision, t2m_max double precision, t2m_min double precision,
  prectotcorr double precision CHECK (prectotcorr >= 0),
  rh2m double precision CHECK (rh2m BETWEEN 0 AND 100),
  ws2m double precision, allsky_sfc_sw_dwn double precision,
  gwetroot double precision, gwettop double precision,
  PRIMARY KEY (region_id, date)
);
COMMENT ON TABLE power_daily IS 'NASA POWER daily, local solar time (LST). Model/reanalysis (MERRA-2), ~0.5 deg: not field scale. GWET* are model outputs, not satellite.';

CREATE TABLE power_monthly (
  region_id text NOT NULL REFERENCES dim_region,
  month     text NOT NULL CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  allsky_sfc_sw_dwn double precision, gwetroot double precision, gwettop double precision,
  prectotcorr double precision, rh2m double precision,
  t2m double precision, t2m_max double precision, t2m_min double precision, ws2m double precision,
  PRIMARY KEY (region_id, month)
);

CREATE TABLE ndvi_series (
  region_id    text NOT NULL REFERENCES dim_region,
  source_key   text NOT NULL CHECK (source_key IN ('modis_qa', 'gibs')),
  date         date NOT NULL,
  median_raw   double precision,
  median_final double precision CHECK (median_final BETWEEN -0.2 AND 1),
  source       text NOT NULL CHECK (source IN ('measured', 'interpolated', 'missing')),
  flag_bad     boolean NOT NULL,
  reasons      text,                          -- '|' separated QA reasons
  valid_frac   double precision, cloud_frac double precision, smoothed double precision,
  PRIMARY KEY (region_id, source_key, date),
  CHECK (source <> 'missing' OR median_final IS NULL)
);
COMMENT ON TABLE ndvi_series IS 'NDVI per 16-day composite after QA. source=interpolated rows are NOT measurements and must be shown as such.';

CREATE TABLE ndvi_raw (
  region_id  text NOT NULL REFERENCES dim_region,
  source_key text NOT NULL CHECK (source_key IN ('modis_qa', 'gibs')),
  date       date NOT NULL,
  valid_frac double precision, cloud_frac double precision,
  median double precision, mean double precision, p80 double precision,
  min double precision, max double precision, frac_below_030 double precision,
  error      text,
  PRIMARY KEY (region_id, source_key, date)
);

CREATE TABLE smap_daily (
  region_id      text NOT NULL REFERENCES dim_region,
  date           date NOT NULL,
  sm_recommended double precision,            -- NULL when SMAP flags the retrieval as not recommended (dense vegetation)
  sm_all         double precision CHECK (sm_all > 0 AND sm_all < 1),
  PRIMARY KEY (region_id, date)
);

CREATE TABLE gfsad_points (
  region_id text NOT NULL REFERENCES dim_region,
  point     text PRIMARY KEY,
  lat double precision NOT NULL, lon double precision NOT NULL,
  crop_frac double precision CHECK (crop_frac BETWEEN 0 AND 1),
  n_px      integer
);

CREATE TABLE landcover_by_year (
  region_id text NOT NULL REFERENCES dim_region,
  year      smallint NOT NULL,
  n_points  integer, cropland_frac double precision CHECK (cropland_frac BETWEEN 0 AND 1), dominant text,
  PRIMARY KEY (region_id, year)
);

CREATE TABLE landcover_classes (
  region_id  text NOT NULL REFERENCES dim_region,
  year       smallint NOT NULL,
  class_name text NOT NULL,
  frac       double precision CHECK (frac BETWEEN 0 AND 1),
  PRIMARY KEY (region_id, year, class_name)
);

CREATE TABLE terrain (
  region_id text PRIMARY KEY REFERENCES dim_region,
  median_m double precision, min_m double precision, max_m double precision, n_points integer
);

CREATE TABLE gaez_suitability (
  region_id    text NOT NULL REFERENCES dim_region,
  crop_code    text NOT NULL REFERENCES dim_crop,
  input_mode   text NOT NULL CHECK (input_mode IN ('HILM', 'HRLM', 'LILM', 'LRLM')),
  period       text NOT NULL,                 -- HP0120 = 2001-2020
  climate      text NOT NULL,
  ssp          text NOT NULL,
  n_px         integer NOT NULL,
  n_valid      integer NOT NULL,
  value_mean   double precision CHECK (value_mean BETWEEN 0 AND 10000),
  value_median double precision CHECK (value_median BETWEEN 0 AND 10000),
  value_min    double precision, value_max double precision,
  value_center double precision,
  PRIMARY KEY (region_id, crop_code, input_mode, period, ssp)
);
COMMENT ON TABLE gaez_suitability IS 'FAO GAEZ v5 RES05-SXX30AS suitability index 0-10000 (higher = more suitable), mean over the region bbox window (~0.9 km pixels). HILM/LILM irrigated, HRLM/LRLM rain-fed; H/L = high/low inputs. Potential averaged over 20 years, not a yearly value.';

CREATE TABLE vn_grid_monthly (               -- nationwide POWER grid, long format
  lat double precision NOT NULL, lon double precision NOT NULL,
  param text NOT NULL, yyyymm integer NOT NULL, value double precision,
  PRIMARY KEY (lat, lon, param, yyyymm)
);

CREATE INDEX ix_power_daily_date    ON power_daily (date);
CREATE INDEX ix_ndvi_series_date    ON ndvi_series (date);
CREATE INDEX ix_gaez_rank           ON gaez_suitability (region_id, input_mode, value_mean DESC);

-- App-facing views ---------------------------------------------------------------------------
CREATE VIEW v_region_overview AS
SELECT r.*,
       (SELECT count(*) FROM ndvi_series n WHERE n.region_id = r.region_id AND n.source_key = 'modis_qa') AS ndvi_dates,
       (SELECT count(*) FROM ndvi_series n WHERE n.region_id = r.region_id AND n.source_key = 'modis_qa'
                                              AND n.source = 'measured')                                  AS ndvi_measured,
       (SELECT count(*) FROM smap_daily s WHERE s.region_id = r.region_id)                                AS smap_days,
       (SELECT round(CAST(100.0 * count(s.sm_recommended) / NULLIF(count(*), 0) AS numeric), 0)
          FROM smap_daily s WHERE s.region_id = r.region_id)                                              AS smap_recommended_pct
FROM dim_region r;

CREATE VIEW v_crop_ranking AS
SELECT g.region_id, g.input_mode, g.crop_code, c.name_vi, c.name_verified, g.value_mean, g.value_center,
       rank() OVER (PARTITION BY g.region_id, g.input_mode ORDER BY g.value_mean DESC NULLS LAST) AS rank
FROM gaez_suitability g JOIN dim_crop c USING (crop_code);

INSERT INTO schema_migrations (version) VALUES ('001_init');
