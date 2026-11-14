# Kiểm tra dữ liệu R2 so với yêu cầu dự án (14/11/2026)

Phạm vi: bucket `field-shift-nasa`, lần chạy `20261114T030142Z`, gold schema `v0.3`. Dữ liệu đọc **từ R2** (không dùng bản local). Chạy lại bằng `python audit_r2.py` trong `pipeline/`. Yêu cầu dùng làm thước đo lấy từ ghi chú dự án (hợp đồng dữ liệu mục 2.2, mục tiêu sản phẩm, bài học mục 4) và README của repo.

## Kết luận
Dữ liệu **nguyên vẹn và đủ** cho khí hậu, NDVI, GAEZ, lớp phủ đất. Nhưng **chưa đủ để chạy đúng yêu cầu**: thiếu bảng cây trồng và vài đầu vào để so sánh luân canh. Về độ tin cậy có một lỗi dữ liệu rõ ràng (mưa) và vài điểm cần cảnh báo khi trình bày.

## 1. Toàn vẹn: đạt
633 object khớp manifest và sha256, catalog cùng lần chạy với manifest, không có object lạ, gold và silver cùng số dòng NDVI. Silver nạp sạch vào bản mô phỏng Postgres (`load_postgres.py --dry-run`).

## 2. Đối chiếu với yêu cầu

| Yêu cầu | Tình trạng |
|---|---|
| Hợp đồng 1: khí hậu POWER theo ngày/tháng | **Đủ**: 2015–2025, 4.018 ngày/vùng, 0 ô thiếu, có đơn vị (LST). Chưa có 2026. |
| Hợp đồng 2: NDVI `date, median_final, source, flag_bad, reasons` | **Đủ**: 254 mốc/vùng, 2014-12-19 đến 2025-12-19 |
| Hợp đồng 3: metadata (tọa độ, khung, ngày tạo) | **Đủ** trong gold; bảng DB chưa có cột ngày tạo (có `pipeline_run.loaded_at`) |
| **Hợp đồng 4: bảng cây trồng** | **THIẾU.** `dim_crop` chỉ có `crop_code`, `name_vi`, `name_verified`. Thiếu: mùa trồng, thời gian sinh trưởng, khoảng nhiệt độ thích hợp, ngưỡng rét/nóng, nhu cầu nước, họ đậu, độ phủ đất/chống xói mòn, giá thị trường, nguồn. |
| Cây / luân canh hiện tại của từng vùng | **Thiếu** (không có trong dữ liệu) |
| 5 ưu tiên: nước, đất, đạm, xói mòn, thu nhập | Nước: có khí hậu, thiếu nhu cầu nước từng cây. Đất/thấm nước: không có số liệu đất. Đạm: thiếu cờ họ đậu. Xói mòn: có độ cao, chưa tính độ dốc. Thu nhập: thiếu giá. |
| Cắt chu kỳ sâu bệnh | **Thiếu** họ thực vật của từng cây |
| Thuật ngữ: bốc thoát hơi nước, cân bằng nước | Chưa có; tính được từ nhiệt độ và bức xạ POWER. Sương giá: có `t2m_min`. |
| Vệ tinh so với mặt đất | Không có số liệu trạm mặt đất |
| Hài hòa độ phân giải | Có 5 mức: GFSAD 30 m, MODIS 250 m, GAEZ ~0,9 km, SMAP 9 km, POWER ~0,5°. Chưa có GPM, ECOSTRESS, Landsat, GEDI, GRACE. |
| Thanh trượt kịch bản mưa/nhiệt | Có biến động theo năm; chưa có kịch bản tương lai (GAEZ tương lai chưa lấy) |
| Chọn vị trí trên bản đồ | Chỉ **6 vùng** có đủ dữ liệu; ngoài đó chỉ có lưới khí hậu POWER |

## 3. Độ chính xác

**Tốt**
- Cao độ NASADEM khớp địa điểm cả 6 vùng (Thái Bình 1 m, Sóc Trăng 2 m, An Giang 2 m, Ninh Thuận 8 m, Đắk Lắk 454 m, Sơn La 674 m): tọa độ không sai.
- NDVI hai nguồn độc lập (MODIS qua AppEEARS và ảnh GIBS) 2023–2025: Pearson r = 0,97 (Thái Bình, Sơn La), 0,96 (An Giang), 0,94 (Sóc Trăng), 0,93 (Ninh Thuận), **0,70 (Đắk Lắk)**. Đắk Lắk thấp hơn vì hai nguồn nhìn hai diện tích khác nhau (MODIS đã lọc điểm đất canh tác).
- Số đỉnh NDVI mỗi năm khớp thực tế: Thái Bình 2 đỉnh (9/11 năm), An Giang 2–3, Sơn La 1.

