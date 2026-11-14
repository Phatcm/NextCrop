-- 011: which grid cells are inside Viet Nam (DATA-14, 14/11). gaez_grid is the rectangle 102-110E, 8-24N and also
-- holds Laos, Cambodia and southern China. One row per distinct (lat, lon) cell of gaez_grid.
SET search_path TO field_shift;

CREATE TABLE grid_vietnam (
  lat         double precision NOT NULL,        -- cell centre, same values as gaez_grid.lat / lon
  lon         double precision NOT NULL,
  vn_share    double precision NOT NULL CHECK (vn_share BETWEEN 0 AND 1),   -- fraction of the cell area inside Viet Nam
  in_vietnam  boolean NOT NULL,                 -- vn_share >= the threshold in config.yaml (vn_boundary.min_share)
  PRIMARY KEY (lat, lon)
);
COMMENT ON TABLE grid_vietnam IS 'Share of each 5 arc-minute grid cell inside Viet Nam, from the geoBoundaries gbOpen ADM0 polygon (CC BY 4.0, generalised: ~1 km accuracy, an 8 x 8 lattice per cell). Use in_vietnam to refuse points in Laos, Cambodia, China or at sea. The Paracel and Spratly islands are outside the grid cells that hold data.';
CREATE INDEX ix_grid_vietnam_in ON grid_vietnam (in_vietnam);

INSERT INTO schema_migrations (version) VALUES ('011_grid_vietnam');
