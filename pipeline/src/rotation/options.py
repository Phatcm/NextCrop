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

Language: every sentence the generator writes comes from the two tables STRINGS["vi"] and STRINGS["en"] (same keys,
same {placeholders}, checked by a test). `lang="vi"` is the default and its text is unchanged. A crop is shown by
`name_en` when lang == "en" and the crop has one, otherwise by `name_vi`.
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
LANGS = ("vi", "en")

GAEZ_SOURCE = ("FAO GAEZ v5 RES05-SUX, 2001-2020, AgERA5, historical; average suitability index of current cropland, "
               "5 arc-minute cell (~9 km), better part of the cell in proportion to its cropland share")

# ---- every sentence, per language -------------------------------------------------------------------------------
_VI = {
    "gap_rice": "Giữa hai vụ lúa nước: trung bình 5,6 và 6,6 ngày (một nông hộ, ba thửa, Thốt Nốt, Cần Thơ, 2011–2016; "
                "F1000Research, PMC7059783). Chỉ một nông hộ, không phải khảo sát toàn vùng.",
    "gap_other": "Giả định của dự án, chưa có nguồn. Thực tế có thể từ gần 0 ngày (gieo không làm đất ngay sau gặt) "
                 "đến vài chục ngày (lên liếp, thoát nước).",
    "index_source": "Ranh giới lớp 'phù hợp trung bình' của FAO GAEZ v5 (40–60% năng suất tối đa); dưới ngưỡng này FAO "
                    "ghi 'thương mại không khả thi'. Chỉ số ô là trung bình có trọng số theo lớp nên chỉ xấp xỉ "
                    "(GAEZ v5 wiki, Module V).",
    "class_8000": "Rất phù hợp", "meaning_8000": "Đất tốt nhất cho sản xuất kinh tế",
    "class_6000": "Phù hợp", "meaning_6000": "Đất tốt cho sản xuất kinh tế",
    "class_4000": "Trung bình",
    "meaning_4000": "Hạn chế đáng kể về khí hậu, đất hoặc địa hình; cần giá bán cao mới có lãi",
    "class_2000": "Biên (thương mại không khả thi)",
    "meaning_2000": "Thương mại không khả thi; chỉ dùng để tự cung tự cấp khi không còn đất khác",
    "class_1": "Rất biên (không khả thi kinh tế)", "meaning_1": "Sản xuất kinh tế không khả thi",
    "pct_under_20": "dưới 20",
    "class_none": "Không phù hợp hoặc không có dữ liệu",
    "prio_nitrogen": "cây họ đậu trước", "prio_pest_cycle": "ít cặp vụ liên tiếp cùng họ trước",
    "prio_yield": "điểm GAEZ trung bình cao trước",
    "unsup_water": "chưa nạp thiếu nước (GAEZ RES02-WDE)", "unsup_erosion": "chưa có độ phủ đất",
    "unsup_income": "chưa có giá nông sản", "unsup_soil": "chưa có dữ liệu đất",
    "unsup_other": "không có trong bộ ưu tiên đã hỗ trợ",
    "missing_income": "giá nông sản (ưu tiên thu nhập)", "missing_erosion": "độ phủ đất và xói mòn",
    "missing_soil": "đất (kết cấu, hữu cơ)", "missing_calendar": "lịch gieo từng vụ (thứ tự các vụ chưa được xếp lịch)",
    "assume_season_order": "Thứ tự các vụ chưa được xếp lịch; chỉ xét bộ cây trong một năm.",
    "assume_cycle_days": "Độ dài vụ lấy giống ngắn nhất GAEZ thử (cycle_days_min); thực tế có thể khác theo giống.",
    "assume_gaez": "Chỉ số phù hợp là tiềm năng (0–10000), không phải năng suất thực tế.",
    "benefit_legume": "Có cây họ đậu ({names}): cố định đạm theo cờ họ đậu của GAEZ A4-6.1.",
    "benefit_family": "Giảm số cặp vụ liên tiếp cùng họ, hạn chế sâu bệnh tích lũy theo họ thực vật.",
    "risk_same_family": "Còn {n} cặp vụ liên tiếp cùng họ: nguy cơ sâu bệnh tích lũy.",
    "risk_lower_mean": "Điểm GAEZ trung bình thấp hơn phương án hiện tại {diff} điểm ({mean} so với {base}).",
    "risk_upland": "Cây cạn ({names}) trên ruộng quen ngập: cần thoát nước và làm đất. "
                   "Chế độ nước của cây cạn là mặc định của dự án, GAEZ không phân biệt.",
    "risk_under_floor": "Cây dưới ngưỡng {floor} của FAO (thương mại không khả thi): {items}.",
    "risk_tight": "Sát mép: chỉ còn dư {days} ngày trong năm; chậm một vụ là không còn vừa.",
    "risk_cycle": "Độ dài vụ lấy giống ngắn nhất GAEZ thử; vụ thực tế có thể dài hơn và không còn vừa một năm.",
    "hint_ok": "Hạ ngưỡng xuống {cand} để có {k} phương án (gồm cây thuộc lớp {classes}). Theo FAO, các lớp dưới "
               "'Trung bình' không khả thi về kinh tế.",
    "hint_none": "Hạ ngưỡng đến mức thấp nhất vẫn không đủ 3 phương án (thiếu cây có chỉ số GAEZ dương, "
                 "hợp chế độ nước và vừa một năm).",
    "warn_low_floor": "Ngưỡng đang đặt {floor}, thấp hơn {min}: kết quả có thể gồm cây mà FAO coi là không khả thi về "
                      "kinh tế. Xem bảng lớp độ phù hợp (index_classes) và cảnh báo từng phương án.",
    "msg_perennial": "{name} là cây lâu năm hoặc chưa có độ dài vụ trong dữ liệu GAEZ: không luân canh theo vụ, "
                     "không sinh phương án.",
    "warn_current_below": "{name} có chỉ số GAEZ {index} (lớp: {cls}), dưới ngưỡng {floor} đang áp dụng. "
                          "Các phương án thay thế chỉ gồm cây từ ngưỡng này trở lên.",
    "warn_seasons_changed": "Với khoảng nghỉ bạn chọn, số vụ {name} trong năm là {n} thay vì {default} (mặc định): "
                            "mọi phương án bên dưới đổi theo.",
    "msg_not_fit": "{n} vụ {name} không vừa một năm theo độ dài vụ ngắn nhất của GAEZ.",
    "label_keep": "Giữ nguyên", "label_legume": "Thay 1 vụ bằng cây họ đậu",
    "label_other_family": "Thay 1 vụ bằng cây khác họ", "label_diverse": "Đổi nhiều vụ, mỗi vụ một họ",
    "skip_legume_current": "{name} đã là cây họ đậu.",
    "skip_legume_none": "Không có cây họ đậu đủ điều kiện (chỉ số GAEZ, chế độ nước, vừa một năm).",
    "skip_other_none": "Không có cây khác họ đủ điều kiện (chỉ số GAEZ, chế độ nước, vừa một năm).",
    "skip_diverse_one": "Chỉ có 1 vụ trong năm với cây này, không có chỗ để đa dạng hóa.",
    "skip_diverse_none": "Không có tổ hợp cây khác họ đủ điều kiện.",
    "skip_diverse_twin": "Trùng với phương án '{twin}': khi chỉ có {n} vụ, giữ 1 vụ cây hiện tại và chỉ còn "
                         "thay {m} vụ.",
    "note": "Phương án đầu tiên luôn là hiện tại; các phương án còn lại xếp theo ưu tiên đã chọn.",
    "principle_multi": "Cây hiện tại là cây chủ lực: khi có từ 2 vụ trở lên, mọi phương án giữ lại ít nhất 1 vụ cây "
                       "hiện tại (hạ tầng, máy móc và kinh nghiệm canh tác có sẵn) và chỉ thay các vụ còn lại.",
    "principle_single": "Chỉ có 1 vụ trong năm với cây này: phương án thay thế là cây của năm kế tiếp, không thể giữ "
                        "cây hiện tại trong cùng năm.",
}

