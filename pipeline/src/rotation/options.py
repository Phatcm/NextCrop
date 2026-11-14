"""Rotation options for one location and one current crop (DATA-02).

Season-level rules, NOT a calendar simulation: the app is decision support, and the data does not allow more.
- GAEZ gives one optimal start day per crop standing alone, not a day for a crop that follows another, and
  the day is noisy between neighbouring cells. So the order of the seasons is NOT scheduled (see `assumptions`).
- GAEZ cycle length is the model's pick among candidate cultivars (usually the longest); here the SHORTEST
  candidate (`cycle_days_min`) is used so that multi-cropping is not ruled out. Real cycles can be longer.

Four templates of small change, each shown with its components. There is no single total score: a total would
only restate the weights chosen here, which are not evidence.
  keep          current crop in every season (baseline)
  legume        one season replaced by the best nitrogen-fixing legume
  other_family  one season replaced by the best crop of another family (not a legume)
  diverse       n-1 seasons replaced (n if n == 2): every crop from a different family, a legume if possible
"""
from __future__ import annotations

import itertools

YEAR_DAYS = 365
BUFFER_DAYS = 15          # land preparation + harvest gap between two crops (project assumption, not GAEZ)
MAX_SEASONS = 3
MIN_RATIO = 0.6           # an alternative must reach 60% of the current crop's GAEZ index (project heuristic)
POOL = 8                  # best candidates searched for the "diverse" template

GAEZ_SOURCE = "FAO GAEZ v5 RES05-SXX30AS, 2001-2020, AgERA5, historical; cell mean of ~0.9 km pixels"
SUPPORTED_PRIORITIES = {"nitrogen": "cây họ đậu trước", "pest_cycle": "ít cặp vụ liên tiếp cùng họ trước",
                        "yield": "điểm GAEZ trung bình cao trước"}
UNSUPPORTED_PRIORITIES = {"water": "chưa nạp thiếu nước (GAEZ RES02-WDE)", "erosion": "chưa có độ phủ đất",
                          "income": "chưa có giá nông sản", "soil": "chưa có dữ liệu đất"}
MISSING_ALWAYS = ["giá nông sản (ưu tiên thu nhập)", "độ phủ đất và xói mòn", "đất (kết cấu, hữu cơ)",
                  "thời gian chuyển vụ thực tế và lịch gieo từng vụ"]
ASSUMPTIONS = {
    "season_order": "Thứ tự các vụ chưa được xếp lịch; chỉ xét bộ cây trong một năm.",
    "cycle_days": "Độ dài vụ lấy giống ngắn nhất GAEZ thử (cycle_days_min); thực tế có thể dài hơn.",
    "buffer_days": BUFFER_DAYS, "min_ratio": MIN_RATIO,
    "gaez": "Chỉ số phù hợp là tiềm năng (0–10000), không phải năng suất thực tế.",
}


def _usable(c: dict) -> bool:
    return c.get("life_cycle") == "annual" and c.get("cycle_days_min") is not None


