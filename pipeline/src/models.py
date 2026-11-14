from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    bbox: tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max
    status: str = "candidate"
    province_2025: str | None = None
    zone: str | None = None

    @property
    def center(self) -> tuple[float, float]:
        """(lat, lon) of the bbox center."""
        lon_min, lat_min, lon_max, lat_max = self.bbox
        return (round((lat_min + lat_max) / 2, 4), round((lon_min + lon_max) / 2, 4))

    def grid_points(self, n: int) -> list[tuple[float, float]]:
        """n x n (lat, lon) points at cell centers inside the bbox."""
        lon_min, lat_min, lon_max, lat_max = self.bbox
        dlat, dlon = (lat_max - lat_min) / n, (lon_max - lon_min) / n
        return [(round(lat_min + (i + 0.5) * dlat, 5), round(lon_min + (j + 0.5) * dlon, 5))
                for i in range(n) for j in range(n)]

    @classmethod
    def from_dict(cls, d: dict) -> "Region":
        bbox = tuple(float(x) for x in d["bbox"])
        if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            raise ValueError(f"bad bbox for region {d.get('id')}: {d['bbox']}")
        if "__" in d["id"]:
            raise ValueError(f"region id must not contain '__': {d['id']}")
        return cls(id=d["id"], name=d.get("name", d["id"]), bbox=bbox,  # type: ignore[arg-type]
                   status=d.get("status", "candidate"), province_2025=d.get("province_2025"),
                   zone=d.get("zone"))


@dataclass
class NdviObservation:
    """QA metrics for one 16-day composite date. median is None when nothing usable."""
    date: str
    valid_frac: float
    cloud_frac: float
    median: float | None
    mean: float | None = None
    p80: float | None = None
    min: float | None = None
    max: float | None = None
    frac_below_030: float | None = None
    error: str | None = None  # download/decode failure (distinct from a 0 value)


@dataclass
class NdviPoint:
    """Row of the gold NDVI series (data contract: date, median_final, source, flag_bad, reasons)."""
    date: str
    median_raw: float | None
    median_final: float | None
    source: str  # measured | interpolated | missing
    flag_bad: bool
    reasons: list[str] = field(default_factory=list)
    valid_frac: float = 0.0
    cloud_frac: float = 0.0
    smoothed: float | None = None
