-- 008: gaez_suitability (6 demo regions) and the view v_crop_ranking now read the CROPLAND layer RES05-SUX, the
-- same layer as gaez_grid (DATA-04, 14/11). Same columns; only what the numbers mean changes, so only the table
-- documentation changes here. The table is refilled by the next load (full refresh).
SET search_path TO field_shift;

COMMENT ON TABLE gaez_suitability IS 'FAO GAEZ v5 RES05-SUX suitability index 0-10000 (higher = more suitable): average suitability of CURRENT CROPLAND on 5 arc-minute cells (~9 km), the better part of each cell in proportion to its cropland share; the statistics summarize the 2-3 cells per side that cover the region bbox (n_px 4-9, previously 144 pixels). Replaces the total-cell layer RES05-SXX30AS, which includes forest and steep land and understates hilly regions. HILM/LILM irrigated, HRLM/LRLM rain-fed; H/L = high/low inputs. Potential averaged over 20 years (2001-2020), not a yearly value. Can reach 10000, so crops can tie at the top.';

INSERT INTO schema_migrations (version) VALUES ('008_gaez_suitability_cropland');
