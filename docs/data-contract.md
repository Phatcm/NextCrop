# Hợp đồng dữ liệu giữa pipeline và app (v1, thay bản nháp "file tĩnh trên R2")

Quyết định: **app đọc từ PostgreSQL**. Pipeline lưu dữ liệu ở Cloudflare R2 (data lake) rồi nạp vào Postgres bằng `pipeline/load_postgres.py`. App không gọi API NASA/FAO lúc chạy.

```
pipeline/run_etl.py -> data/{bronze,silver,gold} -> pipeline/upload_r2.py -> R2 -> pipeline/load_postgres.py -> PostgreSQL
```

## Schema PostgreSQL `field_shift`
Nguồn thật là [pipeline/db/migrations/001_init.sql](../pipeline/db/migrations/001_init.sql) (có chú thích từng bảng). App nên đặt `search_path = field_shift`.

| Bảng | Khóa | Nội dung |
|---|---|---|
| `dim_region` | `region_id` | vùng demo: bbox, tỉnh, vùng sinh thái, kết quả kiểm tra đất canh tác (MODIS và GFSAD) |
| `crop_profile` | `crop_code` | họ thực vật xác minh qua GBIF; giá, năng suất, doanh thu thô Việt Nam (FAOSTAT, trung bình quốc gia; **không phải lợi nhuận**); lớp chống xói mòn kèm `cover_confidence`. NULL = không có nguồn (taro, cọ dầu, cà chua, dừa); `faostat_match = proxy` là mục thay thế |
| `dim_crop` | `crop_code` | 24 cây GAEZ, tên tiếng Việt, `name_verified`, đặc tính cây (migration 003, 005): `res02_code`, `gaez_group`, `life_cycle`, `is_legume`, `family`, `cycle_days_min/max`, `min_temp_c`, `water_regime`, nguồn từng nhóm cột. Trống = chưa có nguồn, không đoán |
| `power_daily`, `power_monthly` | `region_id` + ngày/tháng | khí hậu NASA POWER 2015–2025. Mưa ngày bị ERA5 phủ nhận (nhiễu của POWER) là `NULL` kèm lý do trong `power_daily.prectotcorr_qa` |
| `rain_monthly_best` | `region_id, month` | **mưa tháng (mm/tháng) app phải dùng**: CHIRPS v3 (vệ tinh có hiệu chỉnh bằng trạm đo); `best_source = power_fallback` chỉ khi thiếu tháng CHIRPS |
| `rain_validation` | `region_id, year` | tổng mưa năm POWER so với CHIRPS, `ratio`, `status` (`ok` / `power_high` / `power_low`; lệch > 30%) |
| `ndvi_series` | `region_id, source_key, date` | NDVI sau QA, `source` = `measured` / `interpolated` / `missing` |
| `ndvi_raw` | như trên | NDVI trước nội suy, kèm `valid_frac`, `cloud_frac` |
| `smap_daily` | `region_id, date` | độ ẩm đất SMAP; `sm_recommended` là NULL khi NASA không khuyến nghị |
| `gaez_suitability` | `region_id, crop_code, input_mode, period, ssp` | mức thích hợp 0–10000, 4 mức đầu vào; lớp đất canh tác `RES05-SUX` (cùng `gaez_grid`), thống kê các ô 5 phút cung phủ bbox vùng (`n_px` 4–9) |
| `gaez_grid` | `lat, lon, crop_code` | GAEZ cả nước, lớp **đất canh tác** `RES05-SUX`, lưới gốc 5 phút cung (~9 km; tâm ô `24 − (i+0,5)/12`, `102 + (j+0,5)/12`): cột `hilm, hrlm, lilm, lrlm` (0–10000, có thể chạm trần 10000) cho mỗi cây; app tra ô gần điểm người dùng chọn (trong 0,05°) |
| `gfsad_points`, `landcover_by_year`, `landcover_classes`, `terrain` | theo vùng | đất canh tác 30 m, lớp phủ MODIS, độ cao |
| `vn_grid_monthly` | `lat, lon, param, yyyymm` | lưới khí hậu cả nước (cho bản đồ) |
| `pipeline_run` | `run_id` | lần nạp nào đang nằm trong DB |

