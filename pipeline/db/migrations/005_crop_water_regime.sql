-- 005: crop water regime (DATA-02). Source file: pipeline/crop_traits.csv.
-- wetland = grown in flooded fields; upland = needs drained soil. Used so the rotation options do not put a
-- crop that needs flooding in an upland field, and warn when an upland crop is proposed in a flooded one.
SET search_path TO field_shift;

ALTER TABLE dim_crop ADD COLUMN water_regime text CHECK (water_regime IN ('wetland', 'upland'));
ALTER TABLE dim_crop ADD COLUMN water_regime_source text;

COMMENT ON COLUMN dim_crop.water_regime IS 'wetland (paddy rice, wetland taro) or upland. GAEZ itself distinguishes only rice (RICW/RICD) and taro (TAROWL/TARODL); every other crop is upland by project default (see water_regime_source).';

INSERT INTO schema_migrations (version) VALUES ('005_crop_water_regime');
