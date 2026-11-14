# Vấn đề dữ liệu và bàn giao (14/11/2026)

Danh sách việc còn lại, viết để người tiếp theo (Phát) làm tiếp mà không cần hỏi lại. Chi tiết cuộc kiểm tra: [data-audit.md](data-audit.md). Mô hình dữ liệu: [data-contract.md](data-contract.md). Cấu hình Postgres: [postgres-hosting.md](postgres-hosting.md).

Quy ước: **[ĐÃ XÁC NHẬN]** = đã kiểm tra bằng dữ liệu hoặc API thật; **[CHƯA KIỂM CHỨNG]** = đề xuất, chưa thử.

## 1. Trạng thái hiện tại
**Đã xong và đã kiểm tra**
- ETL 7 nguồn: POWER (điểm + lưới cả nước), AppEEARS (MOD13Q1 NDVI+QA, SMAP L3, MCD12Q1, NASADEM), GFSAD30SEACE, FAO GAEZ v5 (24 cây × 4 mức), GIBS (dự phòng). 6 vùng, 2015–2025.
- R2 `field-shift-nasa`, lần chạy `20261114T030142Z`: 633 object, sha256 khớp manifest, `--verify` 0 lỗi, chạy lại không đẩy trùng.
- Migration Postgres `001_init.sql` + `load_postgres.py`; `--dry-run` qua sạch 402.709 dòng; CI xanh (60 test, test Postgres 17 thật qua).

- **Nạp Postgres thật (OPS-01): đã xong.** Neon (PostgreSQL 18.7): 402.709 dòng, 19/19 kiểm tra qua (lần đầu); **14/11 lần nạp thứ hai: 625.429 dòng, 23/23 kiểm tra qua, run `20261114T041950Z`, migration 002 đã áp**, chạy lại lần hai vẫn qua; app đọc được qua cả chuỗi pooled và direct.

**Chưa xong**: bảng cây trồng (DATA-01) và các vấn đề độ chính xác bên dưới.

**Vị trí**
- Mã: repo `Phatcm/field-shift`; PR #1 đã vào `main`. Nhánh `feat/gaez-national-and-rain-qa` (DATA-04/05) chưa mở PR.
- Dữ liệu sinh ra: `pipeline/data/` trên máy chạy ETL, **không commit**; dựng lại được từ R2 hoặc từ bronze bằng `python run_etl.py --offline`.
- Database: dự án Neon `tiny-flower-76765987` (tổ chức `org-withered-wave-01543450`, nhánh `production`), schema `field_shift`, đang chứa lần chạy R2 `20261114T030142Z` (xem bảng `pipeline_run`). `DATABASE_URL` (trực tiếp) dùng cho pipeline, `DATABASE_URL_POOLED` cho app. Phát cần được thêm vào tổ chức Neon và tự lấy chuỗi kết nối trong Neon Console.
- **Bí mật nằm trong `pipeline/.env` chỉ trên máy hiện tại.** Phát cần được cấp riêng (không qua repo hay chat): `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD`, `DATABASE_URL`.

## 2. Thứ tự làm đề xuất (thi 14–15/11)
1. **DATA-01** bảng cây trồng: chặn sản phẩm, không có thì app chưa chấm điểm được luân canh.
2. **DATA-05** chặn mưa bất thường: lỗi rõ ràng, sửa nhanh.
3. ~~OPS-01 nạp Postgres thật~~ (xong, xem mục 4). Còn lại: sau khi sửa dữ liệu (DATA-05, DATA-01...) chạy lại `upload_r2.py` rồi `load_postgres.py`.
4. **DATA-10 và DATA-04** chốt vùng demo.
5. **DATA-03** độ dốc và bốc thoát hơi nước (cho ưu tiên "xói mòn", "nước").
6. Nếu còn thời gian: DATA-06/07 (đối chiếu mưa), DATA-08 (SMAP L4), DATA-09 (Aqua).

