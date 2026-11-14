# Tự host PostgreSQL cho app Field Shift

Hướng dẫn cho máy server tự quản. Phần cấu hình server (mục 2, 3) là chỉ dẫn chuẩn của PostgreSQL, **chưa được thử trên máy server của dự án**; hãy xác nhận bằng `python load_postgres.py --check-server` (mục 5).

## 1. Quy mô: nhỏ
Silver chỉ ~15 MB CSV, ~400.000 dòng (364.000 dòng là lưới khí hậu cả nước). Dự kiến database dưới ~150 MB và một lần nạp mất vài giây đến dưới một phút (đây là ước tính, chưa đo trên server thật). Không cần máy mạnh, không cần tinh chỉnh `shared_buffers` hay WAL cho việc này.

## 2. Yêu cầu server
- **PostgreSQL 14 trở lên** (bản 16 hoặc 17 đều được; CI kiểm thử trên 17).
- **Database mã hóa UTF8.** Tên vùng và tên cây có tiếng Việt; database LATIN1 hoặc SQL_ASCII sẽ lỗi hoặc làm hỏng chữ khi `COPY`. Tạo bằng `ENCODING 'UTF8' TEMPLATE template0`.
- Hai role riêng, không dùng `postgres` cho pipeline hay app:

```sql
CREATE ROLE fs_loader LOGIN PASSWORD '<mật khẩu mạnh>';   -- pipeline: tạo bảng, nạp dữ liệu
CREATE ROLE fs_app    LOGIN PASSWORD '<mật khẩu mạnh>';   -- app: chỉ đọc
CREATE DATABASE fieldshift OWNER fs_loader ENCODING 'UTF8' TEMPLATE template0;
```
Sau lần `python load_postgres.py --migrate-only` đầu tiên (chạy bằng `fs_loader`, schema `field_shift` sẽ thuộc `fs_loader`):
```sql
GRANT USAGE ON SCHEMA field_shift TO fs_app;
GRANT SELECT ON ALL TABLES IN SCHEMA field_shift TO fs_app;              -- gồm cả view
ALTER DEFAULT PRIVILEGES FOR ROLE fs_loader IN SCHEMA field_shift GRANT SELECT ON TABLES TO fs_app;
ALTER ROLE fs_app SET search_path = field_shift, public;
```
`TRUNCATE` trong lần nạp không làm mất quyền đã cấp.

## 3. Mạng và bảo mật (khó khăn thường gặp nhất)
- **Đừng mở cổng 5432 ra Internet.** Chỉ cho phép địa chỉ của máy chạy pipeline và máy chạy app: tường lửa của server **và** `pg_hba.conf`:
  ```
  hostssl  fieldshift  fs_loader  <IP máy pipeline>/32  scram-sha-256
  hostssl  fieldshift  fs_app     <IP máy app>/32       scram-sha-256
  ```
  kèm `listen_addresses = '*'` (hoặc đúng địa chỉ mạng) trong `postgresql.conf`. Sau khi sửa `pg_hba.conf`, chạy `SELECT pg_reload_conf();`.
- **Nếu server ở mạng khác** (nhà, văn phòng, sau NAT): dùng VPN (Tailscale, WireGuard) hoặc SSH tunnel (`ssh -L 5432:localhost:5432 user@server`, rồi đặt `DATABASE_URL=postgresql://...@localhost:5432/fieldshift`). Máy dev hiện bật **Cloudflare WARP**; địa chỉ LAN thường được loại khỏi WARP mặc định nhưng nếu không kết nối được thì kiểm tra điểm này trước.
- **TLS:** bật `ssl = on` với chứng chỉ trên server. `sslmode=require` trong `DATABASE_URL` mã hóa kênh nhưng **không kiểm tra chứng chỉ** (giống libpq). Loader chưa hỗ trợ trỏ tới CA riêng (`sslrootcert`), nên với chứng chỉ tự ký hãy dùng `require` hoặc đi qua tunnel; `verify-full` chỉ chạy với chứng chỉ do CA công cộng cấp.
- Mật khẩu chỉ đặt trong `pipeline/.env` (`DATABASE_URL=postgresql://fs_loader:...@host:5432/fieldshift?sslmode=require`), không commit. Ký tự đặc biệt trong mật khẩu phải được mã hóa URL (`@` thành `%40`).

## 4. Quy tắc để app không làm hỏng lần nạp
Mỗi lần nạp là **làm mới toàn bộ**: `TRUNCATE` 13 bảng rồi `COPY`, trong một transaction.
- **Bảng của app (người dùng, kịch bản đã lưu...) đặt ở schema khác** và **không tạo khóa ngoại trỏ vào bảng của pipeline.** Một khóa ngoại như vậy làm `TRUNCATE` thất bại. Hãy lưu `region_id` / `crop_code` dạng text, không ràng buộc.
- Trong lúc nạp (vài giây), các bảng bị khóa; truy vấn của app sẽ chờ đến khi commit rồi thấy dữ liệu mới. Nếu kiểm tra thất bại thì rollback và app vẫn thấy dữ liệu cũ.
- `region_id`, `crop_code` là mã ổn định, không đổi giữa các lần nạp.

## 5. Quy trình kiểm tra và nạp
```powershell
python load_postgres.py --dry-run          # không cần server: dữ liệu có qua được PK/FK/CHECK/kiểu không
python load_postgres.py --check-server     # server đã đủ điều kiện chưa (phiên bản, UTF8, quyền, TLS, độ trễ)
python load_postgres.py --migrate-only     # tạo schema
python load_postgres.py                    # nạp từ R2
```
`--dry-run` chỉ là bản mô phỏng bằng SQLite từ cùng file migration: nó bắt lỗi dữ liệu, không thay được việc thử trên server thật.

## 6. Sao lưu
Dữ liệu pipeline là **dữ liệu dẫn xuất**: R2 giữ bản gốc và `load_postgres.py` dựng lại database bất cứ lúc nào. Chỉ cần `pg_dump` các schema của app (người dùng, kịch bản); không cần sao lưu schema `field_shift`.
