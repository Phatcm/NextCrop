-- 004: independent rain reference (CHIRPS v3) and the rain series the app should use (DATA-06 / DATA-07).
-- POWER rain (MERRA-2 model, ~0.5 deg) is wrong by up to 2-3x in some regions (Ninh Thuan 2,031 mm/yr vs
-- ~900 mm from gauge-blended CHIRPS and ~780 mm from the Phan Rang gauge 1966-67; Dak Lak 2015 = 423 mm vs 1,653 mm).
-- power_daily / power_monthly keep POWER as delivered. The app must read rain from rain_monthly_best.
SET search_path TO field_shift;

CREATE TABLE rain_validation (
  region_id  text NOT NULL REFERENCES dim_region,
  year       smallint NOT NULL,
  power_mm   double precision NOT NULL CHECK (power_mm >= 0),
  chirps_mm  double precision NOT NULL CHECK (chirps_mm >= 0),
  ratio      double precision,                  -- power_mm / chirps_mm; NULL when CHIRPS = 0
  status     text NOT NULL CHECK (status IN ('ok', 'power_high', 'power_low', 'no_reference')),
  PRIMARY KEY (region_id, year)
);
COMMENT ON TABLE rain_validation IS 'Yearly rain total of POWER (sum of monthly mm/day x days) vs CHIRPS v3 at the region centre (~0.15 deg window). status<>ok means POWER differs from CHIRPS by more than config rain_validation.max_bias (30%). Only full years present in both sources.';

CREATE TABLE rain_monthly_best (
  region_id    text NOT NULL REFERENCES dim_region,
  month        text NOT NULL CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  power_mm     double precision CHECK (power_mm >= 0),
  chirps_mm    double precision CHECK (chirps_mm >= 0),
  best_mm      double precision NOT NULL CHECK (best_mm >= 0),
  best_source  text NOT NULL CHECK (best_source IN ('chirps', 'power_fallback')),
  PRIMARY KEY (region_id, month),
  CHECK ((best_source = 'chirps' AND best_mm = chirps_mm) OR (best_source = 'power_fallback' AND best_mm = power_mm AND chirps_mm IS NULL))
);
COMMENT ON TABLE rain_monthly_best IS 'Monthly rain (mm/month) the app should use: CHIRPS where available, POWER only as a marked fallback. Same source for every region so options stay comparable. Satellite+gauge estimate at ~5 km, not a gauge measurement.';

INSERT INTO schema_migrations (version) VALUES ('004_rain_validation');
