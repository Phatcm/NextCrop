"""Rotation options for one location and one current crop (DATA-02).

Season-level rules, NOT a calendar simulation: the app is decision support, and the data does not allow more.
- GAEZ gives one optimal start day per crop standing alone, not a day for a crop that follows another, and
  the day is noisy between neighbouring cells. So the order of the seasons is NOT scheduled (see `assumptions`).
- GAEZ cycle length is the model's pick among candidate cultivars (usually the longest); here the SHORTEST
  candidate (`cycle_days_min`) is used so that multi-cropping is not ruled out. Real cycles can be longer
  (paddy rice) or shorter (short-duration pulses).

Four templates of small change, each shown with its components. There is no single total score: a total would
only restate the weights chosen here, which are not evidence.
  keep          current crop in every season (baseline)
  legume        one season replaced by the best nitrogen-fixing legume
  other_family  one season replaced by the best crop of another family (not a legume)
  diverse       n-1 seasons replaced (n if n == 2): every crop from a different family, a legume if possible

Two numbers are user-adjustable and always echoed back with their source and a `custom` flag:
  gap days between two crops (paddy rice after paddy rice / every other pair) and the minimum GAEZ index.
"""
from __future__ import annotations

import itertools

YEAR_DAYS = 365
MAX_SEASONS = 3
POOL = 8                       # best candidates searched for the "diverse" template
RICE_CODES = {"RCW"}           # paddy rice: the only crop the gap source covers

GAP_RICE_DAYS = 7              # between two paddy rice crops (source below)
GAP_OTHER_DAYS = 15            # every other pair (project assumption, no source)
GAP_MAX_DAYS = 60
MIN_INDEX = 4000               # lower bound of FAO class "moderately suitable" (>= 40% of maximum attainable yield)
INDEX_MAX = 10000

GAP_SOURCES = {
    "rice": "Giữa hai vụ lúa nước: trung bình 5,6 và 6,6 ngày (một nông hộ, ba thửa, Thốt Nốt, Cần Thơ, 2011–2016; "
            "F1000Research, PMC7059783). Chỉ một nông hộ, không phải khảo sát toàn vùng.",
    "other": "Giả định của dự án, chưa có nguồn. Thực tế có thể từ gần 0 ngày (gieo không làm đất ngay sau gặt) "
             "đến vài chục ngày (lên liếp, thoát nước).",
}
INDEX_SOURCE = ("Ranh giới lớp 'phù hợp trung bình' của FAO GAEZ v5 (40–60% năng suất tối đa); dưới ngưỡng này FAO "
                "ghi 'thương mại không khả thi'. Chỉ số ô là trung bình có trọng số theo lớp nên chỉ xấp xỉ "
                "(GAEZ v5 wiki, Module V).")
GAEZ_SOURCE = ("FAO GAEZ v5 RES05-SUX, 2001-2020, AgERA5, historical; average suitability index of current cropland, "
               "5 arc-minute cell (~9 km), better part of the cell in proportion to its cropland share")
# FAO GAEZ v5 suitability classes (wiki, Module V) on the project's 0-10000 index. Returned in every result so the
# interface can show it next to the index floor the user is choosing.
INDEX_CLASS_TABLE = [
    {"min_index": 8000, "max_index": 10000, "class": "Rất phù hợp", "fao_yield_pct": "80–100",
     "meaning": "Đất tốt nhất cho sản xuất kinh tế"},
    {"min_index": 6000, "max_index": 7999, "class": "Phù hợp", "fao_yield_pct": "60–80",
     "meaning": "Đất tốt cho sản xuất kinh tế"},
    {"min_index": 4000, "max_index": 5999, "class": "Trung bình", "fao_yield_pct": "40–60",
     "meaning": "Hạn chế đáng kể về khí hậu, đất hoặc địa hình; cần giá bán cao mới có lãi"},
    {"min_index": 2000, "max_index": 3999, "class": "Biên (thương mại không khả thi)", "fao_yield_pct": "20–40",
     "meaning": "Thương mại không khả thi; chỉ dùng để tự cung tự cấp khi không còn đất khác"},
    {"min_index": 1, "max_index": 1999, "class": "Rất biên (không khả thi kinh tế)", "fao_yield_pct": "dưới 20",
     "meaning": "Sản xuất kinh tế không khả thi"},
]
CLASSES = [(r["min_index"], r["class"]) for r in INDEX_CLASS_TABLE]

SUPPORTED_PRIORITIES = {"nitrogen": "cây họ đậu trước", "pest_cycle": "ít cặp vụ liên tiếp cùng họ trước",
                        "yield": "điểm GAEZ trung bình cao trước"}
