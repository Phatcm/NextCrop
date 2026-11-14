# Vấn đề dữ liệu và bàn giao (14/11/2026)

Danh sách việc còn lại, viết để người tiếp theo (Phát) làm tiếp mà không cần hỏi lại. Chi tiết cuộc kiểm tra: [data-audit.md](data-audit.md). Mô hình dữ liệu: [data-contract.md](data-contract.md). Cấu hình Postgres: [postgres-hosting.md](postgres-hosting.md).

Bảng theo dõi (dễ nhìn hơn): Kan board `fieldshift` https://kan-amber.vercel.app/boards/1oixmltk2mz5 (riêng tư). File này vẫn là nguồn chính; khi cập nhật hãy sửa file này rồi đồng bộ lại lên board.

Quy ước: **[ĐÃ XÁC NHẬN]** = đã kiểm tra bằng dữ liệu hoặc API thật; **[CHƯA KIỂM CHỨNG]** = đề xuất, chưa thử.

## 1. Trạng thái hiện tại
**Đã xong và đã kiểm tra**
- ETL 7 nguồn: POWER (điểm + lưới cả nước), AppEEARS (MOD13Q1 NDVI+QA, SMAP L3, MCD12Q1, NASADEM), GFSAD30SEACE, FAO GAEZ v5 (24 cây × 4 mức), GIBS (dự phòng). 6 vùng, 2015–2025.
- R2 `field-shift-nasa`, lần chạy `20261114T030142Z`: 633 object, sha256 khớp manifest, `--verify` 0 lỗi, chạy lại không đẩy trùng.
- Migration Postgres `001_init.sql` + `load_postgres.py`; `--dry-run` qua sạch 402.709 dòng; CI xanh (60 test, test Postgres 17 thật qua).

- **Nạp Postgres thật (OPS-01): đã xong.** Neon (PostgreSQL 18.7): 402.709 dòng, 19/19 kiểm tra qua (lần đầu); **14/11 lần nạp thứ hai: 625.429 dòng, 23/23 kiểm tra qua, run `20261114T041950Z`, migration 002 đã áp**, chạy lại lần hai vẫn qua; app đọc được qua cả chuỗi pooled và direct. **14/11 lần nạp thứ ba (bảng cây trồng, DATA-01): R2 run `20261114T071439Z` (736 đối tượng, 0 lỗi), Neon 625.429 dòng, 25/25 kiểm tra qua, migration `003` đã áp** (migration `004` của DATA-06/07 chưa nạp).

**Chưa xong**: phần còn lại của DATA-01 (độ dài vụ thực tế ở Việt Nam, ý nghĩa `min_temp_c`, nhu cầu nước; giá, độ phủ đất và họ thực vật đã có ở bảng `crop_profile`, xem DATA-01), và các vấn đề độ chính xác bên dưới.

