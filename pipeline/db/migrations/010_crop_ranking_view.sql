-- 010: v_crop_ranking carries the crop traits the app needs to keep perennial crops out of the rotation ranking
-- (DATA-15, 14/11). New columns are appended after the existing ones, so queries that already use the view keep
-- working. rank_annual ranks only annual crops within each region and input mode and is NULL for every other crop.
SET search_path TO field_shift;

CREATE OR REPLACE VIEW v_crop_ranking AS
SELECT g.region_id, g.input_mode, g.crop_code, c.name_vi, c.name_verified, g.value_mean, g.value_center,
       rank() OVER (PARTITION BY g.region_id, g.input_mode ORDER BY g.value_mean DESC NULLS LAST) AS rank,
       c.life_cycle, c.gaez_group, c.water_regime,
       CASE WHEN c.life_cycle = 'annual' THEN
            rank() OVER (PARTITION BY g.region_id, g.input_mode, (c.life_cycle = 'annual')
                         ORDER BY g.value_mean DESC NULLS LAST)
       END AS rank_annual
FROM gaez_suitability g JOIN dim_crop c USING (crop_code);

COMMENT ON VIEW v_crop_ranking IS 'GAEZ suitability ranking of the crops of each demo region and input mode. rank covers all 24 crops including perennials (coconut, coffee, oil palm...), which are NOT rotation candidates: for rotation use rank_annual (annual crops only, NULL for the others) or filter life_cycle = annual. gaez_group is the GAEZ crop group, water_regime is wetland or upland. Ties share a rank because the index can reach 10000.';

INSERT INTO schema_migrations (version) VALUES ('010_crop_ranking_view');