UNSUPPORTED_PRIORITIES = {"water": "chưa nạp thiếu nước (GAEZ RES02-WDE)", "erosion": "chưa có độ phủ đất",
                          "income": "chưa có giá nông sản", "soil": "chưa có dữ liệu đất"}
MISSING_ALWAYS = ["giá nông sản (ưu tiên thu nhập)", "độ phủ đất và xói mòn", "đất (kết cấu, hữu cơ)",
                  "lịch gieo từng vụ (thứ tự các vụ chưa được xếp lịch)"]
FIXED_ASSUMPTIONS = {
    "season_order": "Thứ tự các vụ chưa được xếp lịch; chỉ xét bộ cây trong một năm.",
    "cycle_days": "Độ dài vụ lấy giống ngắn nhất GAEZ thử (cycle_days_min); thực tế có thể khác theo giống.",
    "gaez": "Chỉ số phù hợp là tiềm năng (0–10000), không phải năng suất thực tế.",
}


def gaez_class(index: int | None) -> str:
    if not index or index <= 0:
        return "Không phù hợp hoặc không có dữ liệu"
    return next(label for lo, label in CLASSES if index >= lo)


def resolve_params(gap_rice: int | None, gap_other: int | None, min_index: int | None) -> dict:
    """Defaults + validation. Returns the values used and whether each one was changed by the user."""
    def one(value, default, name, lo, hi):
        if value is None:
            return default, False
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not (lo <= value <= hi):
            raise ValueError(f"{name} must be a number between {lo} and {hi}, got {value!r}")
        return value, value != default
    r, rc = one(gap_rice, GAP_RICE_DAYS, "gap_rice", 0, GAP_MAX_DAYS)
    o, oc = one(gap_other, GAP_OTHER_DAYS, "gap_other", 0, GAP_MAX_DAYS)
    m, mc = one(min_index, MIN_INDEX, "min_index", 0, INDEX_MAX)
    return {"gaps": {"rice": r, "other": o}, "min_index": m,
            "custom": {"gap_rice": rc, "gap_other": oc, "min_index": mc}}


def _gap(a: str, b: str, gaps: dict) -> int:
    return gaps["rice"] if a in RICE_CODES and b in RICE_CODES else gaps["other"]


def gap_total(seq: list[str], gaps: dict) -> int:
    """Gap after every crop, including the one from the last crop to the first of the next year."""
    n = len(seq)
    return sum(_gap(seq[i], seq[(i + 1) % n], gaps) for i in range(n))


def _usable(c: dict) -> bool:
    return c.get("life_cycle") == "annual" and c.get("cycle_days_min") is not None


def fits(seq: list[str], crops: dict[str, dict], gaps: dict) -> bool:
    return sum(crops[c]["cycle_days_min"] for c in seq) + gap_total(seq, gaps) <= YEAR_DAYS


def seasons_for(cur_code: str, crops: dict[str, dict], gaps: dict) -> int:
    """How many crops of the current kind fit in a year (1..MAX_SEASONS)."""
    return next((n for n in range(MAX_SEASONS, 1, -1) if fits([cur_code] * n, crops, gaps)), 1)


def eligible(cur_code: str, crops: dict[str, dict], suit: dict[str, int | None],
             min_index: int = MIN_INDEX) -> list[str]:
    """Annual crops that may replace a season, best GAEZ index first."""
    cur = crops[cur_code]
    out = []
    for code, c in crops.items():
        v = suit.get(code)
        if code == cur_code or not _usable(c) or not v or v <= 0 or v < min_index:
            continue
        if cur["water_regime"] == "upland" and c["water_regime"] == "wetland":
            continue                                        # a flooded crop cannot go into an upland field
        out.append(code)
    return sorted(out, key=lambda k: (-suit[k], k))


def components(seq: list[str], crops: dict[str, dict], suit: dict[str, int | None], gaps: dict) -> dict:
    known = [v for v in (suit.get(c) for c in seq) if v is not None]
    n = len(seq)
    same = sum(crops[seq[i]]["family"] == crops[seq[(i + 1) % n]]["family"] for i in range(n)) if n > 1 else 0
    days = sum(crops[c]["cycle_days_min"] for c in seq)
    total = days + gap_total(seq, gaps)
    return {"gaez_mean": round(sum(known) / len(known)) if known else None,
            "same_family_adjacent": same,
            "has_legume": any(crops[c]["is_legume"] for c in seq),
            "families": sorted({crops[c]["family"] for c in seq}),
            "cycle_days_total": days, "days_with_buffer": total, "slack_days": YEAR_DAYS - total,
            "fits_year": total <= YEAR_DAYS}