**Vấn đề, xếp theo mức nghiêm trọng**
1. **Mưa có giá trị phi lý.** An Giang ngày **2020-06-14 = 691 mm trong một ngày**; tháng 6/2020 ra 1.114 mm, tổng năm 2020 ra 3.041 mm. Đây là ngày duy nhất vượt 250 mm trong toàn bộ 24.108 ngày-vùng, nên nhiều khả năng là lỗi của mô hình MERRA-2. Sơn La 2022-02-04 ra 211 mm giữa mùa khô cũng đáng ngờ.
2. **Ninh Thuận ra 1.961 mm/năm**, trong khi đây được biết là vùng khô nhất nước. Theo hiểu biết của người viết ghi chú này, Phan Rang chỉ khoảng 700 mm; **con số đó chưa được kiểm chứng**, trong dữ liệu không có trạm để đối chiếu. POWER ~0,5° trộn đồng bằng khô với núi ẩm, nên không thể hiện được vùng khuất mưa. Mùa mưa (đỉnh tháng 9–11) thì đúng, lượng thì nhiều khả năng sai.
3. **Năm 2015 khô bất thường ở mọi vùng** (Đắk Lắk 423 mm so với 1.866–2.316 mm các năm khác; các tháng 5–10 chỉ 15–27 mm). Phù hợp El Niño 2015–16 nhưng quá cực đoan, chưa kiểm chứng.
4. **SMAP đạt chất lượng khuyến nghị chỉ ở 2/6 vùng** (Sóc Trăng 81%, Thái Bình 64%; 4 vùng còn lại 0%). Đã đối chiếu mô tả của NASA: đây là kết quả thật do thực vật dày, không phải lỗi giải mã.
5. **NDVI phải nội suy nhiều ở đồng bằng**: tỷ lệ đo được Sóc Trăng 60% (năm 2022 chỉ 39%), An Giang 66% (năm 2022 là 52%), Thái Bình 67%. Số vụ ở Sóc Trăng lúc 1 lúc 3 đỉnh nên không nên kết luận mạnh. Sơn La 89%, Ninh Thuận 94%, Đắk Lắk 80%.
6. **MODIS và GFSAD mâu thuẫn về đất canh tác**: Sơn La 0% so với 58%, Đắk Lắk 36% so với 50%. Cao độ xác nhận đúng địa điểm, nhưng việc nó có phải đất canh tác hay không chưa chốt.
7. **GAEZ phản ánh tiềm năng của mô hình, không phải thực tế canh tác**: ví dụ ở An Giang lúa cạn (9.410) cao hơn lúa nước (8.460) ở mức `HRLM`; chỉ số không đơn điệu theo mức đầu vào (22/144 cặp vùng-cây có `LRLM` > `HRLM`).
8. **Độ phủ thời gian**: POWER và MODIS kết thúc cuối 2025 (thiếu ~10,5 tháng của 2026); GFSAD chỉ có năm 2015; GIBS chỉ 2023–2025.

## 4. Việc cần làm

| Ưu tiên | Việc | Gợi ý người làm |
|---|---|---|
| 1 | Lập bảng cây trồng đủ cột của hợp đồng 4, **thêm cột họ thực vật** (cho chu kỳ sâu bệnh); ghi nguồn từng cột | Hùng |
| 2 | Thêm quy tắc chặn mưa ngày bất thường và đối chiếu mưa với nguồn độc lập. Đề bài có nêu **GPM IMERG** (NASA, ~10 km); chưa thử truy cập | Phat |
| 3 | Tính độ dốc (từ NASADEM) và bốc thoát hơi nước / cân bằng nước (từ POWER) trong pipeline | Phat |
| 4 | Chốt vùng demo: xác nhận Sơn La và Đắk Lắk có phải đất canh tác không; nếu giữ Ninh Thuận làm vùng khô thì ghi chú rõ hạn chế của số mưa | Cả hai |
| 5 | Khi trình bày: nêu rõ tỷ lệ NDVI nội suy, SMAP chất lượng thấp, GAEZ là tiềm năng (tiêu chí Validity) | Cả hai |

Danh sách việc chi tiết (mã số, mức ưu tiên, cách xử lý, tiêu chí hoàn thành) và hướng dẫn bàn giao: [data-issues.md](data-issues.md).

## 5. Giới hạn của chính cuộc kiểm tra
- Không có số liệu trạm mặt đất trong dữ liệu, nên "đúng/sai" chủ yếu dựa vào tính hợp lý và đối chiếu chéo giữa các nguồn.
- Phép đếm đỉnh NDVI dùng ngưỡng tự chọn (giá trị tối thiểu 0,45, độ nổi 0,15).
- Bronze chỉ được kiểm tra bằng hash, chưa dựng lại để so sánh. `load_postgres.py` chưa được chạy với dữ liệu thật trên một server Postgres.
