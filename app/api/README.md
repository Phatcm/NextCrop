# app/api: backend chỉ đọc cho NextCrop

FastAPI đọc dữ liệu thật từ PostgreSQL (schema `field_shift`, do `pipeline/load_postgres.py` nạp) và gọi bộ sinh phương án luân canh `pipeline/src/rotation`. **Không ghi dữ liệu, không gọi API NASA/FAO.**

## Chạy
```powershell
cd app/api
pip install -r requirements.txt
$env:APP_DATABASE_URL = "postgresql://...?sslmode=require"      # role chỉ đọc nếu có; xem bên dưới
uvicorn fieldshift_api.main:app --port 8000
```
Tài liệu tương tác: http://localhost:8000/docs. Test: `python -m pytest` (test Postgres thật chạy khi có `TEST_DATABASE_URL`, test xóa và tạo lại schema `field_shift` nên chỉ dùng DB dùng một lần).

| Biến | Ý nghĩa |
|---|---|
| `APP_DATABASE_URL` | chuỗi kết nối, ưu tiên số 1 (nên là role chỉ đọc) |
| `DATABASE_URL_POOLED`, `DATABASE_URL` | dự phòng theo thứ tự này (chuỗi Neon pooled dùng được: bảng được gọi kèm tên schema) |
| `CORS_ORIGINS` | địa chỉ giao diện, cách nhau bằng dấu phẩy (mặc định các cổng dev `localhost:5173` và `:3000`) |
| `WEB_DIR` | thư mục giao diện tĩnh phục vụ ở `/` (mặc định `../web`, tức `app/web`; tắt nếu không có `index.html`) |
| `PIPELINE_DIR` | mặc định `../../pipeline` (API dùng chung `src.rotation` và `src.db.postgres` với pipeline) |

Bí mật chỉ nằm trong biến môi trường, không có trong repo.

## Endpoint
| | |
|---|---|
| `GET /api/health` | `{"status":"ok","database":true}` |
| `GET /api/crops` | 24 cây kèm `rotatable` (`false` với cây lâu năm hoặc thiếu độ dài vụ: không có phương án luân canh). `?lang=vi\|en` chọn ngôn ngữ của `name` (tên hiển thị); `name_vi` và `name_en` luôn có |
| `GET /api/options?lat&lon&crop` | phương án luân canh cho điểm và cây hiện tại. Tùy chọn: `mode` (`hilm`, `hrlm` mặc định, `lilm`, `lrlm`), `seasons` 1–3, `priorities` (lặp lại tham số; `nitrogen`, `pest_cycle`, `yield`), `min_index` 0–10000 (mặc định 4000), `gap_rice` và `gap_other` 0–60 ngày (mặc định 7 và 15), `lang` (`vi` mặc định hoặc `en`: ngôn ngữ của **mọi câu chữ** trong kết quả: tên phương án, lợi ích, rủi ro, giả định và nguồn, lớp độ phù hợp, tên cây) |
| `GET /api/cells?west&south&east&north&crop` | các ô lưới trong khung bản đồ với chỉ số của một cây (lớp tô màu); `mode`, `limit` (mặc định 6000, tối đa 20000) |
| `GET /api/nasa?lat&lon` | dữ liệu NASA quanh một điểm cho thẻ "NASA" của giao diện: nhiệt độ từng tháng (NASA POWER, ô 0,5° gần nhất trong 110 km; trung bình nhiều năm 2015–2025 của T2M, T2M_MIN, T2M_MAX, bỏ giá trị năm và giá trị -999) và, **chỉ khi một trong 6 vùng demo nằm trong 60 km**, mưa theo tháng (CHIRPS v3, không phải NASA) và NDVI theo tháng (NASA MODIS, chỉ các lần đo thật đã qua kiểm tra chất lượng; số nội suy không tính). Là khí hậu nhiều năm, không phải dự báo. Mỗi ô dữ liệu có một đáp án, được nhớ trong bộ nhớ |

`/api/options` trả kết quả của bộ sinh (xem `docs/rotation-rules.md`: `options` với phương án đầu luôn là `keep`, `assumptions` kèm nguồn và cờ `custom`, `index_classes`, `floor_hint`, `warnings`, `missing`, `unsupported_priorities`) cộng thêm:
- `location`: `lat`, `lon` người dùng chọn, `cell_lat`, `cell_lon` (tâm ô), `cell_bounds` `[tây, nam, đông, bắc]`, `cell_area_km2` (khoảng 80–85 km²);
- `cell_indices`: chỉ số của mọi cây trong ô đó (để giao diện hiện danh sách cây kèm mức phù hợp).

