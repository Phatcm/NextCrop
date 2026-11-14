# pipeline/

Pipeline lấy, xử lý và đóng gói dữ liệu cho app NextCrop (thư mục `app/`):

```
NASA / FAO  ->  bronze (dữ liệu gốc)  ->  silver (bảng phẳng, có khóa)  ->  gold (JSON)
                       \_______________ Cloudflare R2 (data lake) _______________/
                                              |
                                  load_postgres.py  ->  PostgreSQL (app đọc từ đây)
```

> **Quy định:** phần lõi sản phẩm phải làm trong thời gian thi (14–15/11/2026); khai báo công cụ AI khi nộp bài. Không commit dữ liệu thô lớn hoặc khóa/bí mật.

## Nguồn dữ liệu
| Nguồn | Dùng cho | Truy cập | Cách lấy |
|---|---|---|---|
| NASA POWER | khí hậu theo ngày/tháng (nhiệt độ, mưa, ẩm, nắng, độ ẩm đất mô hình) + lưới cả nước | API công khai | `power_client.py` |
| NASA MODIS MOD13Q1 (AppEEARS) | NDVI 250 m + `pixel_reliability` | Earthdata (tên + mật khẩu) | `appeears_client.py` |
| NASA SMAP SPL3SMP_E (AppEEARS) | độ ẩm đất đo bằng vệ tinh, 9 km | Earthdata | `appeears_client.py` |
| MODIS MCD12Q1, NASADEM (AppEEARS) | lớp phủ đất theo năm, độ cao | Earthdata | `appeears_client.py` |
| NASA GFSAD30SEACE | mặt nạ đất canh tác 30 m (2015), lọc điểm MODIS "thuần ruộng" | Earthdata (qua `urs.earthdata.nasa.gov`) | `gfsad.py` |
| FAO GAEZ v5 `RES05-SUX` (cấu hình `gaez.layer`) | mức thích hợp trên **đất canh tác** của 24 cây x 4 mức đầu vào (0–10000), 6 vùng demo (`gaez_suitability`) | bucket Google Cloud Storage công khai | `gaez.py` (đọc cửa sổ qua HTTP; lớp cũ `RES05-SXX30AS` trung bình cả ô là mặc định khi bỏ `layer`) |
| FAO GAEZ v5 `RES05-SUX` | như trên nhưng cho **cả nước** trên lưới gốc 5 phút cung ~9 km, không gộp ô | cùng bucket | `gaez_grid.py` (bảng `gaez_grid`) |
| NASA GIBS | NDVI ảnh màu 2023–2025, chỉ dự phòng/đối chiếu | công khai | `gibs_ndvi.py` |

Chi tiết lớp GAEZ, mã cây và cách đối chiếu: [../docs/gaez-notes.md](../docs/gaez-notes.md). Mô hình dữ liệu: [../docs/data-contract.md](../docs/data-contract.md).

## Cấu trúc
```
config.yaml        vùng, năm, nguồn, danh sách cây GAEZ, quy tắc QA
run_etl.py         lấy dữ liệu -> bronze/silver/gold (data/)
upload_r2.py       đẩy data/ lên R2 theo chuẩn data lake + manifest + catalog
load_postgres.py   kéo silver từ R2, nạp PostgreSQL trong một transaction
db/migrations/     schema PostgreSQL (001_init.sql)
src/               extractors/ (nguồn), transformers/ (QA, nội suy, gold), lake/ (R2), db/ (Postgres)
tests/             pytest (không cần mạng; test Postgres chạy khi có TEST_DATABASE_URL)
data/              dữ liệu sinh ra (KHÔNG commit)
```

## Cài đặt (Windows / PowerShell)
```powershell
cd pipeline
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env        # rồi điền giá trị thật
.\.venv\Scripts\python.exe -m pytest
```
Không cần `rasterio`/GDAL/`libpq`: GeoTIFF được đọc bằng `tifffile` + bộ giải nén trong `src/geotiff.py`, PostgreSQL qua `pg8000` (thuần Python).

## Chạy
```powershell
python run_etl.py                       # tất cả nguồn (AppEEARS có thể chờ tới 90 phút lần đầu)
python run_etl.py --no-wait             # chỉ gửi task AppEEARS, chạy lại sau để tải về
python run_etl.py --offline             # dựng lại silver/gold từ cache bronze
python run_etl.py --regions an_giang_rice --skip-gibs --skip-grid
python run_etl.py --gaez-local-dir D:\path	o\gaez_tifs   # lưới GAEZ cả nước từ file tif đã tải (~vài giây thay vì ~45 phút)
python run_etl.py --skip-gaez-grid                          # bỏ qua lưới GAEZ cả nước
python upload_r2.py --dry-run           # xem sẽ đẩy gì
python upload_r2.py --init --prune      # đẩy lên R2 (lần đầu có --init; --prune dọn object cũ)
python upload_r2.py --verify            # đối chiếu bucket với manifest
python upload_r2.py --allow-empty BẢNG  # cho phép một bảng rỗng có chủ ý (mặc định chặn khi bảng có dữ liệu ở lần trước mà lần này về 0)
python audit_r2.py                      # kiểm tra dữ liệu trên R2 so với yêu cầu dự án (xem ../docs/data-audit.md)
python load_postgres.py --dry-run       # không cần server: dữ liệu có qua được PK/FK/CHECK/kiểu của Postgres không
python load_postgres.py --check-server  # server đích đã đủ điều kiện chưa (phiên bản, UTF8, quyền, TLS)
python load_postgres.py                 # R2 -> PostgreSQL (DATABASE_URL trong .env)
```
Chạy lại lúc nào cũng an toàn: mọi tải về được cache trong `data/bronze/`, task AppEEARS ghi trong `tasks.json` nên không bao giờ gửi trùng, upload bỏ qua file không đổi.

