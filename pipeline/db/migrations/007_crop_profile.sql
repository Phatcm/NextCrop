-- 007: crop profile (DATA-01 part 2): GBIF-verified family, Viet Nam price and yield, erosion protection class.
-- Source files: pipeline/crop_profile_map.csv (hand-maintained) + GBIF species match + FAOSTAT bulk (PP, QCL).
-- New table only: dim_crop and crop_traits.csv are not touched.
SET search_path TO field_shift;

CREATE TABLE crop_profile (
  crop_code            text PRIMARY KEY REFERENCES dim_crop,
  scientific_name      text NOT NULL,
  gbif_usage_key       bigint,
  gbif_family          text,
  family_check         text NOT NULL CHECK (family_check IN ('match', 'mismatch', 'unverified')),
  faostat_item_code    integer,
  faostat_item         text,
  faostat_match        text NOT NULL CHECK (faostat_match IN ('direct', 'proxy', 'none')),
  price_usd_per_t      double precision CHECK (price_usd_per_t > 0),
  yield_kg_ha          double precision CHECK (yield_kg_ha > 0),
  econ_year_from       smallint,
  econ_year_to         smallint,
  gross_revenue_usd_ha double precision CHECK (gross_revenue_usd_ha > 0),
  erosion_protection   text NOT NULL CHECK (erosion_protection IN ('high', 'medium', 'low')),
  cover_confidence     text NOT NULL CHECK (cover_confidence IN ('documented_secondary', 'assumed')),
  cover_basis          text NOT NULL,
  CHECK (faostat_match <> 'none' OR (price_usd_per_t IS NULL AND gross_revenue_usd_ha IS NULL)),
  CHECK ((price_usd_per_t IS NULL) = (yield_kg_ha IS NULL) AND (price_usd_per_t IS NULL) = (gross_revenue_usd_ha IS NULL)),
  CHECK (gbif_family IS NOT NULL OR family_check = 'unverified'),
  CHECK (econ_year_from IS NULL OR econ_year_from <= econ_year_to)
);
COMMENT ON TABLE crop_profile IS 'One row per crop. price/yield are FAOSTAT Viet Nam NATIONAL averages (USD/tonne, kg/ha) over econ_year_from..econ_year_to; gross_revenue_usd_ha = price x yield per harvest (annual crops) or per year (perennials), NOT profit (no costs in the data). faostat_match = proxy means another item stands in for the crop (see cover_basis / notes in crop_profile_map.csv); none = no price, left NULL. erosion_protection is a relative class (high/medium/low); cover_confidence = assumed means a project assumption without a read source.';
COMMENT ON COLUMN crop_profile.family_check IS 'gbif_family compared with dim_crop.family: match / mismatch / unverified (GBIF had no answer).';

INSERT INTO schema_migrations (version) VALUES ('007_crop_profile');