- `climate_check` (chỉ khi có phương án): kiểm tra độ ẩm của từng phương án cho 6 vùng demo, xem `docs/rotation-rules.md`. Là khóa riêng, **không ảnh hưởng `options`**. `applies: true` kèm `area`, `moist_season` (`months`, `days`), `monthly` (12 tháng: `rain_mm`, `et0_mm`, `ratio`, `moist`), `options` (theo `id` phương án: `status` = `enough`/`short`/`unknown`, `days_needed`, `days_available`, `shortfall_days`, `margin_days`, `near_limit`, `single_season_fits`, `message`), `not_checked`, `caveats`, `sources`. `applies: false` kèm `reason` (`irrigated_mode`, `no_demo_area`, `no_data`) và `message`.

Với cây lâu năm, kết quả có `message` và `options` rỗng (HTTP 200).

## Lỗi
Mọi lỗi có dạng `{"detail": {"code": ..., "message": ...}}`:

| Mã | HTTP | Khi nào |
|---|---|---|
| `outside_grid` | 422 | điểm ngoài khung 102–110°E, 8–24°N |
| `no_data` | 404 | ô không có dữ liệu GAEZ (biển, không có đất canh tác); với `/api/nasa`: không có ô NASA POWER trong 110 km |
| `unknown_crop`, `invalid_mode`, `invalid_lang`, `invalid_argument`, `invalid_bbox` | 422 | tham số sai (tham số ngoài khoảng cho phép trả 422 chuẩn của FastAPI) |
| `too_many_cells` | 413 | `/api/cells` có nhiều ô hơn `limit`: thu nhỏ bbox |
| `db_not_configured` | 503 | chưa đặt biến chuỗi kết nối |
| `db_unavailable` | 503 | không đọc được database (đang khởi động lại, mất mạng) |

## Thiết kế và giới hạn
- **Chỉ đọc có kiểm soát:** mọi yêu cầu chạy trong `BEGIN READ ONLY ... ROLLBACK`, nên không ghi được kể cả với role chủ (đã thử trên Neon bằng một câu `DELETE` không động tới dòng nào; test Postgres thật nằm trong `tests/test_repo_pg.py` và chạy ở CI, workflow `api-tests`). Vẫn nên dùng role chỉ đọc (`docs/postgres-hosting.md` mục 2, OPS-11).
- **Ô lưới, không phải ô gần nhất:** điểm được đổi thành ô chứa nó theo đúng quy ước của pipeline (`lat = 24 - (i + 0,5)/12`, `lon = 102 + (j + 0,5)/12`), rồi tra bằng khoảng 0,0002° quanh tâm ô.
- **Bộ nhớ đệm 5 phút** cho bảng cây và cho từng ô (tối đa 512 ô): kéo thanh trượt trong cùng một ô chỉ mất vài mili giây. Dữ liệu đổi khi pipeline nạp lại, tối đa 5 phút sau API mới thấy.
- **Một kết nối, có khóa:** đủ cho demo; chưa dùng pool. Khi tải lớn hơn cần pool hoặc nhiều worker, mỗi worker một kết nối.
- **DATA-14 vẫn mở:** điểm ở Lào, Campuchia hoặc miền nam Trung Quốc nằm trong khung vẫn nhận kết quả vì chưa có lớp ranh giới quốc gia. Giao diện phải tự giới hạn vùng chọn.
- **Dữ liệu theo ô khoảng 9 km** (DATA-16 cho hướng ô nhỏ hơn): chỉ số là mức trung bình của đất canh tác trong ô, không phải của một thửa.
- Thứ tự các vụ trong năm chưa được xếp lịch (`sequence` là danh sách tổ hợp cây).
- **Hai ngôn ngữ (vi, en):** câu chữ do bộ sinh viết nằm trong hai bảng `STRINGS["vi"]` và `STRINGS["en"]` của `pipeline/src/rotation/options.py` (cùng khoá, cùng chỗ điền, có test kiểm tra); tiếng Việt là mặc định và không đổi. Tên cây tiếng Anh nằm trong `pipeline/src/rotation/crop_names.py`, **chưa có trong database** (muốn đưa vào `dim_crop` cần migration và nạp lại). Lỗi (`detail.message`) vẫn bằng tiếng Việt; giao diện dịch theo `code`.
