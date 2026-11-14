# Kiểm tra toàn hệ thống theo tiêu chí đề thi (14/11/2026)

Phạm vi: dữ liệu, pipeline, cơ sở dữ liệu, bộ test, tài liệu và quy trình. Cách kiểm tra: chạy lại `audit_r2.py` trên R2 (đọc lại và băm lại từng file), chạy toàn bộ test, đo độ phủ test, quét bí mật, đối chiếu từng yêu cầu trong `FIELD-SHIFT-NOTES.md`. Ghi chú: **[ĐÃ XÁC NHẬN]** = đã chạy và thấy số; **[ĐÁNH GIÁ]** = nhận định của người kiểm tra, không phải số đo.

## 1. Kết luận ngắn
- **Phần dữ liệu và pipeline đáp ứng tốt** yêu cầu về độ tin cậy: 6 vùng, 11 năm, mọi nguồn đều có kiểm tra chéo hoặc ghi rõ giới hạn.
- **Phần sản phẩm người dùng chưa có:** `app/` chỉ có README, chưa có giao diện, chưa có slide hay video. Đây là rủi ro lớn nhất cho các tiêu chí **Impact, Creativity và Presentation**, và nó nằm ngoài phạm vi dữ liệu.
- **Bộ sinh phương án luân canh** (CLI `rotation_options.py`, Phát làm) đáp ứng yêu cầu "so sánh ít nhất 3 chiến lược, gồm cả hiện tại, kèm lý do, bằng chứng, lợi ích, rủi ro, chỗ còn thiếu". Nó **chưa dùng** các đầu vào mới của DATA-03 (cân bằng nước, độ dốc, đất, doanh thu).

## 2. Đối chiếu 5 tiêu chí chấm điểm của NASA

| Tiêu chí | Hiện trạng | Mức |
|---|---|---|
| **Validity** (độ tin cậy) | Mọi nguồn đều đối chiếu độc lập (mục 3). Khoảng trống không bao giờ là 0. Ngày nội suy được gắn nhãn. Giới hạn ghi trong `caveats` của từng vùng | **Mạnh** |
| **Relevance** | Năm ưu tiên (nước, đất, đạm, xói mòn, thu nhập) đều có dữ liệu hoặc khai báo thiếu. Nguồn NASA: POWER, MODIS, SMAP, GFSAD30, NASADEM. Đề nêu thêm GPM, ECOSTRESS, GEDI, GRACE, Landsat: chưa dùng (mưa lấy CHIRPS thay GPM) | Khá |
| **Impact** | Phụ thuộc sản phẩm; dữ liệu đã đủ để chạy 4 phương án luân canh cho 6 vùng | **Chưa có giao diện** |
| **Creativity** | Điểm khác biệt có thật: kiểm tra mưa bằng nguồn độc lập thay vì tin mô hình, doanh thu thô nêu rõ không phải lợi nhuận, không có điểm tổng giả. Chưa được trình bày | Tiềm năng |
| **Presentation** | Chưa có slide, video, bản demo. Thẻ Kan "Hồ sơ nộp" vẫn ở To Do | **Chưa làm** |

## 3. Độ tin cậy dữ liệu [ĐÃ XÁC NHẬN, chạy `audit_r2.py` 14/11]

| Hạng mục | Kết quả |
|---|---|
| Toàn vẹn R2 | run `20261114T094741Z`: 1077 object, 0 lỗi sha256, 0 object ngoài manifest |
| Phủ thời gian | 6 vùng x 4018 ngày khí hậu (2015-2025), NDVI 254 mốc/vùng |
| NDVI hai nguồn độc lập (MODIS và GIBS, 2023-2025) | Pearson r = 0,97 / 0,97 / 0,93 / **0,70** / 0,96 / 0,94. Đắk Lắk thấp (cà phê lâu năm, ít biến động) |
| NDVI đo thật, tỷ lệ mốc | Sơn La 89%, Ninh Thuận 94%, Đắk Lắk 80%, Thái Bình 67%, An Giang 66%, **Sóc Trăng 60%** (phần còn lại là nội suy, gắn nhãn) |
| Số vụ lúa từ đỉnh NDVI | Thái Bình trung vị 2 (đúng 2 vụ), An Giang 2 (đúng 2-3), Sơn La 1 (đúng ngô một vụ) |
| Độ cao NASADEM so với nơi vùng nhận là | 6/6 hợp lý |
| Mưa POWER so với CHIRPS (trung bình năm) | Thái Bình +2%, Sơn La +20%, **Ninh Thuận +126%**, Đắk Lắk -5%, An Giang +12%, Sóc Trăng -5%. Sản phẩm dùng CHIRPS (`rain_monthly_best`), 0 tháng phải dùng POWER thay thế |
| ET0 tính từ POWER so với ET0 của GAEZ | Thái Bình -1%, Sóc Trăng +4%, An Giang +7%, **Sơn La -18%, Ninh Thuận -16%, Đắk Lắk -26%**: đã hiệu chỉnh theo vùng, giữ số gốc |
| Đất và độ dốc có hợp lý không | Sơn La dốc 34,6% và yếu tố đất hạn chế nhất 0,27; Sóc Trăng độ phì 0,06 và mặn 0,26 (đúng bối cảnh lúa-tôm); đồng bằng 3-4% |
| Bảng cây trồng | 24 họ thực vật khớp GBIF; 20/24 cây có giá và năng suất Việt Nam; 4 cây để trống vì không có nguồn |
| Nạp Neon | 49/49 kiểm tra qua |

