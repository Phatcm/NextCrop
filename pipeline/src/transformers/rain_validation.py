"""Independent check of POWER rain against CHIRPS, and the rain series the app should use (DATA-06/07).

Findings that motivate this (see docs/data-issues.md): per-region 2016-2025 mean annual rain
POWER vs CHIRPS vs gauges: Ninh Thuan 2,031 vs 896 (Phan Rang gauge 1966-67: ~780); Son La 1,705 vs 1,370
(Son La gauge 1,348); Dak Lak 2015: POWER 423 vs CHIRPS 1,653. POWER is a model, so it can be off by 2x
where terrain matters. A single reanalysis cannot referee another one (ERA5 is also off in Ninh Thuan and
Dak Lak), which is why a gauge-blended product is used.

Output per region:
  validation rows (region x year): POWER total, CHIRPS total, ratio, status
  monthly rows (region x month):   POWER, CHIRPS, best_mm, best_source  -> `best` is what the app reads
  summary: multi-year bias and a verdict
Rule: best = CHIRPS wherever CHIRPS has the month (same source in every region, so options stay comparable),
otherwise POWER (marked). POWER is never overwritten: silver power_* stays as delivered (after DATA-05 QA).
"""
from __future__ import annotations

import calendar

DEFAULTS = {"max_bias": 0.30, "min_years": 8}


def power_month_mm(monthly_rows: list[dict]) -> dict[str, float]:
    """POWER monthly PRECTOTCORR is mm/day -> mm/month. Months without a value are left out."""
    out = {}
    for r in monthly_rows:
        v = r.get("PRECTOTCORR")
        if v is None:
            continue
        y, m = int(r["month"][:4]), int(r["month"][5:7])
        out[r["month"]] = round(v * calendar.monthrange(y, m)[1], 1)
    return out


def _status(ratio: float, max_bias: float) -> str:
    if ratio > 1 + max_bias:
        return "power_high"
    if ratio < 1 - max_bias:
        return "power_low"
    return "ok"


def validate(power_mm: dict[str, float], chirps_mm: dict[str, float], cfg: dict | None = None) -> dict:
    """{"years": [rows], "monthly": [rows], "summary": {...}} for one region."""
    c = {**DEFAULTS, **(cfg or {})}
    years = sorted({k[:4] for k in power_mm} & {k[:4] for k in chirps_mm})
    rows = []
    for y in years:
        months = [f"{y}-{m:02d}" for m in range(1, 13)]
        if not all(k in power_mm and k in chirps_mm for k in months):
            continue  # only full years are comparable
        p = round(sum(power_mm[k] for k in months), 1)
        ch = round(sum(chirps_mm[k] for k in months), 1)
        ratio = round(p / ch, 3) if ch > 0 else None
        rows.append({"year": int(y), "power_mm": p, "chirps_mm": ch, "ratio": ratio,
                     "status": _status(ratio, c["max_bias"]) if ratio is not None else "no_reference"})
    monthly = []
    for k in sorted(set(power_mm) | set(chirps_mm)):
        ch, p = chirps_mm.get(k), power_mm.get(k)
        best, src = (ch, "chirps") if ch is not None else (p, "power_fallback")
        if best is not None:
            monthly.append({"month": k, "power_mm": p, "chirps_mm": ch, "best_mm": best, "best_source": src})
    n = len(rows)
    summary: dict = {"n_years": n, "max_bias": c["max_bias"]}
    if n:
        mp, mc = sum(r["power_mm"] for r in rows) / n, sum(r["chirps_mm"] for r in rows) / n
        bias = mp / mc - 1 if mc > 0 else None
        bad = [r["year"] for r in rows if r["status"] != "ok"]
        if n < c["min_years"] or bias is None:
            verdict = "insufficient"
        elif abs(bias) > c["max_bias"]:
            verdict = "power_biased"
        elif bad:
            verdict = "power_bad_years"
        else:
            verdict = "power_consistent"
        summary.update({"mean_power_mm": round(mp), "mean_chirps_mm": round(mc),
                        "bias": round(bias, 3) if bias is not None else None,
                        "bad_years": bad, "verdict": verdict})
    else:
        summary["verdict"] = "insufficient"
    return {"years": rows, "monthly": monthly, "summary": summary}


def caveat(summary: dict) -> str | None:
    v = summary.get("verdict")
    if v == "power_biased":
        return (f"Mưa: POWER lệch {summary['bias']:+.0%} so với CHIRPS (trung bình năm {summary['mean_power_mm']} mm "
                f"so với {summary['mean_chirps_mm']} mm); dùng climate.rain_best (CHIRPS), không dùng PRECTOTCORR của POWER.")
    if v == "power_bad_years":
        return (f"Mưa: POWER sai lệch hơn {summary['max_bias']:.0%} so với CHIRPS ở các năm {summary['bad_years']}; "
                f"dùng climate.rain_best (CHIRPS).")
    if v == "insufficient":
        return "Mưa: chưa đủ năm CHIRPS để kiểm chứng POWER; climate.rain_best có thể thiếu."
    return None


def gold_block(result: dict, source_note: str) -> dict:
    """climate.rain_best: monthly normals, per-year totals and the validation table."""
    monthly = result["monthly"]
    norm: list[list[float]] = [[] for _ in range(12)]
    ann: dict[str, float] = {}
    full: dict[str, int] = {}
    for r in monthly:
        norm[int(r["month"][5:7]) - 1].append(r["best_mm"])
        full[r["month"][:4]] = full.get(r["month"][:4], 0) + 1
    for y, n in full.items():
        if n == 12:
            ann[y] = round(sum(r["best_mm"] for r in monthly if r["month"].startswith(y)), 1)
    return {
        "source": source_note,
        "unit": "mm/month",
        "rule": "best = CHIRPS nếu có tháng đó, ngược lại POWER (best_source = power_fallback)",
        "summary": result["summary"],
        "normals_mm": [round(sum(v) / len(v), 1) if v else None for v in norm],
        "annual_mm": ann,
        "validation_by_year": result["years"],
        "monthly": monthly,
    }
