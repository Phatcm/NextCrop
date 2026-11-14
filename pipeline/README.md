# pipeline/

Pipeline lấy, xử lý và đóng gói dữ liệu cho app Field Shift (thư mục `app/`). Kết quả là các file nhỏ, tĩnh, đặt trên Cloudflare R2 để app đọc.

> **Quy định:** phần lõi sản phẩm phải làm trong thời gian thi (14–15/11/2026); khai báo công cụ AI khi nộp bài. Không commit dữ liệu thô lớn hoặc khóa/bí mật.

## Nguồn dữ liệu
| Nguồn | Dùng cho | Truy cập |
|---|---|---|
| NASA POWER | khí hậu (nhiệt độ, mưa, độ ẩm đất, nắng) | API công khai, không cần khóa |
| NASA MODIS NDVI (AppEEARS) | độ xanh thực vật + chất lượng pixel | cần tài khoản Earthdata |
| NASA GFSAD30SEACE | mặt nạ đất canh tác 30 m | cần tài khoản Earthdata |
| FAO GAEZ v5 (`RES05-SXX30AS`) | mức thích hợp của cây trồng (0–10000) | bucket Google Cloud Storage công khai |

Chi tiết lớp GAEZ, mã cây và cách đối chiếu: `../docs/gaez-notes.md`.

## Cấu trúc
```
../docs/         ghi chú dữ liệu và hợp đồng dữ liệu (nháp)
raw/             dữ liệu thô tải về (KHÔNG commit, xem .gitignore)
processed/       file nhỏ đã xử lý để đưa lên R2 (có thể commit mẫu nhỏ)
scripts/         mã pipeline
.env.example     mẫu biến môi trường (không chứa bí mật)
```

## Cloudflare R2
Bucket chứa các file đã xử lý. Thông tin kết nối đặt trong biến môi trường (xem `.env.example`); **không** commit khóa, dùng GitHub Secrets nếu chạy trong CI.

## Chạy
_(bổ sung khi có mã)_

## Ghi công
- FAO & IIASA. 2025. Global Agro-ecological Zoning version 5 (GAEZ v5) Model Documentation (CC BY 4.0).
- NASA POWER, MODIS, GFSAD30: dữ liệu mở của NASA.

## Công cụ AI đã dùng
_(ghi rõ công cụ và mục đích khi nộp bài)_