View cho app: `v_region_overview` (một dòng mỗi vùng kèm số liệu đủ/thiếu), `v_crop_ranking` (xếp hạng cây theo vùng và mức đầu vào).

## Quy ước app phải tuân theo
- Ô thiếu dữ liệu là `NULL`, **không bao giờ là 0**. NDVI có `source = 'interpolated'` là giá trị nội suy, phải hiển thị khác với giá trị đo.
- Mức đầu vào GAEZ: `HILM` tưới + đầu vào cao, `HRLM` mưa + cao, `LILM` tưới + thấp, `LRLM` mưa + thấp. Chênh lệch giữa các mức rất lớn (lúa nước An Giang: 8.460 ở `HRLM`, 2.472 ở `LRLM`), không so sánh khác mức với nhau. Chỉ số **không đơn điệu** theo mức đầu vào: ở 22/144 cặp vùng-cây, `LRLM` cao hơn `HRLM` (ví dụ cà phê Đắk Lắk 3.331 so với 2.420), nên đừng giả định đầu vào cao luôn tốt hơn.
- Chỉ số GAEZ là tiềm năng trung bình 20 năm, **không** nhận diện cây bằng một con số (nhiều cây có thể trùng giá trị).
- **Mưa đã qua QA (DATA-05):** `prectotcorr` rỗng + `prectotcorr_qa` có chữ nghĩa là ngày đó bị loại vì vượt ngưỡng; app hiển thị "đã loại giá trị phi lý", không vẽ thành 0. Tháng/năm chứa ngày đó đã được tính lại từ các ngày còn lại.
- **Mưa lấy từ `rain_monthly_best`, không lấy từ `power_*.prectotcorr` (DATA-06/07):** POWER là mô hình ~0,5°, lệch tới 2,3 lần ở Ninh Thuận (2.031 mm/năm so với 896 mm của CHIRPS) và sai năm 2015 ở Đắk Lắk (423 so với 1.653 mm). `power_*` giữ nguyên để đối chiếu và dùng cho các biến khác (nhiệt độ, nắng, ẩm). Đây là ước lượng ~5 km, không phải số đo trạm; gold có `climate.rain_best` cùng nội dung kèm chuẩn khí hậu 12 tháng.
- **`gaez_grid`:** hình chữ nhật 102–110°E, 8–24°N nên có cả ô thuộc Lào, Campuchia, Trung Quốc; app chỉ tra điểm nằm trong Việt Nam. Ô không có pixel hợp lệ (biển) không có dòng; mức không có dữ liệu là `NULL`. Truy vấn mẫu: `SELECT * FROM gaez_grid WHERE crop_code='RCW' ORDER BY (lat-:lat)^2+(lon-:lon)^2 LIMIT 1`.
- `dim_region.status = 'candidate'`: tọa độ chưa xác nhận ngoài thực địa.
- Mỗi vùng là một khung ~0,1° (~11 km); dữ liệu POWER ~0,5° nên không phân biệt từng thửa ruộng.

## R2
Cấu trúc bucket, manifest và catalog: xem `pipeline/README.md` (mục Cloudflare R2). Bản JSON "gold" (`gold/v<schema>/<vùng>.json`) vẫn được tạo, dùng khi cần xuất file tĩnh hoặc kiểm tra nhanh; không phải đường đọc chính của app.

## Còn thiếu so với hợp đồng gốc
Bảng cây trồng (mùa trồng, thời gian sinh trưởng, ngưỡng nhiệt, nhu cầu nước, họ đậu, độ phủ đất, giá thị trường, họ thực vật) chưa có trong dữ liệu. Kết quả kiểm tra đầy đủ và các vấn đề độ chính xác: [data-audit.md](data-audit.md).

## Điều cần chốt (Phat và Hùng)
Danh sách vùng demo cuối cùng (hiện có 6 vùng, 5 vùng còn là `candidate`); cách app truy cập Postgres (kết nối trực tiếp hay qua API); phiên bản Postgres và nhà cung cấp; có cần `R2_PUBLIC_BASE_URL` cho file tĩnh hay không.
