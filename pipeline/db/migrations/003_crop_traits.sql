-- 003: crop traits in dim_crop (DATA-01). Source file: pipeline/crop_traits.csv (every row names its source).
-- All columns are nullable on purpose: NULL = no source found, the app must show "missing", never assume.
SET search_path TO field_shift;

ALTER TABLE dim_crop ADD COLUMN res02_code text;
ALTER TABLE dim_crop ADD COLUMN gaez_group text;
ALTER TABLE dim_crop ADD COLUMN life_cycle text CHECK (life_cycle IN ('annual', 'perennial'));
ALTER TABLE dim_crop ADD COLUMN is_legume boolean;
ALTER TABLE dim_crop ADD COLUMN family text;
ALTER TABLE dim_crop ADD COLUMN cycle_days_min smallint CHECK (cycle_days_min > 0);
ALTER TABLE dim_crop ADD COLUMN cycle_days_max smallint CHECK (cycle_days_max > 0);
ALTER TABLE dim_crop ADD COLUMN min_temp_c double precision;
ALTER TABLE dim_crop ADD COLUMN traits_source text;
ALTER TABLE dim_crop ADD COLUMN family_source text;
ALTER TABLE dim_crop ADD COLUMN notes text;
ALTER TABLE dim_crop ADD CONSTRAINT dim_crop_cycle_order CHECK (cycle_days_min <= cycle_days_max);
ALTER TABLE dim_crop ADD CONSTRAINT dim_crop_perennial_no_cycle CHECK (life_cycle IS NULL OR life_cycle <> 'perennial' OR cycle_days_min IS NULL);

COMMENT ON COLUMN dim_crop.res02_code IS 'GAEZ RES02 crop code (growth-cycle layers); differs from crop_code (RES05). COCO is cacao, coconut is COCN.';
COMMENT ON COLUMN dim_crop.gaez_group IS 'GAEZ crop group (Appendix 4-1). Not a botanical family.';
COMMENT ON COLUMN dim_crop.life_cycle IS 'GAEZ Appendix 4-6 annual/perennial flag where a row exists, otherwise general knowledge (see notes). Perennials are not rotated by season.';
COMMENT ON COLUMN dim_crop.is_legume IS 'Nitrogen-fixing legume (GAEZ Appendix 4-6 flag).';
COMMENT ON COLUMN dim_crop.family IS 'Botanical family, used to avoid two crops of the same family in a row. Standard classification, not yet checked against a cited source (family_source).';
COMMENT ON COLUMN dim_crop.cycle_days_min IS 'Shortest to longest candidate cultivar cycle (days) GAEZ tests (A4-6.1). GAEZ layer CYL reports the one with the highest potential yield, usually the longest, which is NOT the typical Vietnamese practice.';
COMMENT ON COLUMN dim_crop.min_temp_c IS 'Column "Minimum temperature" of GAEZ A4-6.1; the exact meaning is defined in Appendix 4-5 and was not read yet.';

INSERT INTO schema_migrations (version) VALUES ('003_crop_traits');
