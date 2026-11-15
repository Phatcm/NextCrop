# NextCrop: crop-rotation decision support for Vietnam

**NASA Space Apps Challenge 2026, challenge "Field Shift: Adapting Farms with NASA Data".**
Team entry **NextCrop** · Ho Chi Minh City local event, 14–15 Nov 2026 · [Demo video (≤30 s)](https://drive.google.com/file/d/1EJ7CVDyAiW8Od_vqXjTzXIZxEunJ27KZ/view?usp=sharing)

Pick a place in Vietnam and the crop that is grown there now. NextCrop compares **at least three crop-rotation options, always including "keep the current crop"**, and says in plain words why, what the benefits and risks are, what is still unknown, and how each option trades off against what the farm does today. It is an **advisory tool**: it supports, and never replaces, the judgement of farmers and local agronomists.

> The interface is in **Vietnamese and English** (VI | EN switch in the header). Vietnamese was the working language of the team, so most of the engineering notes in `docs/` are in Vietnamese; the sections below are in English.

## What you can do
- Click anywhere on the map (or choose a province) and a crop. The map colours every ~9 km cell by how suitable it is for that crop.
- Read 3–4 rotation options for the clicked cell, each with benefits, risks, a trade-off against "keep", and the assumptions behind it. Change the number of seasons, rest days between crops and your priorities.
- Open the **NASA** tab for the monthly climate of the place: temperature (NASA POWER) and, around the six demo areas, vegetation greenness (NASA MODIS NDVI) next to rainfall (CHIRPS).
- In the six demo areas each option also carries a **moisture check**: does the option fit inside the area's rain-fed moist season? (CHIRPS rain against reference evapotranspiration computed from NASA POWER, FAO-56.)

## How NASA data is used (and what is not NASA)
| Data | Source | Where it shows up |
|---|---|---|
| Daily weather, 2015–2025: temperature, humidity, wind, solar radiation | **NASA POWER** | Temperature chart (whole country); reference evapotranspiration (ET0, FAO-56 Penman-Monteith) for the six demo areas, which feeds the moisture check |
| NDVI and its quality flags | **NASA MODIS MOD13Q1** (via AppEEARS) | NDVI chart in the demo areas. Only real, quality-checked composites are used; interpolated values are never shown as measurements |
| Soil moisture, land cover, elevation, cropland mask | **NASA SMAP, MCD12Q1, NASADEM, GFSAD30** | Processed by the pipeline and loaded into the database; not shown in the interface yet |
| Crop suitability index (0–10000) | **FAO GAEZ v5** (not NASA) | The map colours and the ranking of rotation options |
| Rainfall | **CHIRPS v3** (not NASA) | Rain bars and the moisture check; NASA POWER rain was found to differ from CHIRPS by up to 2.3× in one area, so it is not used |

**Honest summary:** the *ranking* of rotation options is driven by the FAO GAEZ suitability index plus explicit rules (crop family, legumes, season length). NASA data feeds the climate context, the NDVI/rain/temperature charts and the moisture check; it does not change the order of the options. See [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Run it yourself
The app reads a PostgreSQL database that the pipeline fills. The hosted demo uses our own database, which is **not** part of this repository, so to run the app you first load your own copy with the pipeline (see [pipeline/README.md](pipeline/README.md); it needs a free NASA Earthdata account for the AppEEARS data).

```bash
# 1. API + web UI (the API serves the UI at "/")
cd app/api
pip install -r requirements.txt
export APP_DATABASE_URL="postgresql://user:password@host:5432/db?sslmode=require"   # read-only access is enough
uvicorn fieldshift_api.main:app --port 8000        # UI: http://localhost:8000/   API docs: /docs

# 2. Tests (no database needed except the Postgres ones, which CI runs)
cd app/api && pytest
cd app/web && node --test                           # Node 20+, no packages to install
cd pipeline && pytest
```
More detail: [app/README.md](app/README.md), [app/api/README.md](app/api/README.md).

## Repository layout
```
app/api/      FastAPI backend, read-only (every request runs in a READ ONLY transaction)
app/web/      the interface: plain HTML/CSS/JavaScript (no build step), MapLibre GL for the map, hand-written SVG charts
pipeline/     fetch, clean, check and package the data; load it into PostgreSQL (and a data lake)
docs/         data contract, rotation rules, data audit and known data issues (mostly Vietnamese)
.github/      CI: API, web and pipeline tests on every pull request
```

## Documents
- [docs/rotation-rules.md](docs/rotation-rules.md): how options are generated, what the numbers mean, what is adjustable.
- [docs/data-contract.md](docs/data-contract.md): tables between the pipeline and the app.
- [docs/data-issues.md](docs/data-issues.md), [docs/data-audit.md](docs/data-audit.md), [docs/system-audit.md](docs/system-audit.md): data quality, known issues and audits.
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md): what this tool does **not** do.
- [docs/AI_USAGE.md](docs/AI_USAGE.md): declaration of the AI tools used.

## Limitations in one paragraph
One cell (~80–85 km²) gets one answer, so results are **not** for a single field. The suitability index is a *potential*, not a yield or a profit. Rain and NDVI exist only for six demo areas (each about 10 km across; five of the six locations are still estimated, see the pipeline config). Province outlines in the map are from 2008 and do not follow the 2025 mergers. Nothing here is a forecast. Details in [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Data credits
- FAO & IIASA. 2025. Global Agro-ecological Zoning version 5 (GAEZ v5) Model Documentation (CC BY 4.0).
- NASA POWER, MODIS (MOD13Q1, MCD12Q1), SMAP, NASADEM, GFSAD30: NASA open data.
- CHIRPS v3 (Climate Hazards Center, UC Santa Barbara).
- Province boundaries: geoBoundaries (gbOpen, ADM1, Vietnam, simplified).
- Base map imagery: Esri World Imagery (Esri, Maxar, Earthstar Geographics), loaded from Esri at run time; its terms of use have not been reviewed yet.
- Map library: MapLibre GL JS (BSD-3-Clause), loaded from a CDN.

## Team and AI tools
Built by the two members of team NextCrop (GitHub: `Phatcm`, `hnguyen021`). AI tools were used and are declared in [docs/AI_USAGE.md](docs/AI_USAGE.md). Recommendations are advisory only.

---

# Tiếng Việt (tóm tắt)

**NextCrop** là sản phẩm dự thi NASA Space Apps Challenge 2026, đề *Field Shift: Adapting Farms with NASA Data*. Người dùng chọn vị trí và cây đang trồng; công cụ so sánh **ít nhất ba phương án luân canh (gồm "giữ nguyên")**, nêu lợi ích, rủi ro, thông tin còn thiếu và mức đánh đổi, bằng lời dễ hiểu, tiếng Việt và tiếng Anh. Đây là công cụ **hỗ trợ**, không thay thế phán đoán của nông dân hay cán bộ khuyến nông.

- **Dữ liệu NASA** (POWER, MODIS NDVI, SMAP, MCD12Q1, NASADEM, GFSAD30) nuôi pipeline, tab "NASA" (nhiệt độ, mưa, độ xanh theo tháng) và nhãn *kiểm tra độ ẩm* của từng phương án ở 6 vùng demo. **Xếp hạng phương án dựa trên chỉ số độ phù hợp FAO GAEZ v5** cùng các luật về họ cây, họ đậu, độ dài vụ; dữ liệu NASA không đổi thứ tự các phương án.
- Chỉ số GAEZ (0–10000) là **tiềm năng** của đất, không phải năng suất hay lợi nhuận; một ô ~80 km² chỉ cho một đáp án, không dùng cho từng thửa.
- Mưa (CHIRPS) không phải dữ liệu NASA; mưa và NDVI chỉ có ở 6 vùng demo; ranh giới tỉnh trong bản đồ là năm 2008.
- Cách chạy, cấu trúc, tài liệu kỹ thuật: xem các phần tiếng Anh ở trên và `docs/`, `app/README.md`, `app/api/README.md`.
- Công cụ AI đã dùng được khai báo tại [docs/AI_USAGE.md](docs/AI_USAGE.md).