def _describe(opt_id: str, label: str, seq: list[str], cur_code: str, crops: dict, suit: dict, mode: str,
              gaps: dict, base_mean: int | None) -> dict:
    comp = components(seq, crops, suit, gaps)
    cur = crops[cur_code]
    keep_same = components([cur_code] * len(seq), crops, suit, gaps)["same_family_adjacent"]
    benefits, risks = [], []
    if comp["has_legume"] and not cur["is_legume"]:
        legs = sorted({crops[c]["name_vi"] for c in seq if crops[c]["is_legume"]})
        benefits.append(f"Có cây họ đậu ({', '.join(legs)}): cố định đạm theo cờ họ đậu của GAEZ A4-6.1.")
    if seq != [cur_code] * len(seq) and comp["same_family_adjacent"] < keep_same:
        benefits.append("Giảm số cặp vụ liên tiếp cùng họ, hạn chế sâu bệnh tích lũy theo họ thực vật.")
    if comp["same_family_adjacent"]:
        risks.append(f"Còn {comp['same_family_adjacent']} cặp vụ liên tiếp cùng họ: nguy cơ sâu bệnh tích lũy.")
    if base_mean is not None and comp["gaez_mean"] is not None and comp["gaez_mean"] < base_mean - 500:
        risks.append(f"Điểm GAEZ trung bình thấp hơn phương án hiện tại {base_mean - comp['gaez_mean']} điểm "
                     f"({comp['gaez_mean']} so với {base_mean}).")
    if cur["water_regime"] == "wetland" and any(crops[c]["water_regime"] == "upland" for c in seq):
        ups = sorted({crops[c]["name_vi"] for c in seq if crops[c]["water_regime"] == "upland"})
        risks.append(f"Cây cạn ({', '.join(ups)}) trên ruộng quen ngập: cần thoát nước và làm đất. "
                     "Chế độ nước của cây cạn là mặc định của dự án, GAEZ không phân biệt.")
    under = [c for c in dict.fromkeys(seq) if (suit.get(c) or 0) < MIN_INDEX]
    if under:
        risks.append("Cây dưới ngưỡng " + str(MIN_INDEX) + " của FAO (thương mại không khả thi): " +
                     ", ".join(f"{crops[c]['name_vi']} {suit.get(c) or 0} ({gaez_class(suit.get(c))})" for c in under) + ".")
    if comp["slack_days"] < 10:
        risks.append(f"Sát mép: chỉ còn dư {comp['slack_days']} ngày trong năm; chậm một vụ là không còn vừa.")
    risks.append("Độ dài vụ lấy giống ngắn nhất GAEZ thử; vụ thực tế có thể dài hơn và không còn vừa một năm.")
    evidence = [{"crop_code": c, "name_vi": crops[c]["name_vi"], "gaez_index": suit.get(c),
                 "gaez_class": gaez_class(suit.get(c)), "mode": mode,
                 "cycle_days_min": crops[c]["cycle_days_min"], "family": crops[c]["family"],
                 "is_legume": crops[c]["is_legume"], "water_regime": crops[c]["water_regime"]} for c in seq]
    return {"id": opt_id, "label": label, "sequence": seq, "names": [crops[c]["name_vi"] for c in seq],
            "components": comp, "benefits": benefits, "risks": risks, "evidence": evidence,
            "evidence_source": GAEZ_SOURCE}


def _best_diverse(cur_code: str, n: int, replace: int, pool: list[str], crops: dict, suit: dict,
                  gaps: dict) -> list[str] | None:
    """Keep cur in (n - replace) seasons; fill `replace` seasons with crops of pairwise different families,
    all different from cur, a legume among them when the pool has one. Best GAEZ sum wins."""
    keep = [cur_code] * (n - replace)
    best, best_key = None, None
    for combo in itertools.combinations(pool[:POOL], replace):
        fams = [crops[c]["family"] for c in combo] + ([crops[cur_code]["family"]] if keep else [])
        if len(set(fams)) != len(fams):
            continue
        seq = keep + list(combo)
        if not fits(seq, crops, gaps):
            continue
        key = (any(crops[c]["is_legume"] for c in combo), sum(suit[c] for c in combo),
               tuple(-ord(ch) for ch in "".join(combo)))
        if best_key is None or key > best_key:
            best, best_key = seq, key
    return best