| ID | Mức | Việc | Gợi ý người làm |
|---|---|---|---|
| DATA-01 | Nghiêm trọng | Thiếu bảng cây trồng | Hùng (theo phân công) |
| DATA-02 | Cao | Không có cây/luân canh hiện tại và định nghĩa phương án | Hùng + Phát |
| DATA-03 | Cao | Thiếu đầu vào: độ dốc, bốc thoát hơi nước, thấm nước, đất | Phát |
| DATA-04 | ~~Trung bình~~ Đã xử lý phần GAEZ | Chỉ 6 vùng có đủ dữ liệu (GAEZ đã có cả nước, xem mục 3) | Cả hai |
| DATA-05 | ~~Cao~~ Đã xử lý (còn 3 ngày dưới ngưỡng và lưới) | Mưa phi lý (691 mm/ngày) lan sang bảng tháng, năm, chuẩn khí hậu | Phát |
| DATA-06 | Cao | Ninh Thuận 1.961 mm/năm, nhiều khả năng quá cao | Phát |
| DATA-07 | Trung bình | Năm 2015 khô cực đoan | Phát |
| DATA-08 | Trung bình | SMAP chất lượng khuyến nghị 0% ở 4/6 vùng | Phát |
| DATA-09 | Trung bình | NDVI nội suy nhiều ở đồng bằng | Phát |
| DATA-10 | Trung bình | MODIS và GFSAD mâu thuẫn ở Sơn La, Đắk Lắk | Cả hai |
| DATA-11 | Thấp | GAEZ là tiềm năng, không đơn điệu | Hùng (giao diện) |
| DATA-12 | Thấp | Độ phủ thời gian: không có 2026, mốc NDVI trước 2015 | Phát |
| DATA-13 | Thấp | Đơn vị và ngày tạo chưa có trong Postgres | Phát |
| OPS-01..10 | xem mục 4 | | |

## 3. Vấn đề dữ liệu

### DATA-01 · Nghiêm trọng · Thiếu bảng cây trồng
- **Vấn đề:** hợp đồng dữ liệu mục 2.2 yêu cầu bảng cây trồng; `dim_crop` hiện chỉ có `crop_code`, `name_vi`, `name_verified` cho 24 cây.
- **Bằng chứng:** `python audit_r2.py`, mục I, dòng "crop-table fields ... still missing".
- **Cột cần có:** họ thực vật (cần cho chu kỳ sâu bệnh, ngoài hợp đồng gốc), mùa trồng, thời gian sinh trưởng (ngày), nhiệt độ thích hợp min/max, ngưỡng rét, ngưỡng nóng, nhu cầu nước (mm), họ đậu (cố định đạm), độ phủ đất/chống xói mòn, giá thị trường, **nguồn của từng cột**.
- **Hướng xử lý:** điền cho 24 cây (hoặc rút gọn còn nhóm cây dùng để luân canh). Kỹ thuật: thêm cột vào `silver/dim_crop` và migration `002_*.sql` (`ALTER TABLE dim_crop ADD COLUMN ...`), cập nhật `loader` và test. File `pipeline/data/crops_template.csv` cũ chỉ có trên máy local (thư mục `data/` không commit) và đang trống, không dùng được. FAO EcoCrop có thể là nguồn tham số; **[CHƯA KIỂM CHỨNG]** độ phủ cây và giấy phép.
- **Xong khi:** mọi cây trong danh sách chốt có đủ cột và nguồn; `python load_postgres.py --dry-run` qua.

