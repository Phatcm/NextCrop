-- 006: gaez_grid now holds the CROPLAND suitability layer on the native 5 arc-minute grid (DATA-04, 14/11).
-- Same columns, different meaning of the values and of the cells, so only the documentation changes here; the
-- table is refilled by the next load (full refresh).
SET search_path TO field_shift;

COMMENT ON TABLE gaez_grid IS 'FAO GAEZ v5 RES05-SUX (2001-2020, AgERA5, historical): average suitability index of CURRENT CROPLAND per 5 arc-minute cell (~9 km), i.e. the better part of the cell in proportion to its cropland share. Replaces the earlier total-cell average aggregated to 0.1 deg (RES05-SXX30AS), which is pulled down by forest and steep land. Values 0-10000 can reach 10000 in good cells, so crops can tie at the top. NULL = no valid value. The rectangle also covers Laos, Cambodia, southern China and sea edges: the app must only look up points inside Vietnam (DATA-14). Potential suitability, not a yearly value.';
COMMENT ON COLUMN gaez_grid.lat IS 'Cell centre latitude: 24 - (i + 0.5)/12, 4 decimals (e.g. 20.4583).';
COMMENT ON COLUMN gaez_grid.lon IS 'Cell centre longitude: 102 + (j + 0.5)/12, 4 decimals (e.g. 106.2917).';

INSERT INTO schema_migrations (version) VALUES ('006_gaez_grid_cropland');
