# app/

NASA Space Apps Challenge 2026, đề **Field Shift: Adapting Farms with NASA Data**. Thư mục này chứa **ứng dụng web** (công cụ hỗ trợ ra quyết định luân canh). Dữ liệu do thư mục `pipeline/` tạo ra.

> **Quy định:** phần lõi của sản phẩm phải được phát triển trong thời gian thi (14–15/11/2026); mọi công cụ AI dùng trong dự án phải khai báo khi nộp bài. Lịch sử commit của repo này thể hiện công việc làm trong thời gian thi.

## Mục tiêu sản phẩm (theo đề)
Người dùng chọn vị trí, cây hiện tại và ưu tiên (tiết kiệm nước, đất, đạm, xói mòn, thu nhập). Công cụ dùng dữ liệu NASA và đối tác để:
- hiển thị hồ sơ khí hậu và độ xanh thực vật của vị trí;
- so sánh **ít nhất 3 phương án luân canh** (gồm phương án hiện tại): vì sao, bằng chứng, lợi ích, rủi ro, thông tin còn thiếu;
- nhắc rõ đây là công cụ **hỗ trợ**, không thay thế phán đoán của nông dân hay chuyên gia địa phương.

## Dữ liệu đầu vào
App đọc **PostgreSQL (Neon) qua API trong `app/api/`**, **không gọi API ngoài (NASA, FAO) lúc chạy**. Pipeline nạp dữ liệu vào Postgres; mô hình dữ liệu xem `docs/data-contract.md`.

## Cấu trúc
```
api/        backend FastAPI (chỉ đọc): phương án luân canh, danh sách cây, ô lưới cho bản đồ. Xem api/README.md
web/        giao diện: HTML, CSS và JavaScript thuần (không build), MapLibre cho bản đồ. API phục vụ luôn thư mục này ở "/"
```
Quyết định (14/11, Hùng chốt): giao diện là file tĩnh do chính API phục vụ, nên một container Python là đủ và không cần CORS. Chuyển sang framework (React...) để sau cuộc thi nếu cần.

## Chạy
```powershell
cd app/api
pip install -r requirements.txt
$env:APP_DATABASE_URL = "postgresql://...?sslmode=require"
uvicorn fieldshift_api.main:app --port 8000      # giao diện ở http://localhost:8000/ , tài liệu API ở /docs
```
Chi tiết backend: [api/README.md](api/README.md). Test giao diện: `node --test` trong `app/web` (Node 20 trở lên, không cần cài gói).

Giao diện gọi `/api/...` cùng địa chỉ. Khi mở file tĩnh bằng máy chủ khác, thêm `?api=http://localhost:8000` vào địa chỉ trang (và đặt `CORS_ORIGINS` cho API).

## Nguồn dữ liệu và ghi công
- NASA POWER, NASA MODIS (NDVI), NASA GFSAD30
- FAO & IIASA. 2025. Global Agro-ecological Zoning version 5 (GAEZ v5) Model Documentation (CC BY 4.0)
- Ranh giới tỉnh trong giao diện (`web/data/provinces.geojson`): geoBoundaries (gbOpen, ADM1, Việt Nam, bản đã đơn giản hoá). Trường giấy phép của geoBoundaries ghi là miền công cộng; **dữ liệu thuộc năm 2008**, nên không khớp ranh giới và tên tỉnh sau các đợt sáp nhập.
- Ảnh vệ tinh nền bản đồ: Esri World Imagery (Esri, Maxar, Earthstar Geographics). Là dịch vụ ngoài lúc chạy; điều khoản sử dụng chưa được kiểm tra (OPS-14).

## Công cụ AI đã dùng
- **Claude Code** (Anthropic) được dùng trong dự án (xem README gốc). Với mã ứng dụng: backend `app/api/` (14/11/2026) được viết cùng Claude Code (mô hình Claude Sonnet 5.5); bộ sinh phương án luân canh mà API gọi (`pipeline/src/rotation/`) cũng viết cùng Claude Code. Giao diện `app/web/` (14/11/2026) cũng được viết cùng Claude Code (Claude Sonnet 5.5): HTML, CSS, JavaScript và test; kiểm tra bằng trình duyệt tự động chạy với dữ liệu thật.