### DATA-02 · Cao · Không có cây/luân canh hiện tại, không có định nghĩa phương án
- **Vấn đề:** đề yêu cầu so sánh ≥3 phương án luân canh gồm phương án hiện tại; dữ liệu không có "cây hiện tại" của vùng và không có định nghĩa phương án (chuỗi cây theo mùa).
- **Hướng xử lý:** quyết định ai định nghĩa. Cách đơn giản: người dùng chọn cây hiện tại trong app, Hùng định nghĩa các mẫu luân canh (bảng `rotation_option`) hoặc quy tắc sinh phương án từ bảng cây trồng.
- **Xong khi:** mỗi cây hiện tại có ≥3 phương án (gồm giữ nguyên) hoặc có quy tắc sinh ra chúng.

### DATA-03 · Cao · Thiếu đầu vào cho 5 ưu tiên (nước, đất, đạm, xói mòn, thu nhập)
- **Độ dốc / xói mòn:** `terrain` chỉ có độ cao tại 25 điểm/vùng (trung vị, min, max), không đủ tính độ dốc. Cần DEM dạng lưới; **[CHƯA KIỂM CHỨNG]** cách lấy (NASADEM theo vùng).
- **Bốc thoát hơi nước / cân bằng nước:** POWER **không có `PET`** (gọi trả lỗi 422 **[ĐÃ XÁC NHẬN]**). Có `EVPTRNS` (năng lượng bốc thoát hơi nước) và `EVLAND` **[ĐÃ XÁC NHẬN]**; đơn vị chưa kiểm tra. Hai hướng: thêm hai biến này vào `power.parameters` trong `config.yaml` (nhớ đổi đơn vị), hoặc tính PET kiểu Hargreaves từ `t2m_max`, `t2m_min`, bức xạ rồi cân bằng nước = mưa − PET theo tháng.
- **Thấm nước:** SMAP L4 `SPL4SMGP.008` có lớp `Geophysical_Data_soil_water_infiltration_flux` trong AppEEARS **[ĐÃ XÁC NHẬN]**; chưa lấy dữ liệu thử. Đây là sản phẩm đồng hóa mô hình, không phải đo vệ tinh thuần.
- **Đất (kết cấu, hữu cơ):** chưa có nguồn nào. ISRIC SoilGrids là ứng viên (không phải NASA) **[CHƯA KIỂM CHỨNG]**. Đề bài cho phép ghi "chỗ còn thiếu thông tin", nên có thể khai báo thiếu trong app thay vì tìm cho bằng được.
- **Đạm, thu nhập:** phụ thuộc DATA-01.

### DATA-04 · ĐÃ XỬ LÝ phần GAEZ (14/11/2026) · Chỉ 6 vùng có đủ dữ liệu
- **Đã làm:** `gaez_grid` (silver + bảng Postgres, migration `002`): GAEZ v5 cho **cả Việt Nam** (102–110°E, 8–24°N), gộp ~0,9 km thành ô 0,1° (~11 km), 24 cây × 4 mức đầu vào, dạng rộng `hilm, hrlm, lilm, lrlm`. Mọi điểm người dùng chọn đều tra được ô gần nhất. Cấu hình `gaez_grid` trong `config.yaml`; mã `src/extractors/gaez_grid.py`.
- **[ĐÃ XÁC NHẬN]** Giá trị ô khớp từng pixel với file đã cắt bằng rasterio (RCW/HRLM, cả cửa sổ 1.920 × 960 pixel). Bộ đọc GeoTIFF của Hùng và rasterio cho cùng kết quả ở cả 3 vùng thử (Thái Bình, Đắk Lắk, Sơn La; RCW/COF/MZE).
- **Chạy:** đọc từ xa mất ~110 giây/file, 96 file khoảng 45 phút với 4 luồng. Nếu đã có file tif cắt sẵn thì `python run_etl.py --gaez-local-dir <thư mục>` chỉ mất vài giây (0,1 giây/file đo thực tế). Kết quả lưu trong `data/bronze/gaez/grid_0.1deg/`, chạy lại `--offline` không cần mạng.
- **Giới hạn:** hình chữ nhật gồm cả Lào, Campuchia, Trung Quốc (9.280 ô có dữ liệu cho một cặp cây/mức, chưa lọc theo biên giới); app chỉ tra điểm trong Việt Nam. Vẫn là tiềm năng GAEZ (DATA-11).
- **Còn lại của DATA-04:** NDVI, SMAP, lớp phủ đất vẫn chỉ có 6 vùng; khí hậu POWER đã có cả nước.