_EN = {
    "gap_rice": "Between two wetland-rice crops: on average 5.6 and 6.6 days (one farm household, three plots, "
                "Thot Not, Can Tho, 2011–2016; F1000Research, PMC7059783). One household only, not a regional survey.",
    "gap_other": "Project assumption, no source. In practice it can range from almost 0 days (sowing without tillage "
                 "right after harvest) to several tens of days (bed preparation, drainage).",
    "index_source": "Lower bound of the FAO GAEZ v5 'moderately suitable' class (40–60% of maximum yield); below it "
                    "FAO states 'not commercially viable'. The cell index is a class-weighted mean, so this is only "
                    "approximate (GAEZ v5 wiki, Module V).",
    "class_8000": "Very suitable", "meaning_8000": "Best land for economic production",
    "class_6000": "Suitable", "meaning_6000": "Good land for economic production",
    "class_4000": "Moderately suitable",
    "meaning_4000": "Significant climate, soil or terrain limits; needs a high selling price to pay off",
    "class_2000": "Marginal (not commercially viable)",
    "meaning_2000": "Not commercially viable; only for subsistence when no other land is left",
    "class_1": "Very marginal (not economically viable)", "meaning_1": "Economic production is not viable",
    "pct_under_20": "under 20",
    "class_none": "Not suitable or no data",
    "prio_nitrogen": "legumes first", "prio_pest_cycle": "fewest consecutive same-family seasons first",
    "prio_yield": "highest mean GAEZ index first",
    "unsup_water": "water shortage not loaded yet (GAEZ RES02-WDE)", "unsup_erosion": "no ground-cover data",
    "unsup_income": "no crop prices", "unsup_soil": "no soil data",
    "unsup_other": "not among the supported priorities",
    "missing_income": "crop prices (income priority)", "missing_erosion": "ground cover and erosion",
    "missing_soil": "soil (texture, organic matter)",
    "missing_calendar": "sowing calendar per season (the order of the seasons is not scheduled)",
    "assume_season_order": "The order of the seasons is not scheduled; only the set of crops in one year is considered.",
    "assume_cycle_days": "Shortest cycle length GAEZ tests (cycle_days_min); real cycles may differ by cultivar.",
    "assume_gaez": "The suitability index is potential (0–10000), not actual yield.",
    "benefit_legume": "Includes a legume ({names}): fixes nitrogen according to the GAEZ A4-6.1 legume flag.",
    "benefit_family": "Fewer consecutive same-family seasons, limiting pest build-up by plant family.",
    "risk_same_family": "{n} consecutive same-family season pair(s) remain: risk of pest build-up.",
    "risk_lower_mean": "Mean GAEZ score is {diff} points lower than the current option ({mean} vs {base}).",
    "risk_upland": "Upland crop(s) ({names}) on a field used to flooding: needs drainage and tillage. "
                   "The project assumes the water regime of upland crops; GAEZ does not distinguish it.",
    "risk_under_floor": "Crops below the FAO floor of {floor} (not commercially viable): {items}.",
    "risk_tight": "Tight fit: only {days} spare days in the year; one late season and it no longer fits.",
    "risk_cycle": "Cycle length is the shortest cultivar GAEZ tests; real seasons can be longer and then no longer "
                  "fit in one year.",
    "hint_ok": "Lower the floor to {cand} to get {k} options (including crops of class {classes}). According to FAO, "
               "classes below 'Moderately suitable' are not economically viable.",
    "hint_none": "Lowering the floor all the way still does not give 3 options (not enough crops with a positive "
                 "GAEZ index that fit the water regime and one year).",
    "warn_low_floor": "The floor is set to {floor}, below {min}: results may include crops that FAO considers not "
                      "economically viable. See the suitability class table (index_classes) and the warnings on "
                      "each option.",
    "msg_perennial": "{name} is a perennial or has no cycle length in the GAEZ data: no rotation by season, so no "
                     "options are generated.",
    "warn_current_below": "{name} has GAEZ index {index} (class: {cls}), below the floor of {floor} in use. "
                          "Replacement options only include crops at or above this floor.",
    "warn_seasons_changed": "With the gaps you chose, the number of {name} seasons per year is {n} instead of "
                            "{default} (default): all options below change accordingly.",
    "msg_not_fit": "{n} season(s) of {name} do not fit in one year using GAEZ's shortest cycle lengths.",
    "label_keep": "Keep as is", "label_legume": "Replace 1 season with a legume",
    "label_other_family": "Replace 1 season with a crop of another family",
    "label_diverse": "Change several seasons, one family each",
    "skip_legume_current": "{name} is already a legume.",
    "skip_legume_none": "No eligible legume (GAEZ index, water regime, fits one year).",
    "skip_other_none": "No eligible crop of another family (GAEZ index, water regime, fits one year).",
    "skip_diverse_one": "Only 1 season per year with this crop, no room to diversify.",
    "skip_diverse_none": "No eligible combination of crops from different families.",
    "skip_diverse_twin": "Same as option '{twin}': with only {n} seasons, 1 season of the current crop stays and only "
                         "{m} season(s) can be replaced.",
    "note": "The first option is always the current practice; the others are ordered by the priorities you chose.",
    "principle_multi": "The current crop is the main crop: with 2 or more seasons, every option keeps at least 1 "
                       "season of it (existing infrastructure, machines and experience) and only replaces the other "
                       "seasons.",
    "principle_single": "Only 1 season per year with this crop: the alternative is the crop of the next year, the "
                        "current crop cannot be kept in the same year.",
}
STRINGS = {"vi": _VI, "en": _EN}