def seasons_for(cur: dict) -> int:
    """How many crops of the current kind fit in a year (1..MAX_SEASONS)."""
    return max(1, min(MAX_SEASONS, YEAR_DAYS // (cur["cycle_days_min"] + BUFFER_DAYS)))


def fits(seq: list[str], crops: dict[str, dict]) -> bool:
    return sum(crops[c]["cycle_days_min"] for c in seq) + BUFFER_DAYS * len(seq) <= YEAR_DAYS


def eligible(cur_code: str, crops: dict[str, dict], suit: dict[str, int | None],
             min_ratio: float = MIN_RATIO) -> list[str]:
    """Annual crops that may replace a season, best GAEZ index first."""
    cur, cur_suit = crops[cur_code], suit.get(cur_code)
    floor = min_ratio * cur_suit if cur_suit else 0
    out = []
    for code, c in crops.items():
        v = suit.get(code)
        if code == cur_code or not _usable(c) or not v or v <= 0 or v < floor:
            continue
        if cur["water_regime"] == "upland" and c["water_regime"] == "wetland":
            continue                                        # a flooded crop cannot go into an upland field
        out.append(code)
    return sorted(out, key=lambda k: (-suit[k], k))


def components(seq: list[str], crops: dict[str, dict], suit: dict[str, int | None]) -> dict:
    vals = [suit.get(c) for c in seq]
    known = [v for v in vals if v is not None]
    n = len(seq)
    same = sum(crops[seq[i]]["family"] == crops[seq[(i + 1) % n]]["family"] for i in range(n)) if n > 1 else 0
    days = sum(crops[c]["cycle_days_min"] for c in seq)
    return {"gaez_mean": round(sum(known) / len(known)) if known else None,
            "same_family_adjacent": same,
            "has_legume": any(crops[c]["is_legume"] for c in seq),
            "families": sorted({crops[c]["family"] for c in seq}),
            "cycle_days_total": days, "days_with_buffer": days + BUFFER_DAYS * n,
            "fits_year": fits(seq, crops)}


def _describe(opt_id: str, label: str, seq: list[str], cur_code: str, crops: dict, suit: dict, mode: str,
              base_mean: int | None) -> dict:
    comp = components(seq, crops, suit)
    cur = crops[cur_code]
    benefits, risks = [], []
    if comp["has_legume"] and not cur["is_legume"]:
        legs = sorted({crops[c]["name_vi"] for c in seq if crops[c]["is_legume"]})
        benefits.append(f"Có cây họ đậu ({', '.join(legs)}): cố định đạm theo cờ họ đậu của GAEZ A4-6.1.")
    if seq != [cur_code] * len(seq) and comp["same_family_adjacent"] < components([cur_code] * len(seq), crops, suit)["same_family_adjacent"]:
        benefits.append("Giảm số cặp vụ liên tiếp cùng họ, hạn chế sâu bệnh tích lũy theo họ thực vật.")
    if comp["same_family_adjacent"]:
        risks.append(f"Còn {comp['same_family_adjacent']} cặp vụ liên tiếp cùng họ: nguy cơ sâu bệnh tích lũy.")
    if (base_mean is not None and comp["gaez_mean"] is not None and comp["gaez_mean"] < base_mean - 500):
        risks.append(f"Điểm GAEZ trung bình thấp hơn phương án hiện tại {base_mean - comp['gaez_mean']} điểm "
                     f"({comp['gaez_mean']} so với {base_mean}).")
    if cur["water_regime"] == "wetland" and any(crops[c]["water_regime"] == "upland" for c in seq):
        ups = sorted({crops[c]["name_vi"] for c in seq if crops[c]["water_regime"] == "upland"})
        risks.append(f"Cây cạn ({', '.join(ups)}) trên ruộng quen ngập: cần thoát nước và làm đất. "
                     "Chế độ nước của cây cạn là mặc định của dự án, GAEZ không phân biệt.")
    risks.append("Độ dài vụ lấy giống ngắn nhất GAEZ thử; vụ thực tế có thể dài hơn và không còn vừa một năm.")
    evidence = [{"crop_code": c, "name_vi": crops[c]["name_vi"], "gaez_index": suit.get(c), "mode": mode,
                 "cycle_days_min": crops[c]["cycle_days_min"], "family": crops[c]["family"],
                 "is_legume": crops[c]["is_legume"], "water_regime": crops[c]["water_regime"]} for c in seq]
    return {"id": opt_id, "label": label, "sequence": seq, "names": [crops[c]["name_vi"] for c in seq],
            "components": comp, "benefits": benefits, "risks": risks, "evidence": evidence,
            "evidence_source": GAEZ_SOURCE}


def _best_diverse(cur_code: str, n: int, replace: int, pool: list[str], crops: dict, suit: dict) -> list[str] | None:
    """Keep cur in (n - replace) seasons; fill `replace` seasons with crops of pairwise different families,
    all different from cur, a legume among them when the pool has one. Best GAEZ mean wins."""
    keep = [cur_code] * (n - replace)
    best, best_key = None, None
    for combo in itertools.combinations(pool[:POOL], replace):
        fams = [crops[c]["family"] for c in combo] + ([crops[cur_code]["family"]] if keep else [])
        if len(set(fams)) != len(fams):
            continue
        seq = keep + list(combo)
        if not fits(seq, crops):
            continue
        has_leg = any(crops[c]["is_legume"] for c in combo)
        key = (has_leg, sum(suit[c] for c in combo), tuple(-ord(ch) for ch in "".join(combo)))
        if best_key is None or key > best_key:
            best, best_key = seq, key
    return best


def generate(cur_code: str, crops: dict[str, dict], suit: dict[str, int | None], *, mode: str = "hrlm",
             seasons: int | None = None, priorities: list[str] | None = None,
             min_ratio: float = MIN_RATIO) -> dict:
    """crops: {code: {name_vi, life_cycle, is_legume, family, cycle_days_min, water_regime}} (dim_crop).
    suit: {crop_code: GAEZ index 0-10000 or None} for the clicked cell and input mode.
    Returns {"options": [...], "skipped": [...], ...}; options[0] is always the current practice.
    `sequence` is a canonical listing (kept crops first, then replacements by GAEZ index), not a schedule."""
    if cur_code not in crops:
        raise ValueError(f"unknown crop {cur_code!r}")
    cur = crops[cur_code]
    prios = [p for p in (priorities or ["yield"])]
    unsupported = [{"priority": p, "reason": UNSUPPORTED_PRIORITIES.get(p, "không có trong bộ ưu tiên đã hỗ trợ")}
                   for p in prios if p not in SUPPORTED_PRIORITIES]
    base = {"current": cur_code, "mode": mode, "assumptions": ASSUMPTIONS, "missing": MISSING_ALWAYS,
            "unsupported_priorities": unsupported, "options": [], "skipped": []}
    if cur.get("life_cycle") != "annual" or cur.get("cycle_days_min") is None:
        base["message"] = (f"{cur['name_vi']} là cây lâu năm hoặc chưa có độ dài vụ trong dữ liệu GAEZ: "
                           "không luân canh theo vụ, không sinh phương án.")
        return base
    n = seasons if seasons is not None else seasons_for(cur)
    base["seasons"] = n
    if not fits([cur_code] * n, crops):
        base["message"] = f"{n} vụ {cur['name_vi']} không vừa một năm theo độ dài vụ ngắn nhất của GAEZ."
        return base
    pool = eligible(cur_code, crops, suit, min_ratio)
    keep = [cur_code] * n
    base_mean = components(keep, crops, suit)["gaez_mean"]
    options = [_describe("keep", "Giữ nguyên", keep, cur_code, crops, suit, mode, base_mean)]

    def skip(opt_id, reason):
        base["skipped"].append({"id": opt_id, "reason": reason})

    legumes = [c for c in pool if crops[c]["is_legume"] and fits(keep[:-1] + [c], crops)]
    if cur["is_legume"]:
        skip("legume", f"{cur['name_vi']} đã là cây họ đậu.")
    elif legumes:
        options.append(_describe("legume", "Thay 1 vụ bằng cây họ đậu", keep[:-1] + [legumes[0]], cur_code,
                                 crops, suit, mode, base_mean))
    else:
        skip("legume", "Không có cây họ đậu đủ điều kiện (điểm GAEZ, chế độ nước, vừa một năm).")

    others = [c for c in pool if not crops[c]["is_legume"] and crops[c]["family"] != cur["family"]
              and fits(keep[:-1] + [c], crops)]
    if others:
        options.append(_describe("other_family", "Thay 1 vụ bằng cây khác họ", keep[:-1] + [others[0]], cur_code,
                                 crops, suit, mode, base_mean))
    else:
        skip("other_family", "Không có cây khác họ đủ điều kiện (điểm GAEZ, chế độ nước, vừa một năm).")

    if n < 2:
        skip("diverse", "Chỉ có 1 vụ trong năm với cây này, không có chỗ để đa dạng hóa.")
    else:
        replace = n - 1 if n >= 3 else n
        seq = _best_diverse(cur_code, n, replace, pool, crops, suit)
        if seq:
            options.append(_describe("diverse", "Đổi nhiều vụ, mỗi vụ một họ", seq, cur_code, crops, suit, mode,
                                     base_mean))
        else:
            skip("diverse", "Không có tổ hợp cây khác họ đủ điều kiện.")

    ranked = [o for o in options[1:] if o["id"] != "keep"]
    sup = [p for p in prios if p in SUPPORTED_PRIORITIES]

    def key(o):
        c = o["components"]
        parts = {"nitrogen": 0 if c["has_legume"] else 1, "pest_cycle": c["same_family_adjacent"],
                 "yield": -(c["gaez_mean"] or 0)}
        return tuple(parts[p] for p in sup) + (o["id"],)
    ranked.sort(key=key)
    base["options"] = [options[0]] + ranked
    base["ranked_by"] = [{"priority": p, "meaning": SUPPORTED_PRIORITIES[p]} for p in sup]
    base["note"] = "Phương án đầu tiên luôn là hiện tại; các phương án còn lại xếp theo ưu tiên đã chọn."
    return base