## Cloudflare R2 (data lake)
Khóa đặt trong `.env` (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`), **không** commit; trong CI dùng GitHub Secrets.
```
bronze/<nguồn>/...                               dữ liệu gốc, giữ nguyên như tải về (không sửa)
silver/<bảng>/region_id=<vùng>/<bảng>.csv        bảng phẳng, có cột region_id và khóa tự nhiên
gold/v<schema>/<tên>.json                        JSON đánh phiên bản theo schema
_meta/manifests/run_id=<UTC>.json                nhật ký bất biến mỗi lần đẩy: size, sha256
_meta/catalog.json                               từ điển dữ liệu: cột, kiểu, khóa, số dòng
_meta/latest.json                                con trỏ tới lần đẩy mới nhất (ghi cuối = commit)
```
- **Cổng chất lượng:** trước khi đẩy, mỗi bảng silver bị kiểm tra header đồng nhất, khóa duy nhất, có dữ liệu; gold phải là JSON hợp lệ. Lỗi thì chặn đẩy.
- **Idempotent:** so sánh size + hash, mỗi object có `x-amz-meta-sha256`; gold được ghi sau cùng; `--prune` chỉ xóa `silver/` và `gold/`, không bao giờ xóa `bronze/` hay `_meta/`.
- R2 không có object versioning kiểu S3, nên lịch sử thay đổi nằm trong manifest.

## PostgreSQL
`db/migrations/001_init.sql` tạo schema `field_shift`: 13 bảng dữ liệu (cùng tên và cột với bảng silver), khóa chính, khóa ngoại, CHECK, 2 view cho app (`v_region_overview`, `v_crop_ranking`) và bảng `pipeline_run` ghi lại lần nạp nào đang nằm trong DB. App nên đặt `search_path = field_shift`.

`load_postgres.py` kéo silver từ R2 (kiểm tra sha256 từng file), áp migration, rồi `TRUNCATE` + `COPY` + kiểm tra **trong một transaction**: kiểm tra hỏng thì rollback, DB giữ nguyên dữ liệu cũ. Một kiểm tra chặn việc bảng có dữ liệu ở lần nạp trước mà lần này về 0 dòng (thường do máy thiếu đầu vào: chạy `pull_bronze.py` rồi `run_etl.py --offline`); cho phép có chủ ý bằng `--allow-empty BẢNG`.

Đang dùng Neon: pipeline dùng chuỗi **trực tiếp** (`DATABASE_URL`), app dùng chuỗi pooled (`DATABASE_URL_POOLED`); xem mục 5b của tài liệu bên dưới. Cấu hình server, role, mạng và TLS khi tự host: [../docs/postgres-hosting.md](../docs/postgres-hosting.md).

Test tích hợp với Postgres thật: `TEST_DATABASE_URL=postgresql://... python -m pytest tests/test_postgres.py` (dùng DB dùng một lần: test xóa và tạo lại schema `field_shift`).

## QA và giới hạn đã biết
- **MODIS NDVI (nguồn chính):** chỉ lấy pixel `pixel_reliability` 0 hoặc 1; ngày hỏng được nội suy tuyến tính theo số ngày thực tế và đánh dấu `source = interpolated`. An Giang và Sóc Trăng phải nội suy khoảng 35–40% số ngày (mây mùa mưa).
- **POWER** là dữ liệu mô hình/tái phân tích ~0,5°; `GWETROOT`/`GWETTOP` **không phải** đo vệ tinh. **SMAP** thường bị gắn cờ "không khuyến nghị" ở nơi thực vật dày (lúa, rừng): chỉ vài vùng có `sm_recommended`.
- **GAEZ** là tiềm năng trung bình 20 năm, không phải từng năm; mô hình có thể lệch thực tế (cà phê quanh Buôn Ma Thuột ra thấp); nhiều cây có thể trùng giá trị tại một điểm.
- **Lớp phủ đất:** MODIS MCD12Q1 (500 m) và GFSAD (30 m) có thể mâu thuẫn ở vùng đồi núi; tin GFSAD hơn ở đó. Tọa độ các vùng `candidate` chưa được xác nhận ngoài thực địa.
- `EARTHDATA_TOKEN` cho GFSAD chưa được kiểm chứng; đường tải chắc chắn là tên đăng nhập + mật khẩu qua `urs.earthdata.nasa.gov` (có thể cần VPN).

## Ghi công
- FAO & IIASA. 2025. Global Agro-ecological Zoning version 5 (GAEZ v5) Model Documentation (CC BY 4.0).
- NASA POWER, MODIS, SMAP, GFSAD30, NASADEM: dữ liệu mở của NASA.

## Công cụ AI đã dùng
- **Claude Code** (Anthropic): viết và kiểm thử mã ETL, nạp R2/PostgreSQL, QA mưa (đối chiếu ERA5), lưới GAEZ cả nước, kiểm tra dữ liệu và soạn tài liệu. Con người quyết định nguồn dữ liệu, ngưỡng, và duyệt kết quả.