## 4. Bộ test [ĐÃ XÁC NHẬN]
- **266 test qua, 4 bỏ qua** (3 cần PostgreSQL thật, chạy trong CI; 1 là test SMAP L4 chờ nhánh DATA-08). CI trên `main` xanh, kể cả PostgreSQL 17 thật.
- **Độ phủ mã 82%** (trước đợt này 77%). Module quan trọng: bộ sinh luân canh 100%, QA mưa 100%, các bộ biến đổi dữ liệu 91-100%, `http_client` 98%, `silver_to_gold` (tạo gold JSON) 80%.
- **Test mới trong đợt này (84 test):**
  - `test_repo_consistency.py`: mã migration không trùng, mỗi migration tự đăng ký đúng phiên bản, mọi bảng đều có trong `LOAD_ORDER` và khóa của data lake, bảng cha nạp trước bảng con, cây trong `config.yaml` khớp hai bảng cây, `.env.example` đủ biến, không có chuỗi giống bí mật. Đã kiểm tra các test này **thật sự fail** khi cố tình làm hệ thống sai (3 thử nghiệm).
  - `test_gold_contract.py`: hợp đồng của gold JSON và silver CSV mà app đọc (khóa bắt buộc, đơn vị, khoảng trống không bằng 0, cảnh báo bắt buộc đi kèm dữ liệu).
  - `test_network_clients.py`: thử lại, không thử lại lỗi 4xx, cache không để file dở, chế độ offline không chạm mạng, chuỗi thiếu tháng không được cache như đầy đủ.
  - `test_appeears_tasks.py`: tạo task, băm task, đọc kết quả, chế độ offline, thiếu tài khoản.
- **Chưa phủ tốt:** `gfsad.py` 33% (tải tile qua Earthdata), `postgres.py` 45% (phần cần máy chủ thật, CI phủ), `faostat.py` 71%, `power_client.py` 64%, `appeears_client.py` 52%.
- **Sửa `audit_r2.py`:** công cụ này bị lỗi khi gặp ngày mưa NULL (do QA mưa DATA-05), nay đã sửa, thêm mục J (mưa), K (đầu vào môi trường), L (danh sách kiểm tra đề thi, mỗi dòng là một phép kiểm thật, không có dòng nào đặt cứng).

## 5. Quy trình và bảo mật
- **Quy định "phần lõi làm trong thời gian thi":** toàn bộ 54 commit đều trong ngày 14/11, commit đầu lúc 09:30. [ĐÃ XÁC NHẬN]
- **Khai báo công cụ AI:** có trong README gốc và `pipeline/README.md`; `app/README.md` mới ghi chung, cần cập nhật khi có mã ứng dụng. [ĐÃ XÁC NHẬN]
- **Bí mật trong repo:** quét file đang theo dõi và lịch sử, không thấy khóa thật. Chỉ có chuỗi mẫu trong `.env.example` và test. [ĐÃ XÁC NHẬN]
- **Còn rủi ro (OPS-03, chưa làm):** khóa R2, token `cfut_`, mật khẩu Earthdata, chuỗi kết nối Neon, khóa Kan đã xuất hiện trong chat; mật khẩu Earthdata còn nằm trong `C:\Workspace\field_shift_etl\.env.example` (ngoài repo). Cảnh báo GitGuardian về mật khẩu CI vẫn nằm trong lịch sử commit (đã chọn bỏ qua).

## 6. Việc còn lại, theo mức ưu tiên cho ngày thi
**Bắt buộc để có sản phẩm (ngoài dữ liệu):**
1. Giao diện: bản đồ chọn điểm, chọn cây hiện tại, chọn ưu tiên, hiển thị 3+ phương án với lý do, bằng chứng, lợi ích, rủi ro, chỗ thiếu thông tin.
2. Nối bộ sinh luân canh với đầu vào DATA-03 (cân bằng nước, độ dốc và xói mòn, đất, doanh thu thô).
3. Slide (7) hoặc video (30 giây), tài liệu tham khảo, cập nhật `app/README.md`.
4. Xác nhận thể lệ và hạn nộp với ban tổ chức điểm thi TP.HCM (mục đầu của checklist trong notes).

**Dữ liệu, nếu còn thời gian:**
5. DATA-08: SMAP L3 không có chất lượng khuyến nghị ở 4/6 vùng; hướng SMAP L4 đã có mã trên nhánh `feat/smap-l4-data08`, task AppEEARS chưa xong, cần đổi migration sang 010.
6. DATA-09: Sóc Trăng và An Giang phải nội suy 35-40% số mốc NDVI (mây mùa mưa).
7. DATA-10: MODIS và GFSAD mâu thuẫn về đất canh tác ở Sơn La (0% so với 58%) và Đắk Lắk.
8. Cột bảng cây còn thiếu: mùa trồng, nhiệt độ tối ưu và ngưỡng nóng, số ngày sinh trưởng thực tế ở Việt Nam. Còn thiếu: thấm nước, kết cấu đất, hệ số cây trồng Kc, chi phí sản xuất.
9. Chỉ 6 vùng; tọa độ các vùng `candidate` chưa xác nhận ngoài thực địa. Lưới khí hậu cả nước `vn_grid_monthly` vẫn dùng mưa POWER.

**Bảo mật:** đổi các khóa ở mục 5 trước khi công khai repo hay nộp bài.
