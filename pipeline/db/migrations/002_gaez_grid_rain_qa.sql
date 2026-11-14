-- 002: nationwide GAEZ grid (DATA-04) and rain QA flag (DATA-05).
SET search_path TO field_shift;

-- DATA-05: POWER daily rain above the QA limit (config power.rain_qa.max_daily_mm) is stored as NULL
-- with the reason in prectotcorr_qa; it is never replaced by 0. Months/years containing a removed day
-- were recomputed from the remaining days (see gold climate.rain_qa).
ALTER TABLE power_daily ADD COLUMN prectotcorr_qa text;
COMMENT ON COLUMN power_daily.prectotcorr_qa IS 'NULL = value as delivered by POWER. Text = the day was removed by the rain QA rule (prectotcorr is then NULL).';
ALTER TABLE power_daily ADD CONSTRAINT power_daily_rain_qa_null CHECK (prectotcorr_qa IS NULL OR prectotcorr IS NULL);

-- DATA-04: GAEZ suitability for every ~0.1 deg cell of the Vietnam bbox, wide format (one row per cell x crop).
CREATE TABLE gaez_grid (
  lat       double precision NOT NULL,        -- cell centre
  lon       double precision NOT NULL,
  crop_code text NOT NULL REFERENCES dim_crop,
  hilm      smallint CHECK (hilm BETWEEN 0 AND 10000),   -- irrigated, high inputs
  hrlm      smallint CHECK (hrlm BETWEEN 0 AND 10000),   -- rain-fed, high inputs
  lilm      smallint CHECK (lilm BETWEEN 0 AND 10000),   -- irrigated, low inputs
  lrlm      smallint CHECK (lrlm BETWEEN 0 AND 10000),   -- rain-fed, low inputs
  PRIMARY KEY (lat, lon, crop_code)
);
COMMENT ON TABLE gaez_grid IS 'FAO GAEZ v5 RES05-SXX30AS (2001-2020, AgERA5, HIST) averaged into 0.1 deg cells (mean of the valid ~0.9 km pixels). NULL = no valid pixel. The rectangle also covers Laos, Cambodia, southern China and sea edges: the app must only look up points inside Vietnam. Potential suitability, not a yearly value.';
CREATE INDEX ix_gaez_grid_cell ON gaez_grid (lat, lon);

INSERT INTO schema_migrations (version) VALUES ('002_gaez_grid_rain_qa');
