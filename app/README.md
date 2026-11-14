# app/

NASA Space Apps Challenge 2026, đề **Field Shift: Adapting Farms with NASA Data**. Thư mục này chứa **ứng dụng web** (công cụ hỗ trợ ra quyết định luân canh). Dữ liệu do thư mục `pipeline/` tạo ra.

> **Quy định:** phần lõi của sản phẩm phải được phát triển trong thời gian thi (14–15/11/2026); mọi công cụ AI dùng trong dự án phải khai báo khi nộp bài. Lịch sử commit của repo này thể hiện công việc làm trong thời gian thi.

## Mục tiêu sản phẩm (theo đề)
Người dùng chọn vị trí, cây hiện tại và ưu tiên (tiết kiệm nước, đất, đạm, xói mòn, thu nhập). Công cụ dùng dữ liệu NASA và đối tác để:
- hiển thị hồ sơ khí hậu và độ xanh thực vật của vị trí;
- so sánh **ít nhất 3 phương án luân canh** (gồm phương án hiện tại): vì sao, bằng chứng, lợi ích, rủi ro, thông tin còn thiếu;
- nhắc rõ đây là công cụ **hỗ trợ**, không thay thế phán đoán của nông dân hay chuyên gia địa phương.

## Dữ liệu đầu vào
App đọc file dữ liệu đã xử lý, **không gọi API ngoài lúc chạy**. Cấu trúc file và nơi lưu (Cloudflare R2) xem `docs/data-contract.md` và thư mục `pipeline/`.

## Cấu trúc (dự kiến)
```
src/        mã ứng dụng
public/     tài nguyên tĩnh
docs/       ghi chú thiết kế
```

## Chạy
_(bổ sung khi có mã)_

## Nguồn dữ liệu và ghi công
- NASA POWER, NASA MODIS (NDVI), NASA GFSAD30
- FAO & IIASA. 2025. Global Agro-ecological Zoning version 5 (GAEZ v5) Model Documentation (CC BY 4.0)

## Công cụ AI đã dùng
- **Claude Code** (Anthropic) được dùng trong dự án (xem README gốc). Phần dùng cho mã ứng dụng sẽ được ghi cụ thể tại đây khi có.