# Vietnamese constants kept for callers and tests that read them directly
GAP_SOURCES = {"rice": _VI["gap_rice"], "other": _VI["gap_other"]}
INDEX_SOURCE = _VI["index_source"]
_CLASS_ROWS = [(8000, 10000, "80–100", "8000"), (6000, 7999, "60–80", "6000"), (4000, 5999, "40–60", "4000"),
               (2000, 3999, "20–40", "2000"), (1, 1999, None, "1")]


def _class_table(lang: str) -> list[dict]:
    s = STRINGS[lang]
    return [{"min_index": lo, "max_index": hi, "class": s[f"class_{key}"], "fao_yield_pct": pct or s["pct_under_20"],
             "meaning": s[f"meaning_{key}"]} for lo, hi, pct, key in _CLASS_ROWS]


# FAO GAEZ v5 suitability classes (wiki, Module V) on the project's 0-10000 index. Returned in every result so the
# interface can show it next to the index floor the user is choosing.
INDEX_CLASS_TABLE = _class_table("vi")
CLASSES = [(r["min_index"], r["class"]) for r in INDEX_CLASS_TABLE]
SUPPORTED_PRIORITIES = {k: _VI[f"prio_{k}"] for k in ("nitrogen", "pest_cycle", "yield")}
UNSUPPORTED_PRIORITIES = {k: _VI[f"unsup_{k}"] for k in ("water", "erosion", "income", "soil")}
MISSING_ALWAYS = [_VI[k] for k in ("missing_income", "missing_erosion", "missing_soil", "missing_calendar")]
FIXED_ASSUMPTIONS = {k: _VI[f"assume_{k}"] for k in ("season_order", "cycle_days", "gaez")}