**Vị trí**
- Mã: repo `Phatcm/field-shift`; PR #1, #2 (DATA-04/05) và #4 (DATA-01 phần bảng, migration `003`) đã vào `main`.
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
| DATA-01 | ~~Nghiêm trọng~~ Đã xử lý phần bảng (còn giá, độ phủ đất, nguồn khuyến nông) | Bảng cây trồng 24 cây đã vào `dim_crop` (PR #4) và đã nạp R2/Neon (14/11) | Hùng + Phát |
| DATA-02 | ~~Cao~~ Đã xử lý phần sinh phương án (còn nối vào app) | Bộ sinh 4 phương án mức vụ đã có và có test; app chưa gọi nó | Phát |
| DATA-03 | ~~Cao~~ Đã xử lý phần dữ liệu cho 6 vùng (còn thiếu thấm nước, kết cấu đất, Kc, chi phí) | Độ dốc, ET0 và cân bằng nước, đất, nhu cầu tưới theo cây, xói mòn tương đối | Hùng + Phát |
| DATA-04 | ~~Trung bình~~ Đã xử lý phần GAEZ | Chỉ 6 vùng có đủ dữ liệu (GAEZ đã có cả nước, xem mục 3) | Cả hai |
| DATA-05 | ~~Cao~~ Đã xử lý (còn 3 ngày dưới ngưỡng và lưới) | Mưa phi lý (691 mm/ngày) lan sang bảng tháng, năm, chuẩn khí hậu | Phát |
| DATA-06 | ~~Cao~~ Đã xử lý (PR #6, đã nạp R2/Neon) | Mưa POWER lệch tới 2,3 lần (Ninh Thuận) | Phát |
| DATA-07 | ~~Trung bình~~ Đã xử lý (PR #6, đã nạp R2/Neon) | Mưa 2015 Đắk Lắk sai (POWER 423 mm, CHIRPS 1.653) | Phát |
| DATA-08 | Trung bình | SMAP chất lượng khuyến nghị 0% ở 4/6 vùng | Phát |
| DATA-09 | Trung bình | NDVI nội suy nhiều ở đồng bằng | Phát |
| DATA-10 | Trung bình | MODIS và GFSAD mâu thuẫn ở Sơn La, Đắk Lắk | Cả hai |
| DATA-11 | Thấp | GAEZ là tiềm năng, không đơn điệu | Hùng (giao diện) |
| DATA-12 | Thấp | Độ phủ thời gian: không có 2026, mốc NDVI trước 2015 | Phát |
| DATA-13 | Thấp | Đơn vị và ngày tạo chưa có trong Postgres | Phát |
| DATA-14 | Trung bình | Điểm ngoài Việt Nam (Lào, Campuchia, Trung Quốc) vẫn nhận phương án | Hùng (app) + Phát |
| OPS-01..10 | xem mục 4 | | |

## 3. Vấn đề dữ liệu

### DATA-01 · ĐÃ XỬ LÝ phần bảng (14/11/2026, PR #4) và phần 2 (14/11, bảng `crop_profile`, migration 007) · Thiếu bảng cây trồng
- **Phần 2 (làm tiếp thay Phát, bảng mới, không sửa `dim_crop` / `crop_traits.csv`):** `crop_profile` (24 cây) gồm: (1) **họ thực vật có nguồn**: GBIF Backbone Taxonomy (khóa `gbif_usage_key`), cả 24 họ khớp cột `family` của Phát; (2) **giá và năng suất Việt Nam** từ FAOSTAT (giá người sản xuất USD/tấn, năng suất kg/ha, trung bình quốc gia 2020–2024, chỉ lấy năm có đủ cả hai), `gross_revenue_usd_ha` = giá x năng suất = **doanh thu thô trên 1 ha cho 1 vụ (cây hằng năm) hoặc 1 năm (cây lâu năm), KHÔNG phải lợi nhuận** (không có chi phí); (3) **lớp chống xói mòn** `erosion_protection` (cao/trung bình/thấp) kèm `cover_basis` và `cover_confidence`.
  - **20/24 cây có giá và doanh thu.** Thiếu có chủ đích (để NULL, không đoán): taro, cọ dầu, cà chua (FAOSTAT không có mục cho Việt Nam), dừa (giá USD chỉ có năm 2015, chuỗi nội tệ đứt năm 2017). Đậu đũa dùng đậu khô, cam quýt dùng cam, lúa cạn dùng lúa nước (`faostat_match = proxy`).
  - **Giới hạn cần nói khi trình bày:** giá và năng suất là **trung bình quốc gia**, không phải theo tỉnh; năng suất lúa quốc gia chủ yếu là lúa nước nên lạc quan với lúa cạn. Lớp chống xói mòn: **chỉ 7/24 dòng có căn cứ đọc được qua bản tóm tắt tìm kiếm** (`documented_secondary`, bài gốc chưa đọc: JICA Indonesia C lúa tưới 0,010 và ngô 0,245; một nghiên cứu Lampung cho cà phê C 0,004–0,045; một tổng quan FAO về sắn cho cây lâu năm C 0,1–0,3), 17/24 dòng là **giả định của dự án** (`assumed`). FAO-56 và trang FAO bị chặn bot nên chưa lấy được hệ số Kc.
  - **Vẫn chưa làm:** số ngày sinh trưởng thực tế ở Việt Nam (USDA crop calendar trả 503, FAO GIEWS bị chặn), ý nghĩa của `min_temp_c`, và cột nhu cầu nước (sẽ lấy từ GAEZ `RES05-WDC` trong DATA-03).
- **Đã làm (PR #4, CI xanh gồm Postgres 17 thật):** `pipeline/crop_traits.csv` cho 24 cây, migration `003_crop_traits.sql`, cột: mã `RES02`, nhóm GAEZ, một năm/lâu năm, họ đậu, họ thực vật, độ dài vụ ứng viên (min/max), nhiệt tối thiểu, nguồn từng nhóm cột. Cây không có dòng trong bảng GAEZ (taro, vừng, điều, dưa hấu) để trống cột sinh trưởng, không đoán. Bộ đọc từ chối dòng sai số cột.
- **Đã nạp (14/11):** R2 run `20261114T071439Z`, Neon migration `003`, 25/25 kiểm tra qua, đọc lại 24 cây khớp `crop_traits.csv`.
- **Chưa làm:** giá thị trường; độ phủ đất chống xói mòn; số ngày sinh trưởng thực tế ở Việt Nam; đối chiếu họ thực vật với nguồn trích dẫn; ý nghĩa chính xác của `min_temp_c` (Appendix 4-5).
- **Vấn đề (trước PR #4):** hợp đồng dữ liệu mục 2.2 yêu cầu bảng cây trồng; `dim_crop` chỉ có `crop_code`, `name_vi`, `name_verified` cho 24 cây.
- **Bằng chứng:** `python audit_r2.py`, mục I, dòng "crop-table fields ... still missing".
- **Cột cần có:** họ thực vật (cần cho chu kỳ sâu bệnh, ngoài hợp đồng gốc), mùa trồng, thời gian sinh trưởng (ngày), nhiệt độ thích hợp min/max, ngưỡng rét, ngưỡng nóng, nhu cầu nước (mm), họ đậu (cố định đạm), độ phủ đất/chống xói mòn, giá thị trường, **nguồn của từng cột**.
- **Hướng xử lý:** điền cho 24 cây (hoặc rút gọn còn nhóm cây dùng để luân canh: lúa, ngô, đậu tương, lạc, khoai lang, sắn, mía... khoảng 10–12 cây). Kỹ thuật: thêm cột vào `silver/dim_crop` và migration `003_*.sql` (`002` đã dùng cho `gaez_grid`; `ALTER TABLE dim_crop ADD COLUMN ...`), cập nhật `loader` và test. File `pipeline/data/crops_template.csv` cũ chỉ có trên máy local (thư mục `data/` không commit) và đang trống, không dùng được. FAO EcoCrop có thể là nguồn tham số; **[CHƯA KIỂM CHỨNG]** độ phủ cây và giấy phép.
- **GAEZ chỉ giúp được một phần (kiểm tra 14/11):** cùng bucket có nhóm Growth Cycle `RES02-CBD` (ngày bắt đầu vụ), `RES02-CYL` (độ dài vụ), `RES02-WDE` (thiếu nước), `RES02-ETA` (thoát hơi nước thực tế); kỳ `HP0120.AGERA5.HIST`, đủ 4 mức đầu vào. **Mã cây khác RES05** (lúa nước `RICW`, ngô `MAIZ`, sắn `CASV`, đậu tương `SOYB`, lạc `GRND`, mía `SUGC`...). **[ĐÃ XÁC NHẬN] cả 24 cây đều có mã RES02**, ghép theo bảng `DIMENSION/GAEZ-V5.CROP-RES02.csv` và `CROP-RES05.csv` trong bucket (cột `caption`): `RCW→RICW, RCD→RICD, MZE→MAIZ, CSV→CASV, SPO→SPOT, WPO→WPOT, TAROW→TAROWL, SOY→SOYB, GRD→GRND, COW→COWP, SES→SESA, ONI→ONIO, COF→COFF, RUB→PRUB, TEA→TEAS, CSH→CASH, CON→COCN, OLP→OILP, SUC→SUGC, BAN→BANA, CIT→CITR, CAB→CABB, TOM→TOMA, WMEL→WMEL`. Lưu ý: **`COCO` là ca cao, không phải dừa** (dừa là `COCN`); `COFF` là "tốt nhất của arabica và robusta" (có thêm `COFA`, `COFR`); `TEAS` là "tốt nhất của các giống chè". **[CHƯA KIỂM CHỨNG]** `COF`/`TEA` của RES05 có cùng định nghĩa "tốt nhất" với `COFF`/`TEAS` không. Lưới gốc 5 phút cung (~0,0833°), không chia nguyên 0,1°.
  - **[ĐÃ XÁC NHẬN] `CYL` ít thay đổi theo vùng** (lúa 150 ngày ở Thái Bình, Đắk Lắk, An Giang; ngô 135, riêng Thái Bình 180; đậu tương 135). **Đính chính (đọc wiki GAEZ, Appendix 4-6):** đây không phải một hằng số của cây mà là độ dài vụ của giống **được mô hình chọn** trong các độ dài ứng viên (lúa indica 105/120/135/150 ngày, ngô nhiệt đới đất thấp 90–135, đậu tương nhiệt đới 105/120/135, lạc 90/105/120, đậu đũa 80/100/120), lấy giống cho năng suất tiềm năng cao nhất, nên thường rơi vào độ dài dài nhất. Vì thế 150 ngày của lúa là "tối ưu năng suất", không phải thực tế gieo trồng ở Việt Nam; giống ngắn ngày 105–120 ngày nằm trong chính tập ứng viên của GAEZ. Không nên làm lớp theo ô; dùng bảng tham số của Appendix 4-6 (khoảng độ dài ứng viên) làm cột `cycle_days_min/max`.
  - **Nguồn chính thức cho nhiều cột của DATA-01 (wiki `un-fao/gaezv5`, đã kiểm tra 14/11):** `Appendix 4-6 Biomass and yield parameters.xlsx`, bảng A4-6.1 có cột `Legume (1=yes, 0=no)` (đậu tương, lạc, đậu đũa = 1), `Annual/perennial` (1 = một năm, 2 = lâu năm: sắn 270 ngày, mía, chuối, dầu cọ, cam quýt, cà phê, dừa, chè, cao su = 2), `Reference growth cycle length`, `Minimum temperature` (°C), `Harvest index`. `Appendix 4-1 List of Crops.xlsx` có `GAEZ crop group` (Cereals, Roots and tubers, Oil crops, Pulses, Vegetables, Fruits, Sugar crops, Narcotics and stimulants, Industrial crops). Đây là nhóm cây của GAEZ, **không phải họ thực vật**: cà chua và khoai tây cùng họ Cà nhưng khác nhóm, nên họ thực vật vẫn phải điền tay. Không tìm thấy dòng cho taro, vừng, điều, dưa hấu trong bảng A4-6.1 khi tìm theo tên **[CHƯA KIỂM CHỨNG]** (có thể dưới tên khác).
  - `CBD` là ngày trong năm (vòng tròn): không lấy trung bình, lấy ô gần nhất; có nhiễu giữa ô kề nhau (lúa nước trời An Giang 169 so với 237 ở một ô lân cận). Dùng làm **nhãn mùa gieo gợi ý**, không làm lịch cố định. Ý nghĩa giá trị 0/1 chưa rõ.
  - Vẫn phải điền tay (có nguồn từng cột): họ thực vật, họ đậu, độ phủ đất, giá.
- **Xong khi:** mọi cây trong danh sách chốt có đủ cột và nguồn; `python load_postgres.py --dry-run` qua.

### DATA-02 · ĐÃ XỬ LÝ phần sinh phương án (14/11/2026) · Không có cây/luân canh hiện tại, không có định nghĩa phương án
- **Đã làm:** `pipeline/src/rotation/options.py` (thư viện thuần Python), lệnh thử `pipeline/rotation_options.py`, quy tắc ghi ở `docs/rotation-rules.md`, cột `water_regime` (migration `005`). Người dùng chọn cây hiện tại; bộ sinh trả **4 mẫu thay đổi nhỏ** (giữ nguyên, thay 1 vụ bằng cây họ đậu, thay 1 vụ bằng cây khác họ, đổi nhiều vụ mỗi vụ một họ), mỗi mẫu hiện từng thành phần (điểm GAEZ trung bình, cặp vụ cùng họ, họ đậu, số ngày) chứ **không có điểm tổng**, kèm lợi ích, rủi ro, bằng chứng và phần còn thiếu. Ưu tiên người dùng chọn quyết định thứ tự; ưu tiên chưa có dữ liệu (nước, xói mòn, thu nhập, đất) được khai báo là chưa hỗ trợ, không lờ đi. Ba tham số người dùng chỉnh được và luôn được ghi lại kèm nguồn: khoảng nghỉ giữa hai vụ lúa nước (mặc định 7 ngày, có nguồn nhưng chỉ từ một nông hộ), khoảng nghỉ các cặp khác (mặc định 15 ngày, **giả định chưa có nguồn**; chưa tìm được nguồn cho cây màu sau lúa dù đã tìm tiếng Việt, tiếng Anh và kho văn bản mở), chỉ số GAEZ tối thiểu (mặc định 4000, ranh giới lớp "phù hợp trung bình" của FAO).
- **Kiểm thử rộng 14/11 (12 cây một năm × 6 vùng demo × 2 mức đầu vào = 144 trường hợp, dữ liệu thật):** không vi phạm tính chất nào (phương án đầu là giữ nguyên, giữ cây chủ lực, vừa năm, không đặt cây ngập vào ruộng cạn, cây thay thế từ ngưỡng trở lên). Kết quả Neon và silver giống nhau từng byte. **118/120 trường hợp ngoài Sơn La có ≥ 3 phương án.** Hai ngoại lệ: Sóc Trăng với cây hiện tại là đậu tương chỉ có 2 phương án (mẫu họ đậu không áp dụng, mẫu đổi nhiều vụ không có tổ hợp), mức độ nhẹ.
- **[Cập nhật sau khi đổi sang `SUX`, 14/11] Sơn La:** ngô 1.728 ở ô 21,125°N 104,0417°E và 2.485 ở ô kề (cách ~9 km), vẫn dưới 4000, nên vẫn không đủ 3 phương án (1 và 2 phương án); số trường hợp dưới 3 phương án trong kiểm thử 6 vùng giảm từ 26 xuống 8. Đoạn ngay dưới mô tả lớp cũ (cả ô).
- **Sơn La không có phương án nào ngoài giữ nguyên ở ngưỡng mặc định (với lớp cũ):** cả 12 cây một năm đều dưới 1.000 ở ô trung tâm (ngô 452), số liệu cấp vùng cũ cho cùng hướng (ngô trung bình 750, trung vị 472, pixel cao nhất 3.291). Không phải lỗi lưới. Có thể GAEZ phạt nặng độ dốc và độ cao (533–868 m), trong khi thực tế vẫn trồng ngô nương: hạn chế của dữ liệu, không phải kết luận về nông nghiệp. **Quyết định 14/11:** cho người dùng hạ ngưỡng (`min_index`), giao diện hiện bảng lớp FAO (`index_classes`), kết quả có `floor_hint` và cảnh báo từng cây dưới 4000. **Không nên dùng Sơn La làm vùng demo chính**; dùng nó để minh họa giới hạn của công cụ.
- **Bằng chứng ít hơn ngoài 6 vùng:** phương án chỉ cần `gaez_grid` và `dim_crop` (phủ cả nước); NDVI, SMAP, lớp phủ đất và mưa hiệu chỉnh CHIRPS chỉ có ở 6 vùng, mưa ngoài 6 vùng là POWER chưa hiệu chỉnh. Chưa kiểm thử trên cả 9.280 ô.
- **Chưa làm:** nối vào app (chưa quyết định tính theo yêu cầu hay tính sẵn vào bảng/JSON); thứ tự các vụ (chưa xếp lịch, xem lý do ở dưới). **Đã nạp 14/11:** R2 run `20261114T081629Z`, Neon 626.287 dòng, 31/31 kiểm tra qua, migration `005` đã áp.
- **Vấn đề:** đề yêu cầu so sánh ≥3 phương án luân canh gồm phương án hiện tại; dữ liệu không có "cây hiện tại" của vùng và không có định nghĩa phương án (chuỗi cây theo mùa).
- **Hướng xử lý:** quyết định ai định nghĩa. Cách đơn giản: người dùng chọn cây hiện tại trong app, Hùng định nghĩa các mẫu luân canh (bảng `rotation_option`) hoặc quy tắc sinh phương án từ bảng cây trồng (DATA-01, phụ thuộc).
- **Quyết định 14/11: chấm điểm bằng luật mức vụ, không cộng ngày.** Thử trên dữ liệu thật An Giang: cộng "ngày bắt đầu + độ dài vụ" báo "vừa một năm" nhưng lịch tối ưu của từng cây xung đột (có tưới: lúa ngày 10–160, đậu tương bắt đầu ngày 320 kéo sang ngày 90 năm sau, đè lên lúa; nước trời: lúa kết thúc ngày 318, đậu tương tối ưu từ ngày 261). Lúa 3 vụ không biểu diễn được với 150 ngày/vụ của `CYL` (3 x 150 = 450); nhưng tập giống ứng viên của GAEZ có cả 105 ngày (3 x 105 = 315), nên dùng độ dài ứng viên ngắn nhất làm giả định cho vùng lúa nhiều vụ, ghi rõ trong app. Luật dùng: khác họ liên tiếp, có cây họ đậu trong chuỗi, điểm phù hợp GAEZ (`gaez_grid`), nhu cầu nước không xung đột, nhãn mùa gieo từ `CBD`. Cây lâu năm (cà phê, cao su, chè, điều, dừa) không luân canh theo vụ: loại ra hoặc xử lý riêng.
- **Phải ghi trong app:** xếp hạng tương đối dựa trên lịch mô phỏng GAEZ, các vụ nối tiếp là giả định, chưa tính thời gian chuyển vụ; không phải lịch nông dân và không dự báo từng ruộng.
- **Cải thiện sau (không chặn):** số ngày sinh trưởng thực tế ở Việt Nam từ tài liệu khuyến nông; lịch thời vụ chính thức theo vùng để đối chiếu `CBD`; giá nông sản; độ phủ đất chống xói mòn.
- **Xong khi:** mỗi cây hiện tại có ≥3 phương án (gồm giữ nguyên) hoặc có quy tắc sinh ra chúng.

### DATA-03 · ĐÃ XỬ LÝ phần dữ liệu (14/11/2026, migration 009) · Thiếu đầu vào cho 5 ưu tiên (nước, đất, đạm, xói mòn, thu nhập)
- **Đã làm (6 vùng, bảng mới, không đụng bảng của Phát):** mọi đầu vào lấy từ bucket GAEZ v5 (cùng bộ đọc cửa sổ HTTP) và từ dữ liệu đã có, không cần nguồn mới:
  - **Nước:** `water_balance_monthly` = mưa CHIRPS − ET0, tính theo FAO-56 Penman-Monteith từ chính cột POWER (nhiệt độ, độ ẩm, gió, bức xạ). Kiểm chứng với lớp ET0 độc lập của GAEZ: Thái Bình −1%, Sóc Trăng +4%, An Giang +7% nhưng Sơn La −18%, Ninh Thuận −16%, Đắk Lắk −26% (POWER lệch ở vùng núi và khô). Vì vậy `et0_mm` được nhân hệ số từng vùng (0,93–1,35) để trung bình 11 năm khớp GAEZ, giữ nguyên hình dạng theo tháng của POWER; `et0_raw_mm` giữ số gốc. Cân bằng năm: Ninh Thuận −830 mm (thiếu nước), Thái Bình +685. `crop_water_demand`: lượng tưới ròng trong vụ (mm) theo 24 cây và 2 mức có tưới, từ GAEZ `RES05-WDC` (0 = không thiếu nước trong mô hình, NULL = không có dữ liệu; **là nhu cầu tưới, không phải tổng nước cây dùng**).
  - **Xói mòn:** `terrain_slope` (10 lớp độ dốc GAEZ `LR-SLC`): Sơn La dốc trung bình 34,6% (81% diện tích dốc >12%), Đắk Lắk 8,4%, ba vùng đồng bằng 3–4%. `erosion_context`: chỉ số Fournier hiệu chỉnh từ mưa CHIRPS và mức nguy cơ nền (thấp/vừa/cao). Đây là **mức tương đối, không phải tấn/ha**; thiếu hệ số xói của đất và hệ số phủ cây (app nhân với `crop_profile.erosion_protection`). Chỉ số Fournier ở cả 6 vùng đều ≥142 nên các lớp theo ngưỡng bão hòa và **độ dốc quyết định kết quả**; ngưỡng là quy tắc dự án chưa hiệu chỉnh cho Việt Nam, nguồn ngưỡng Fournier **[CHƯA KIỂM CHỨNG]**.
  - **Đất:** `soil_quality` (GAEZ `SQX`, 8 yếu tố x 2 mức đầu vào, điểm 0–1): ví dụ Sóc Trăng độ phì 0,06 và nhiễm mặn 0,26 (đúng với bối cảnh lúa-tôm), Sơn La yếu tố hạn chế nhất 0,27. Độ phân giải ~1 km, nền HWSD.
  - **Đạm:** không có dữ liệu mới; dùng `dim_crop.is_legume` (DATA-01) và `soil_quality` SQ1 (độ phì).
  - **Thu nhập:** `crop_profile.gross_revenue_usd_ha` (DATA-01 phần 2), doanh thu thô, không phải lợi nhuận.
- **Vẫn thiếu, ghi rõ trong gold `environment.note`:** thấm nước (không có dữ liệu trực tiếp; SMAP L4 `soil_water_infiltration_flux` là thông lượng của mô hình, không phải khả năng thấm, nên không dùng), kết cấu đất và hữu cơ (GAEZ chỉ cho chỉ số chất lượng), hệ số cây trồng Kc (FAO-56 bị chặn truy cập tự động), đạm thực đo, chi phí sản xuất.
- **Giới hạn:** raster ~1–10 km mô tả vùng quanh điểm, không phải một thửa; chưa có cho lưới cả nước (mới 6 vùng).

**Ghi chú cũ (trước khi làm):**
- **Độ dốc / xói mòn:** `terrain` chỉ có độ cao tại 25 điểm/vùng (trung vị, min, max), không đủ tính độ dốc. Cần DEM dạng lưới; **[CHƯA KIỂM CHỨNG]** cách lấy (NASADEM theo vùng).
- **Bốc thoát hơi nước / cân bằng nước:** POWER **không có `PET`** (gọi trả lỗi 422 **[ĐÃ XÁC NHẬN]**). Có `EVPTRNS` (năng lượng bốc thoát hơi nước) và `EVLAND` **[ĐÃ XÁC NHẬN]**; đơn vị chưa kiểm tra. Hai hướng: thêm hai biến này vào `power.parameters` trong `config.yaml` (nhớ đổi đơn vị), hoặc tính PET kiểu Hargreaves từ `t2m_max`, `t2m_min`, bức xạ rồi cân bằng nước = mưa − PET theo tháng.
- **Thấm nước:** SMAP L4 `SPL4SMGP.008` có lớp `Geophysical_Data_soil_water_infiltration_flux` trong AppEEARS **[ĐÃ XÁC NHẬN]**; chưa lấy dữ liệu thử. Đây là sản phẩm đồng hóa mô hình, không phải đo vệ tinh thuần.
- **Đất (kết cấu, hữu cơ):** chưa có nguồn nào. ISRIC SoilGrids là ứng viên (không phải NASA) **[CHƯA KIỂM CHỨNG]**. Đề bài cho phép ghi "chỗ còn thiếu thông tin", nên có thể khai báo thiếu trong app thay vì tìm cho bằng được.
- **Đạm, thu nhập:** phụ thuộc DATA-01.

### DATA-04 · ĐÃ XỬ LÝ phần GAEZ (14/11/2026) · Chỉ 6 vùng có đủ dữ liệu
- **Sự cố 14/11 và cách chặn:** lần nạp 07:19 UTC (run `20261114T071843Z`, từ máy không có silver `gaez_grid`) làm `gaez_grid` về 0 dòng trên R2 và Neon mà không có kiểm tra nào báo, vì kiểm tra cũ chỉ chạy khi bảng có dòng. Đã khôi phục lúc 08:16 UTC (run `20261114T081629Z`, 222.720 dòng). Từ nay `upload_r2.py` và `load_postgres.py` từ chối khi một bảng có dữ liệu ở lần trước mà lần này không có dòng nào, và `load_postgres.py` bắt `gaez_grid` không rỗng khi cấu hình có bật (cho phép có chủ ý bằng `--allow-empty TABLE`). Trước khi nạp từ máy khác: `pull_bronze.py` rồi `run_etl.py --offline`.
- **Đã làm:** `gaez_grid` (silver + bảng Postgres, migration `002`): GAEZ v5 cho **cả Việt Nam** (102–110°E, 8–24°N), lớp **đất canh tác** `RES05-SUX` trên lưới gốc 5 phút cung (~9 km, không gộp ô; **đổi từ lớp "cả ô" ngày 14/11**, xem ngay dưới), 12.813 ô × 24 cây × 4 mức đầu vào = 307.270 dòng, dạng rộng `hilm, hrlm, lilm, lrlm`. Mọi điểm người dùng chọn đều tra được ô gần nhất. Cấu hình `gaez_grid` trong `config.yaml`; mã `src/extractors/gaez_grid.py`.
- **Đã nạp 14/11 (09:16 UTC), PR #11:** R2 run `20261114T091512Z` (946 đối tượng, 0 lỗi), Neon migration `006`, `gaez_grid` **307.270 dòng, 12.813 ô, 24 cây** (lớp `SUX`, tâm ô `20,4583 / 106,2917` kiểm tra thật), 710.837 dòng tổng. Bộ sinh phương án đọc từ Neon cho kết quả giống đọc từ silver (Thái Bình, lúa nước 9.022, 4 phương án). Bảng 6 vùng `gaez_suitability` **vẫn là lớp cũ** (n_px 144) cho đến khi PR #13 (migration `008`) được nạp.
- **Đổi lớp 14/11 (đã bàn với Hùng):** bản đầu dùng trung bình **cả ô** (`RES05-SXX30AS` gộp về 0,1°), gồm cả rừng và đất dốc nên kéo thấp các ô đồi núi. Kiểm thử cả nước: với lớp cũ 54,9% số ô không có cây một năm nào đạt 4000; với lớp đất canh tác `RES05-SUX` chỉ còn 9,3%. Ở đồng bằng phẳng hai lớp gần như giống nhau (An Giang lúa nước 7.828–8.817 so với 8.128–9.202); ở vùng đồi núi khác nhiều (Sơn La ngô 282–1.185 so với 1.728–2.485, lúa nước 411–2.207 so với 4.051–4.486). Theo wiki GAEZ, lớp đất canh tác giả định nông dân dùng phần tốt nhất của ô theo tỉ lệ đất đang trồng trọt. Không để người dùng chọn giữa hai thước đo. **Lưu ý:** `SUX` lạc quan, `SXX` bi quan, thực tế nằm giữa; `SUX` có thể chạm trần 10.000 nên các cây hòa nhau ở đỉnh. **Lưới đổi từ 0,1° sang 5 phút cung**: tâm ô `lat = 24 − (i + 0,5)/12`, `lon = 102 + (j + 0,5)/12`, làm tròn 4 chữ số (ví dụ 20,4583 và 106,2917); migration `006`, app tra theo ô mới. **Bảng 6 vùng `gaez_suitability` (và view `v_crop_ranking`) đổi sang `SUX` cùng lúc** (`gaez.layer` trong `config.yaml`, migration `008`), nên hai bảng dùng cùng thước đo. Mỗi vùng bbox 0,1° chỉ phủ 2–3 ô mỗi chiều nên `n_px` là 4 thay vì 144. Xếp hạng nước trời + đầu vào cao đổi rõ ở Đắk Lắk (sắn 5.433 lên 7.308, ngô từ hạng 5 lên hạng 3), Sơn La (lúa nước 1.363 lên 4.274), Thái Bình (lúa nước 7.645 lên 9.031), Sóc Trăng (lúa nước từ hạng 4 lên hạng 2); An Giang gần như không đổi (lúa nước 8.460 lên 8.504).
- **[ĐÃ XÁC NHẬN] (lớp cũ SXX30AS)** Giá trị ô khớp từng pixel với file đã cắt bằng rasterio (RCW/HRLM, cả cửa sổ 1.920 × 960 pixel). Bộ đọc GeoTIFF của Hùng và rasterio cho cùng kết quả ở cả 3 vùng thử (Thái Bình, Đắk Lắk, Sơn La; RCW/COF/MZE).
- **Chạy:** lớp `SUX` nhỏ (~1,6 MB/file): đọc 96 file từ xa mất ~105 giây với 8 luồng (lớp cũ ~45 phút). Kết quả lưu trong `data/bronze/gaez/grid_sux_5arcmin/`, chạy lại `--offline` không cần mạng; `--gaez-local-dir <thư mục>` dùng file tif `RES05-SUX` tải sẵn.
- **Giới hạn:** hình chữ nhật gồm cả Lào, Campuchia, Trung Quốc (12.813 ô có dữ liệu, chưa lọc theo biên giới, xem DATA-14); app chỉ tra điểm trong Việt Nam. Vẫn là tiềm năng GAEZ (DATA-11).
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
- **Cải thiện sau (đã hoãn, 14/11):** ERA5 chỉ là tái phân tích, chưa phải số đo. Để phân xử 3 ca ranh giới nên đối chiếu thêm nguồn độc lập: **GPM IMERG** (NASA, vệ tinh hiệu chỉnh bằng trạm, nằm trong danh sách nguồn của đề, cần Earthdata; **[CHƯA KIỂM CHỨNG]** cách truy cập) hoặc trạm **NOAA GHCN-Daily** gần 6 vùng (**[CHƯA KIỂM CHỨNG]** có trạm đủ gần và đủ 2015–2025 không). Chỉ cần kiểm khoảng 9 ngày bị loại và vài ngày bị giữ. Cũng nên dùng chuỗi ERA5 đã cache trong `bronze/era5` để làm DATA-06/07 (so tổng mưa năm của POWER với ERA5 cho 6 vùng), không cần tải thêm.
- **Chưa xử lý:** lưới khí hậu cả nước (`vn_grid_monthly`) là dữ liệu tháng nên không áp được quy tắc theo ngày; ô lưới chứa An Giang vẫn mang số tháng 6/2020 cao bất thường.

### DATA-06 · ĐÃ XỬ LÝ (14/11/2026, PR #6; đã nạp R2 và Neon) · Mưa POWER lệch tới 2,3 lần ở Ninh Thuận
- **Kiểm chứng (3 nguồn + trạm):** trung bình năm 2016–2025, POWER / ERA5 / CHIRPS v3: Ninh Thuận 2.031 / 1.507 / 896; Sơn La 1.705 / 1.345 / 1.370; Đắk Lắk 2.049 / 1.218 / 2.031; Thái Bình 1.989 / 1.778 / 1.917; An Giang 1.993 / 1.820 / 1.683; Sóc Trăng 2.055 / 1.987 / 2.119 (mm). Trạm NOAA GHCN-Daily: Sơn La (VMM00048806) 1.348 mm/năm (2016–2024) khớp CHIRPS, POWER cao hơn 26%; Phan Rang (VMW00041022) chỉ có 1966–67: 915 và 638 mm, cỡ ~780 mm, cho thấy Ninh Thuận khô thật. ERA5 không đủ làm trọng tài (cũng sai ở Ninh Thuận và Đắk Lắk 1.218 mm so với 2.0xx).
- **Cách xử lý:** thêm CHIRPS v3 (UCSB CHC, 0,05°, hiệu chỉnh bằng trạm, CC0) đọc theo cửa sổ HTTP (`src/extractors/chirps.py`); `src/transformers/rain_validation.py` so POWER với CHIRPS theo năm; bảng mới `rain_monthly_best` (mưa tháng app phải dùng: CHIRPS, POWER chỉ là dự phòng có đánh dấu) và `rain_validation` (migration 004); gold có `climate.rain_best` và caveat theo vùng. `power_*` giữ nguyên.
- **Kết quả phán quyết (lệch > 30%):** Ninh Thuận `power_biased` (+126%, cả 11 năm); Sơn La, An Giang `power_bad_years` (năm lệch: 2018/19/21; 2018–2022); Đắk Lắk `power_bad_years` (2015); Thái Bình, Sóc Trăng nhất quán.
- **Giới hạn:** CHIRPS là ước lượng vệ tinh + trạm ~5 km, không phải số đo trạm; Phan Rang chỉ có 2 năm trạm (thập niên 1960). Chưa dùng GPM IMERG (cần Earthdata, chưa kiểm chứng cách truy cập). Lưới cả nước `vn_grid_monthly` vẫn là POWER (chưa thay).
- **Đã nạp:** R2 run `20261114T071843Z` (657 object, 0 lỗi) và Neon (27/27 kiểm tra, gồm cả bảng cây trồng DATA-01). **Việc còn lại:** app đổi sang đọc `rain_monthly_best`.

### DATA-07 · ĐÃ XỬ LÝ (14/11/2026, PR #6; đã nạp R2 và Neon) · Năm 2015 khô cực đoan
- **Kết luận:** một phần là lỗi POWER. Đắk Lắk 2015: POWER 423 mm, ERA5 895, CHIRPS 1.653 (bằng 0,81 trung bình năm khác) nên 423 là sai, không phải El Niño. An Giang 2015: POWER 809, CHIRPS 1.083 (0,64 trung bình). Ninh Thuận 2015 khô thật (CHIRPS 516, 0,58 trung bình) nhưng POWER ghi 1.259. El Niño 2015–16 có thật ở An Giang và Ninh Thuận, và CHIRPS vẫn ghi nhận khô hơn bình thường.
- **Cách xử lý:** cùng DATA-06: `rain_validation` đánh dấu năm lệch > 30%, app dùng `rain_monthly_best`.

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

### DATA-14 · Trung bình · Điểm ngoài Việt Nam vẫn nhận phương án luân canh
- **Vấn đề:** `gaez_grid` là hình chữ nhật 102–110°E, 8–24°N nên có cả Lào, Campuchia và miền nam Trung Quốc. Bộ sinh phương án không biết ranh giới quốc gia: điểm ở Viêng Chăn (17,97°N 102,6°E) nhận kết quả đầy đủ như điểm ở Việt Nam. Điểm ngoài biển thì bị từ chối đúng (không có ô trong 0,1°).
- **[ĐÃ XÁC NHẬN] 14/11** bằng lệnh `rotation_options.py` với điểm ở Viêng Chăn. Dữ liệu GAEZ ở đó vẫn là GAEZ hợp lệ; vấn đề là phạm vi sản phẩm (đề và dữ liệu mưa hiệu chỉnh chỉ cho Việt Nam).
- **Hướng xử lý:** cần một lớp ranh giới Việt Nam (chưa có trong repo; ứng viên: ranh giới quốc gia của UN/GADM, **[CHƯA KIỂM CHỨNG]** giấy phép) để (a) giới hạn vùng chọn trên bản đồ, và/hoặc (b) thêm cột `in_vietnam` vào `gaez_grid` lúc ETL. App phải tự giới hạn cho đến khi có.
- **Xong khi:** điểm ngoài Việt Nam bị từ chối với thông báo rõ, có test.

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
- Mục "Công cụ AI đã dùng" trong ba README đã điền (Claude Code); khi nộp bài cần khai báo lại trong biểu mẫu và bổ sung nếu dùng cho mã app.
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
