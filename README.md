# Field Shift: Adapting Farms with NASA Data

NASA Space Apps Challenge 2026, đề **Field Shift: Adapting Farms with NASA Data**. Công cụ hỗ trợ ra quyết định luân canh dựa trên dữ liệu NASA và đối tác.

> **Quy định:** phần lõi sản phẩm phải được phát triển trong thời gian thi (14–15/11/2026); mọi công cụ AI dùng trong dự án phải khai báo khi nộp bài. Lịch sử commit của repo này thể hiện công việc làm trong thời gian thi.

## Mục tiêu sản phẩm (theo đề)
Người dùng chọn vị trí, cây hiện tại và ưu tiên (tiết kiệm nước, đất, đạm, xói mòn, thu nhập). Công cụ:
- hiển thị hồ sơ khí hậu và độ xanh thực vật của vị trí;
- so sánh **ít nhất 3 phương án luân canh** (gồm phương án hiện tại): vì sao, bằng chứng, lợi ích, rủi ro, thông tin còn thiếu;
- nhắc rõ đây là công cụ **hỗ trợ**, không thay thế phán đoán của nông dân hay chuyên gia địa phương.

## Cấu trúc repo
```
app/        ứng dụng web (đọc dữ liệu từ PostgreSQL, không gọi API ngoài lúc chạy)
pipeline/   lấy, xử lý, đóng gói dữ liệu; đẩy lên Cloudflare R2 và nạp vào PostgreSQL
docs/       ghi chú dữ liệu (GAEZ) và hợp đồng dữ liệu giữa pipeline và app (v1: PostgreSQL)
```

## Nguồn dữ liệu
| Nguồn | Dùng cho |
|---|---|
| NASA POWER | khí hậu (nhiệt độ, mưa, độ ẩm đất, nắng) |
| NASA MODIS NDVI (AppEEARS) | độ xanh thực vật + chất lượng pixel |
| NASA GFSAD30SEACE | mặt nạ đất canh tác |
| FAO GAEZ v5 (`RES05-SXX30AS`) | mức thích hợp của cây trồng (0–10000) |

Chi tiết GAEZ, mã cây, cách đối chiếu: [docs/gaez-notes.md](docs/gaez-notes.md). Hợp đồng dữ liệu nháp: [docs/data-contract.md](docs/data-contract.md).

## Bí mật và dữ liệu thô
Không commit khóa, `.env` hay dữ liệu thô lớn (đã chặn trong `.gitignore`). Kết nối Cloudflare R2 đặt trong biến môi trường (mẫu `pipeline/.env.example`); trong CI dùng GitHub Secrets.

## Ghi công
- FAO & IIASA. 2025. Global Agro-ecological Zoning version 5 (GAEZ v5) Model Documentation (CC BY 4.0).
- NASA POWER, MODIS, GFSAD30: dữ liệu mở của NASA.

## Công cụ AI đã dùng
_(ghi rõ công cụ và mục đích khi nộp bài)_