### DATA-05 · ĐÃ XỬ LÝ (14/11/2026) · Mưa phi lý lan sang nhiều bảng
- **Đã làm:** `src/transformers/rain_qa.py`, cấu hình `power.rain_qa` (`max_daily_mm: 180` làm giới hạn dự phòng, `cross_check` ERA5, `min_valid_frac: 0.8`). Ngày vượt ngưỡng → `prectotcorr = NULL` (không phải 0) kèm lý do ở cột mới `prectotcorr_qa`; tháng và năm chứa ngày đó được tính lại từ các ngày còn lại (mm/ngày), tháng/năm khác giữ nguyên số của POWER. Gold có `climate.rain_qa.removed_days` và một dòng trong `caveats`. Loader Postgres kiểm tra: rỗng mưa chỉ khi có cờ, không còn ngày bị ERA5 phủ nhận.
- **Cách làm hiện tại (14/11): đối chiếu tự động với ERA5, không dựa vào ngưỡng tay.** Ngày POWER > 100 mm được so với ERA5 (Open-Meteo, CC BY 4.0, cùng điểm, lấy giá trị lớn nhất trong ±1 ngày vì ranh giới ngày hai nguồn lệch nhau); loại nếu ERA5 < 0,5 × POWER, giữ nếu ERA5 xác nhận. Mất mạng và không có cache thì quay về giới hạn cố định 180 mm (`max_daily_mm`) và ETL báo "CHƯA ĐỦ". Cấu hình: `power.rain_qa.cross_check`; mã `src/extractors/era5_rain.py`, `src/transformers/rain_qa.py`; ERA5 chỉ để kiểm tra, không lưu thành dữ liệu sản phẩm, nhưng được cache trong `bronze/era5` để chạy lại `--offline` ra cùng kết quả. Gold ghi `climate.rain_qa.removed_days` và `kept_after_check`.
- **Kết quả trên 6 vùng, 2015–2025 (9 ngày bị loại trên 24.108 ngày-vùng):**

  | Vùng | Ngày | POWER | ERA5 | Ghi chú |
  |---|---|---|---|---|
  | An Giang | 2020-06-14 | 691 mm | 22 mm | nhiễu rõ ràng |
  | An Giang | 2020-06-15 | 141 mm | 22 mm | nhiễu (ngưỡng cố định bỏ sót) |
  | Sơn La | 2022-02-04 | 211 mm | 2 mm | nhiễu rõ ràng |
  | Thái Bình | 2020-10-18 | 205 mm | 17 mm | nhiễu rõ ràng |
  | Thái Bình | 2023-10-13 | 144 mm | 0,3 mm | nhiều khả năng nhiễu |
  | Đắk Lắk | 2019-08-07 | 200 mm | 29 mm | nhiễu rõ ràng |
  | Ninh Thuận | 2025-10-26 | 127 mm | 24 mm | **ranh giới** |
  | Sóc Trăng | 2020-06-19 | 110 mm | 28 mm | **ranh giới** |
  | Sóc Trăng | 2020-09-18 | 103 mm | 18 mm | **ranh giới** |

  Giữ lại vì ERA5 xác nhận: Thái Bình 2024-09-07 (155 mm so với ERA5 144 mm, bão Yagi), 2024-09-10/11 (132/127 mm so với 120 mm), Thái Bình 2022-09-08 (105/59), 2025-07-22 (106/84), Ninh Thuận 2018-11-18 (101/61).