def _floor_hint(cur_code: str, crops: dict, suit: dict, floor: int, kwargs: dict) -> dict:
    """When fewer than 3 options survive the floor: the highest lower floor (rounded down to 100) that gives 3."""
    cands = sorted({max(1, (suit[c] // 100) * 100) for c, cc in crops.items()
                    if c != cur_code and _usable(cc) and suit.get(c) and 0 < suit[c] < floor}, reverse=True)
    for cand in cands:
        trial = generate(cur_code, crops, suit, min_index=cand, _hint=False, **kwargs)
        if len(trial["options"]) >= 3:
            used = sorted({gaez_class(suit.get(c)) for o in trial["options"] for c in o["sequence"] if c != cur_code})
            return {"min_index": cand, "options_if_lowered": len(trial["options"]), "classes": used,
                    "below_fao_floor": cand < MIN_INDEX,
                    "message": f"Hạ ngưỡng xuống {cand} để có {len(trial['options'])} phương án (gồm cây thuộc lớp "
                               f"{', '.join(used)}). Theo FAO, các lớp dưới 'Trung bình' không khả thi về kinh tế."}
    return {"min_index": None, "options_if_lowered": None, "classes": [], "below_fao_floor": True,
            "message": "Hạ ngưỡng đến mức thấp nhất vẫn không đủ 3 phương án (thiếu cây có chỉ số GAEZ dương, "
                       "hợp chế độ nước và vừa một năm)."}


def generate(cur_code: str, crops: dict[str, dict], suit: dict[str, int | None], *, mode: str = "hrlm",
             seasons: int | None = None, priorities: list[str] | None = None, min_index: int | None = None,
             gap_rice: int | None = None, gap_other: int | None = None, _hint: bool = True) -> dict:
    """crops: {code: {name_vi, life_cycle, is_legume, family, cycle_days_min, water_regime}} (dim_crop).
    suit: {crop_code: GAEZ index 0-10000 or None} for the clicked cell and input mode.
    gap_rice / gap_other (days between two crops) and min_index are adjustable; the values used are echoed in
    `assumptions` with their source and a `custom` flag.
    Returns {"options": [...], "skipped": [...], ...}; options[0] is always the current practice.
    `sequence` is a canonical listing (kept crops first, then replacements by GAEZ index), not a schedule."""
    if cur_code not in crops:
        raise ValueError(f"unknown crop {cur_code!r}")
    p = resolve_params(gap_rice, gap_other, min_index)
    gaps, floor, custom = p["gaps"], p["min_index"], p["custom"]
    cur = crops[cur_code]
    prios = list(priorities or ["yield"])
    unsupported = [{"priority": q, "reason": UNSUPPORTED_PRIORITIES.get(q, "không có trong bộ ưu tiên đã hỗ trợ")}
                   for q in prios if q not in SUPPORTED_PRIORITIES]
    assumptions = {**FIXED_ASSUMPTIONS,
                   "gap_rice": {"days": gaps["rice"], "custom": custom["gap_rice"], "source": GAP_SOURCES["rice"]},
                   "gap_other": {"days": gaps["other"], "custom": custom["gap_other"], "source": GAP_SOURCES["other"]},
                   "min_index": {"value": floor, "custom": custom["min_index"], "source": INDEX_SOURCE}}
    base = {"current": cur_code, "mode": mode, "assumptions": assumptions, "missing": MISSING_ALWAYS,
            "index_classes": INDEX_CLASS_TABLE, "floor_hint": None,
            "unsupported_priorities": unsupported, "warnings": [], "options": [], "skipped": []}
    if floor < MIN_INDEX:
        base["warnings"].append(
            f"Ngưỡng đang đặt {floor}, thấp hơn {MIN_INDEX}: kết quả có thể gồm cây mà FAO coi là không khả thi về "
            "kinh tế. Xem bảng lớp độ phù hợp (index_classes) và cảnh báo từng phương án.")
    if cur.get("life_cycle") != "annual" or cur.get("cycle_days_min") is None:
        base["message"] = (f"{cur['name_vi']} là cây lâu năm hoặc chưa có độ dài vụ trong dữ liệu GAEZ: "
                           "không luân canh theo vụ, không sinh phương án.")
        return base
    cur_index = suit.get(cur_code)
    base["current_gaez"] = {"index": cur_index, "class": gaez_class(cur_index)}
    if not cur_index or cur_index < floor:
        base["warnings"].append(
            f"{cur['name_vi']} có chỉ số GAEZ {cur_index or 0} (lớp: {gaez_class(cur_index)}), dưới ngưỡng {floor} "
            "đang áp dụng. Các phương án thay thế chỉ gồm cây từ ngưỡng này trở lên.")
    default_gaps = {"rice": GAP_RICE_DAYS, "other": GAP_OTHER_DAYS}
    n = seasons if seasons is not None else seasons_for(cur_code, crops, gaps)
    if seasons is None:
        n_default = seasons_for(cur_code, crops, default_gaps)
        if n != n_default:
            base["warnings"].append(
                f"Với khoảng nghỉ bạn chọn, số vụ {cur['name_vi']} trong năm là {n} thay vì {n_default} (mặc định): "
                "mọi phương án bên dưới đổi theo.")
    base["seasons"] = n
    if not fits([cur_code] * n, crops, gaps):
        base["message"] = f"{n} vụ {cur['name_vi']} không vừa một năm theo độ dài vụ ngắn nhất của GAEZ."
        return base
    pool = eligible(cur_code, crops, suit, floor)
    keep = [cur_code] * n
    base_mean = components(keep, crops, suit, gaps)["gaez_mean"]
    options = [_describe("keep", "Giữ nguyên", keep, cur_code, crops, suit, mode, gaps, base_mean)]

    def skip(opt_id, reason):
        base["skipped"].append({"id": opt_id, "reason": reason})

    legumes = [c for c in pool if crops[c]["is_legume"] and fits(keep[:-1] + [c], crops, gaps)]
    if cur["is_legume"]:
        skip("legume", f"{cur['name_vi']} đã là cây họ đậu.")
    elif legumes:
        options.append(_describe("legume", "Thay 1 vụ bằng cây họ đậu", keep[:-1] + [legumes[0]], cur_code,
                                 crops, suit, mode, gaps, base_mean))
    else:
        skip("legume", "Không có cây họ đậu đủ điều kiện (chỉ số GAEZ, chế độ nước, vừa một năm).")

    others = [c for c in pool if not crops[c]["is_legume"] and crops[c]["family"] != cur["family"]
              and fits(keep[:-1] + [c], crops, gaps)]
    if others:
        options.append(_describe("other_family", "Thay 1 vụ bằng cây khác họ", keep[:-1] + [others[0]], cur_code,
                                 crops, suit, mode, gaps, base_mean))
    else:
        skip("other_family", "Không có cây khác họ đủ điều kiện (chỉ số GAEZ, chế độ nước, vừa một năm).")

    if n < 2:
        skip("diverse", "Chỉ có 1 vụ trong năm với cây này, không có chỗ để đa dạng hóa.")
    else:
        # the main crop stays in at least one season: n - 1 seasons are replaced, never all of them
        seq = _best_diverse(cur_code, n, n - 1, pool, crops, suit, gaps)
        twin = next((o["id"] for o in options if seq and sorted(o["sequence"]) == sorted(seq)), None)
        if not seq:
            skip("diverse", "Không có tổ hợp cây khác họ đủ điều kiện.")
        elif twin:
            skip("diverse", f"Trùng với phương án '{twin}': khi chỉ có {n} vụ, giữ 1 vụ cây hiện tại và chỉ còn "
                            f"thay {n - 1} vụ.")
        else:
            options.append(_describe("diverse", "Đổi nhiều vụ, mỗi vụ một họ", seq, cur_code, crops, suit, mode,
                                     gaps, base_mean))

    ranked = [o for o in options[1:]]
    sup = [q for q in prios if q in SUPPORTED_PRIORITIES]

    def key(o):
        c = o["components"]
        parts = {"nitrogen": 0 if c["has_legume"] else 1, "pest_cycle": c["same_family_adjacent"],
                 "yield": -(c["gaez_mean"] or 0)}
        return tuple(parts[q] for q in sup) + (o["id"],)
    ranked.sort(key=key)
    base["options"] = [options[0]] + ranked
    if _hint and len(base["options"]) < 3 and floor > 0:
        base["floor_hint"] = _floor_hint(cur_code, crops, suit, floor, dict(
            mode=mode, seasons=seasons, priorities=priorities, gap_rice=gap_rice, gap_other=gap_other))
    base["ranked_by"] = [{"priority": q, "meaning": SUPPORTED_PRIORITIES[q]} for q in sup]
    base["note"] = "Phương án đầu tiên luôn là hiện tại; các phương án còn lại xếp theo ưu tiên đã chọn."
    base["principle"] = (
        "Cây hiện tại là cây chủ lực: khi có từ 2 vụ trở lên, mọi phương án giữ lại ít nhất 1 vụ cây hiện tại "
        "(hạ tầng, máy móc và kinh nghiệm canh tác có sẵn) và chỉ thay các vụ còn lại."
        if n >= 2 else
        "Chỉ có 1 vụ trong năm với cây này: phương án thay thế là cây của năm kế tiếp, không thể giữ cây hiện tại "
        "trong cùng năm.")
    return base