def _strings(lang: str) -> dict:
    if lang not in STRINGS:
        raise ValueError(f"lang must be one of {', '.join(LANGS)}, got {lang!r}")
    return STRINGS[lang]


def _name(crop: dict, lang: str) -> str:
    """Display name of a crop: English when asked for and available, else Vietnamese."""
    return (crop.get("name_en") if lang == "en" else None) or crop["name_vi"]


def gaez_class(index: int | None, lang: str = "vi") -> str:
    s = _strings(lang)
    if not index or index <= 0:
        return s["class_none"]
    return next(r["class"] for r in _class_table(lang) if index >= r["min_index"])


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
              gaps: dict, base_mean: int | None, lang: str = "vi") -> dict:
    s = _strings(lang)
    comp = components(seq, crops, suit, gaps)
    cur = crops[cur_code]
    keep_same = components([cur_code] * len(seq), crops, suit, gaps)["same_family_adjacent"]
    nm = lambda c: _name(crops[c], lang)                      # noqa: E731
    benefits, risks = [], []
    if comp["has_legume"] and not cur["is_legume"]:
        legs = sorted({nm(c) for c in seq if crops[c]["is_legume"]})
        benefits.append(s["benefit_legume"].format(names=", ".join(legs)))
    if seq != [cur_code] * len(seq) and comp["same_family_adjacent"] < keep_same:
        benefits.append(s["benefit_family"])
    if comp["same_family_adjacent"]:
        risks.append(s["risk_same_family"].format(n=comp["same_family_adjacent"]))
    if base_mean is not None and comp["gaez_mean"] is not None and comp["gaez_mean"] < base_mean - 500:
        risks.append(s["risk_lower_mean"].format(diff=base_mean - comp["gaez_mean"], mean=comp["gaez_mean"],
                                                 base=base_mean))
    if cur["water_regime"] == "wetland" and any(crops[c]["water_regime"] == "upland" for c in seq):
        ups = sorted({nm(c) for c in seq if crops[c]["water_regime"] == "upland"})
        risks.append(s["risk_upland"].format(names=", ".join(ups)))
    under = [c for c in dict.fromkeys(seq) if (suit.get(c) or 0) < MIN_INDEX]
    if under:
        items = ", ".join(f"{nm(c)} {suit.get(c) or 0} ({gaez_class(suit.get(c), lang)})" for c in under)
        risks.append(s["risk_under_floor"].format(floor=MIN_INDEX, items=items))
    if comp["slack_days"] < 10:
        risks.append(s["risk_tight"].format(days=comp["slack_days"]))
    risks.append(s["risk_cycle"])
    evidence = [{"crop_code": c, "name_vi": crops[c]["name_vi"], "name": nm(c), "gaez_index": suit.get(c),
                 "gaez_class": gaez_class(suit.get(c), lang), "mode": mode,
                 "cycle_days_min": crops[c]["cycle_days_min"], "family": crops[c]["family"],
                 "is_legume": crops[c]["is_legume"], "water_regime": crops[c]["water_regime"]} for c in seq]
    return {"id": opt_id, "label": label, "sequence": seq, "names": [nm(c) for c in seq],
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
    lang = kwargs.get("lang", "vi")
    s = _strings(lang)
    cands = sorted({max(1, (suit[c] // 100) * 100) for c, cc in crops.items()
                    if c != cur_code and _usable(cc) and suit.get(c) and 0 < suit[c] < floor}, reverse=True)
    for cand in cands:
        trial = generate(cur_code, crops, suit, min_index=cand, _hint=False, **kwargs)
        if len(trial["options"]) >= 3:
            used = sorted({gaez_class(suit.get(c), lang) for o in trial["options"] for c in o["sequence"]
                           if c != cur_code})
            return {"min_index": cand, "options_if_lowered": len(trial["options"]), "classes": used,
                    "below_fao_floor": cand < MIN_INDEX,
                    "message": s["hint_ok"].format(cand=cand, k=len(trial["options"]), classes=", ".join(used))}
    return {"min_index": None, "options_if_lowered": None, "classes": [], "below_fao_floor": True,
            "message": s["hint_none"]}


def generate(cur_code: str, crops: dict[str, dict], suit: dict[str, int | None], *, mode: str = "hrlm",
             seasons: int | None = None, priorities: list[str] | None = None, min_index: int | None = None,
             gap_rice: int | None = None, gap_other: int | None = None, lang: str = "vi",
             _hint: bool = True) -> dict:
    """crops: {code: {name_vi, [name_en], life_cycle, is_legume, family, cycle_days_min, water_regime}} (dim_crop).
    suit: {crop_code: GAEZ index 0-10000 or None} for the clicked cell and input mode.
    gap_rice / gap_other (days between two crops) and min_index are adjustable; the values used are echoed in
    `assumptions` with their source and a `custom` flag. `lang` ("vi" default, or "en") picks the language of every
    sentence in the result.
    Returns {"options": [...], "skipped": [...], ...}; options[0] is always the current practice.
    `sequence` is a canonical listing (kept crops first, then replacements by GAEZ index), not a schedule."""
    s = _strings(lang)
    if cur_code not in crops:
        raise ValueError(f"unknown crop {cur_code!r}")
    p = resolve_params(gap_rice, gap_other, min_index)
    gaps, floor, custom = p["gaps"], p["min_index"], p["custom"]
    cur = crops[cur_code]
    cur_name = _name(cur, lang)
    prios = list(priorities or ["yield"])
    unsupported = [{"priority": q, "reason": s.get(f"unsup_{q}", s["unsup_other"]) if q in UNSUPPORTED_PRIORITIES
                    else s["unsup_other"]} for q in prios if q not in SUPPORTED_PRIORITIES]
    assumptions = {**{k: s[f"assume_{k}"] for k in ("season_order", "cycle_days", "gaez")},
                   "gap_rice": {"days": gaps["rice"], "custom": custom["gap_rice"], "source": s["gap_rice"]},
                   "gap_other": {"days": gaps["other"], "custom": custom["gap_other"], "source": s["gap_other"]},
                   "min_index": {"value": floor, "custom": custom["min_index"], "source": s["index_source"]}}
    base = {"current": cur_code, "mode": mode, "lang": lang, "assumptions": assumptions,
            "missing": [s[k] for k in ("missing_income", "missing_erosion", "missing_soil", "missing_calendar")],
            "index_classes": _class_table(lang), "floor_hint": None,
            "unsupported_priorities": unsupported, "warnings": [], "options": [], "skipped": []}
    if floor < MIN_INDEX:
        base["warnings"].append(s["warn_low_floor"].format(floor=floor, min=MIN_INDEX))
    if cur.get("life_cycle") != "annual" or cur.get("cycle_days_min") is None:
        base["message"] = s["msg_perennial"].format(name=cur_name)
        return base
    cur_index = suit.get(cur_code)
    base["current_gaez"] = {"index": cur_index, "class": gaez_class(cur_index, lang)}
    if not cur_index or cur_index < floor:
        base["warnings"].append(s["warn_current_below"].format(name=cur_name, index=cur_index or 0,
                                                               cls=gaez_class(cur_index, lang), floor=floor))
    default_gaps = {"rice": GAP_RICE_DAYS, "other": GAP_OTHER_DAYS}
    n = seasons if seasons is not None else seasons_for(cur_code, crops, gaps)
    if seasons is None:
        n_default = seasons_for(cur_code, crops, default_gaps)
        if n != n_default:
            base["warnings"].append(s["warn_seasons_changed"].format(name=cur_name, n=n, default=n_default))
    base["seasons"] = n
    if not fits([cur_code] * n, crops, gaps):
        base["message"] = s["msg_not_fit"].format(n=n, name=cur_name)
        return base
    pool = eligible(cur_code, crops, suit, floor)
    keep = [cur_code] * n
    base_mean = components(keep, crops, suit, gaps)["gaez_mean"]
    options = [_describe("keep", s["label_keep"], keep, cur_code, crops, suit, mode, gaps, base_mean, lang)]

    def skip(opt_id, reason):
        base["skipped"].append({"id": opt_id, "reason": reason})

    legumes = [c for c in pool if crops[c]["is_legume"] and fits(keep[:-1] + [c], crops, gaps)]
    if cur["is_legume"]:
        skip("legume", s["skip_legume_current"].format(name=cur_name))
    elif legumes:
        options.append(_describe("legume", s["label_legume"], keep[:-1] + [legumes[0]], cur_code,
                                 crops, suit, mode, gaps, base_mean, lang))
    else:
        skip("legume", s["skip_legume_none"])

    others = [c for c in pool if not crops[c]["is_legume"] and crops[c]["family"] != cur["family"]
              and fits(keep[:-1] + [c], crops, gaps)]
    if others:
        options.append(_describe("other_family", s["label_other_family"], keep[:-1] + [others[0]], cur_code,
                                 crops, suit, mode, gaps, base_mean, lang))
    else:
        skip("other_family", s["skip_other_none"])

    if n < 2:
        skip("diverse", s["skip_diverse_one"])
    else:
        # the main crop stays in at least one season: n - 1 seasons are replaced, never all of them
        seq = _best_diverse(cur_code, n, n - 1, pool, crops, suit, gaps)
        twin = next((o["id"] for o in options if seq and sorted(o["sequence"]) == sorted(seq)), None)
        if not seq:
            skip("diverse", s["skip_diverse_none"])
        elif twin:
            skip("diverse", s["skip_diverse_twin"].format(twin=twin, n=n, m=n - 1))
        else:
            options.append(_describe("diverse", s["label_diverse"], seq, cur_code, crops, suit, mode,
                                     gaps, base_mean, lang))

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
            mode=mode, seasons=seasons, priorities=priorities, gap_rice=gap_rice, gap_other=gap_other, lang=lang))
    base["ranked_by"] = [{"priority": q, "meaning": s[f"prio_{q}"]} for q in sup]
    base["note"] = s["note"]
    base["principle"] = s["principle_multi"] if n >= 2 else s["principle_single"]
    return base