- **Giới hạn cần nói khi trình bày:** ERA5 cũng là tái phân tích (0,25°), không phải số đo trạm, và có thể bỏ sót mưa đối lưu cục bộ; ba ca "ranh giới" (103–127 mm) có thể là mưa thật mà ERA5 không thấy. Không có số liệu trạm trong dự án để phân xử. Muốn thận trọng hơn: nâng `candidate_mm` lên 150 (chỉ xét ngày thật sự cực đoan) hoặc hạ `min_ratio` xuống 0,3.
- **Chưa xử lý:** lưới khí hậu cả nước (`vn_grid_monthly`) là dữ liệu tháng nên không áp được quy tắc theo ngày; ô lưới chứa An Giang vẫn mang số tháng 6/2020 cao bất thường.

### DATA-06 · Cao · Ninh Thuận 1.961 mm/năm, nhiều khả năng quá cao
- **Vấn đề:** Ninh Thuận được biết là vùng khô nhất nước. Theo hiểu biết của người kiểm tra, Phan Rang chỉ khoảng 700 mm/năm; **[CHƯA KIỂM CHỨNG]**, trong dữ liệu không có trạm để đối chiếu. POWER ~0,5° trộn đồng bằng khô với núi ẩm nên không thể hiện được vùng khuất mưa. Mùa mưa (đỉnh tháng 9–11) thì đúng, lượng thì nhiều khả năng sai.
- **Hướng xử lý:** thêm nguồn mưa độc lập. Đề bài nêu **GPM IMERG** (NASA, ~10 km); **[CHƯA KIỂM CHỨNG]** cách truy cập (GES DISC, cần Earthdata). CHIRPS là phương án thay thế. So sánh tổng năm POWER và nguồn thứ hai cho cả 6 vùng.
- **Xong khi:** bảng so sánh mưa hai nguồn; vùng nào lệch quá ~30% thì ghi cảnh báo hoặc dùng nguồn thứ hai.

### DATA-07 · Trung bình · Năm 2015 khô cực đoan ở mọi vùng
- **Vấn đề:** Đắk Lắk 423 mm (các năm khác 1.866–2.316); mùa mưa 2015 chỉ 15–27 mm/tháng. Phù hợp El Niño 2015–16 nhưng quá cực đoan.
- **Hướng xử lý:** kiểm chứng cùng DATA-06 (so với nguồn thứ hai). Nếu nguồn thứ hai lệch lớn, ghi chú rằng 2015 không đáng tin.

### DATA-08 · Trung bình · SMAP chất lượng khuyến nghị 0% ở 4/6 vùng
- **Bằng chứng [ĐÃ XÁC NHẬN]:** Sóc Trăng 81%, Thái Bình 64%; Sơn La, Ninh Thuận, Đắk Lắk, An Giang 0%. Đã đối chiếu mô tả của NASA: do thực vật dày, không phải lỗi giải mã.
- **Hướng xử lý:** thêm SMAP L4 `SPL4SMGP.008` (9 km, hàng ngày, lớp `sm_surface`, `sm_rootzone`, `sm_profile`) **[ĐÃ XÁC NHẬN có trong AppEEARS]**; thêm một task trong `config.yaml` → `appeears.tasks`. Ghi rõ đây là sản phẩm đồng hóa mô hình.

### DATA-09 · Trung bình · NDVI phải nội suy nhiều ở đồng bằng
- **Bằng chứng [ĐÃ XÁC NHẬN]:** tỷ lệ đo được: Sóc Trăng 60% (2022: 39%), An Giang 66% (2022: 52%), Thái Bình 67%, Đắk Lắk 80%, Sơn La 89%, Ninh Thuận 94%. Số vụ ở Sóc Trăng lúc 1 lúc 3 đỉnh.
- **Hướng xử lý:** thêm Aqua `MYD13Q1.061` **[ĐÃ XÁC NHẬN có trong AppEEARS]** để tăng số lần quan sát (nhiều khả năng lệch 8 ngày so với Terra, **[CHƯA KIỂM CHỨNG]**). Khi trình bày, nêu rõ tỷ lệ nội suy và đừng kết luận số vụ cho Sóc Trăng.

### DATA-10 · Trung bình · MODIS và GFSAD mâu thuẫn về đất canh tác
- **Bằng chứng [ĐÃ XÁC NHẬN]:** Sơn La 0% (MODIS) so với 58% (GFSAD); Đắk Lắk 36% so với 50%. Các vùng đồng bằng khớp nhau (Thái Bình 60/65, An Giang 84/82, Sóc Trăng 80/89, Ninh Thuận 56/64). Cao độ xác nhận đúng địa điểm (Sơn La 674 m, Đắk Lắk 454 m).
- **Hướng xử lý:** chốt có giữ hai vùng này không. Nếu giữ, nên chọn lại khung bbox theo các điểm GFSAD có `crop_frac` cao (`silver/gfsad_points`). **Lưu ý:** đổi bbox làm AppEEARS gửi lại task mới, mất khoảng 30–90 phút (ước tính).

### DATA-11 · Thấp · GAEZ là tiềm năng, không đơn điệu
- **Bằng chứng [ĐÃ XÁC NHẬN]:** 22/144 cặp vùng-cây có `LRLM` > `HRLM`; An Giang lúa cạn (9.410) cao hơn lúa nước (8.460) ở `HRLM`; Sơn La: giá trị tốt nhất ở cả 4 mức đầu vào chỉ 1.363–1.663 (thang 0–10.000).
- **Hướng xử lý:** hiển thị kèm chú thích (giao diện). GAEZ có kịch bản tương lai cho thanh trượt (`FP2140`…), nhưng ghi chú của repo nói tên file cần kiểm tra **[CHƯA KIỂM CHỨNG]**.

### DATA-12 · Thấp · Độ phủ thời gian
- POWER và MODIS kết thúc cuối 2025 (thiếu ~10,5 tháng của 2026); GFSAD chỉ có 2015; GIBS chỉ 2023–2025.
- Mốc NDVI sớm nhất là **2014-12-19** (composite 16 ngày đầu tiên của 2015 bắt đầu từ cuối 2014) trong khi `dim_region.year_start = 2015`: lệch nhỏ, cần lọc hoặc ghi chú.

### DATA-13 · Thấp · Đơn vị và ngày tạo chưa có trong Postgres
- Đơn vị (°C, mm/ngày, %, m/s, MJ/m²/ngày, m³/m³) chỉ nằm trong JSON gold; bảng Postgres không có. `dim_region` không có ngày tạo (chỉ `pipeline_run.loaded_at`).
- **Hướng xử lý:** `COMMENT ON COLUMN` ghi đơn vị trong migration mới, hoặc thêm bảng `column_units`.

## 4. Vấn đề vận hành

### OPS-01 · ĐÃ XONG (14/11/2026) · Nạp Postgres đầu-cuối với dữ liệu thật
- Đã chạy `python load_postgres.py` trên Neon: kéo 63 object silver từ R2 (sha256 khớp), áp `001_init`, nạp 402.709 dòng trong ~17 giây, 19/19 kiểm tra qua, commit. Chạy lần hai vẫn qua và `pipeline_run` vẫn một dòng (làm mới toàn bộ an toàn). Đọc thử bằng cả chuỗi pooled và direct: 6 vùng, view và xếp hạng cây đúng.
- Còn lại cho lần sau: mỗi khi dữ liệu thay đổi, chạy lại `upload_r2.py` rồi `load_postgres.py`.
- Lưu ý: cả pipeline và app đang dùng role `neondb_owner` (chủ database). Nên tách role chỉ đọc cho app (xem [postgres-hosting.md](postgres-hosting.md) mục 2).

### OPS-02 · Trung bình · Dựng server Postgres
- Chi tiết role, mạng, TLS, `pg_hba.conf` trong [postgres-hosting.md](postgres-hosting.md). Các điểm hay vướng: mở cổng nhưng không ra Internet, database phải UTF8, bảng của app đặt schema khác và không tạo khóa ngoại vào bảng pipeline. Phần cấu hình server chưa thử trên máy của dự án.

### OPS-04 · Thấp · Thư mục cũ `C:\Workspace\field_shift_etl`
- Bản trùng lặp của pipeline (đã chuyển vào `pipeline/`). Xóa sau khi xác nhận repo chạy được trên máy của Phát.

### OPS-05 · Thấp · Đăng nhập Earthdata
- AppEEARS cần tên đăng nhập + mật khẩu. `EARTHDATA_TOKEN` cho tải tile GFSAD **chưa kiểm chứng**. Tải GFSAD cần truy cập được `urs.earthdata.nasa.gov`; trên mạng đã dùng, host này bị chặn và phải bật VPN.

### OPS-06 · Trung bình · README của `app/` còn ghi "đọc file tĩnh"
- README gốc và `data-contract.md` đã sửa theo quyết định dùng PostgreSQL; `app/README.md` chưa sửa (người làm app cập nhật).

### OPS-07 · Trung bình · Thể lệ và hồ sơ nộp
- Mục "Công cụ AI đã dùng" trong ba README còn trống; cần khai báo (Claude dùng cho mã pipeline, kiểm tra dữ liệu, tài liệu).
- Quy định: phần lõi làm trong 14–15/11 và lịch sử commit là bằng chứng. Quyết định thời điểm mở PR và merge.

### OPS-08 · Thấp · Danh tính commit
- Các commit mang tên `hnguyen021` (tài khoản `gh` đăng nhập trên máy, theo yêu cầu "dùng danh tính của Hùng"). `git config user.name/email` chưa đặt trên máy. Xác nhận cách ghi tác giả cho các commit sau.

### OPS-09 · Thấp · Cảnh báo CI
- Node 20 sắp ngừng hỗ trợ và `ubuntu-latest` sẽ chuyển sang Ubuntu 26 từ 19/10/2026. Hiện chưa gây lỗi.

### OPS-10 · Trung bình · App đọc dữ liệu từ đâu
- `R2_PUBLIC_BASE_URL` đang trống: bucket chưa công khai. App dùng Postgres nên chưa cần, nhưng nếu muốn xuất JSON tĩnh (gold) thì phải quyết định mở đọc công khai.

## 5. Quyết định cần chốt
1. Danh sách vùng demo cuối (giữ hay bỏ Sơn La, Đắk Lắk; dùng Ninh Thuận làm vùng khô thế nào).
2. Ai định nghĩa phương án luân canh và bằng cách nào (DATA-02).
3. Có thêm GPM / SMAP L4 / Aqua không, hay chỉ ghi cảnh báo.
4. Nhà cung cấp và cách app truy cập Postgres.
5. Thời điểm mở PR và merge; bucket có công khai không.

## 6. Cách chạy và tái hiện
```powershell
cd pipeline
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env          # điền khóa được cấp
.\.venv\Scripts\python.exe -m pytest                    # 58+ test, không cần mạng
.\.venv\Scripts\python.exe audit_r2.py                  # kiểm tra dữ liệu trên R2 (các mục A..I, G2)
.\.venv\Scripts\python.exe upload_r2.py --verify        # bucket khớp manifest
.\.venv\Scripts\python.exe load_postgres.py --dry-run   # dữ liệu có qua được luật của Postgres không
.\.venv\Scripts\python.exe run_etl.py --offline         # dựng lại silver/gold từ cache bronze
```
Chạy lại luôn an toàn: mọi tải về được cache, task AppEEARS không gửi trùng, upload bỏ qua file không đổi. Đổi `bbox` hoặc khoảng năm sẽ gửi task AppEEARS mới (khoảng 30–90 phút, ước tính).
