# Quy tắc sinh phương án luân canh (DATA-02)

Mã: `pipeline/src/rotation/options.py`; thử bằng `python rotation_options.py --lat 10.45 --lon 105.35 --crop RCW` (từ `pipeline/`). Đây là công cụ **hỗ trợ**, không phải lịch gieo hay dự báo năng suất từng ruộng.

## Đầu vào
- Vị trí: ô lưới GAEZ gần nhất trong 0,1° (`gaez_grid`); xa hơn thì không trả lời.
- Cây hiện tại (một trong các cây một năm của `dim_crop`) và mức đầu vào GAEZ (`hilm/hrlm/lilm/lrlm`, mặc định nước trời + đầu vào cao).
- Số vụ trong năm: mặc định là số vụ cây hiện tại vừa trong 365 ngày (tối đa 3), có thể ghi đè.
- **Ba tham số người dùng chỉnh được** (kết quả luôn ghi lại giá trị đã dùng, nguồn và cờ `custom`):

| Tham số | Mặc định | Nguồn |
|---|---|---|
| `gap_rice`: ngày nghỉ giữa hai vụ lúa nước | 7 | Trung bình 5,6 và 6,6 ngày ở một nông hộ (ba thửa, Thốt Nốt, Cần Thơ, 2011–2016), F1000Research, PMC7059783. Chỉ một nông hộ |
| `gap_other`: ngày nghỉ giữa mọi cặp vụ khác | 15 | **Giả định của dự án, chưa có nguồn.** Thực tế có thể từ gần 0 (gieo không làm đất ngay sau gặt) đến vài chục ngày (lên liếp, thoát nước) |
| `min_index`: chỉ số GAEZ tối thiểu của cây thay thế | 4000 | Ranh giới lớp "phù hợp trung bình" của FAO (40% năng suất tối đa); dưới đó FAO ghi "thương mại không khả thi" (GAEZ v5 wiki, Module V) |

Cả ba nằm trong khoảng 0–60 ngày (hai khoảng nghỉ) và 0–10000 (chỉ số); ngoài khoảng thì báo lỗi. Đổi khoảng nghỉ có thể làm đổi số vụ trong năm (ví dụ lúa nước 30 ngày nghỉ thì 3 vụ thành 2 vụ): kết quả có `warnings` nói rõ.
- Ưu tiên (tùy chọn): `nitrogen`, `pest_cycle`, `yield` có dữ liệu; `water`, `erosion`, `income`, `soil` chưa có dữ liệu và được khai báo là chưa hỗ trợ.

## Bốn mẫu
| id | Ý nghĩa |
|---|---|
| `keep` | Giữ cây hiện tại ở mọi vụ (luôn đứng đầu danh sách) |
| `legume` | Thay 1 vụ bằng cây họ đậu có điểm GAEZ cao nhất vừa năm (bỏ qua nếu cây hiện tại đã là họ đậu) |
| `other_family` | Thay 1 vụ bằng cây khác họ, không phải họ đậu, điểm GAEZ cao nhất vừa năm |
| `diverse` | Thay n-1 vụ (n nếu chỉ 2 vụ): mọi cây khác họ nhau, có cây họ đậu nếu có thể, điểm GAEZ tốt nhất |

Mẫu nào không có cây thỏa điều kiện thì không xuất hiện và được ghi trong `skipped` kèm lý do. Đề thi cần ít nhất 3 phương án gồm hiện tại.

## Điều kiện để một cây được thay vào
- Cây một năm và có `cycle_days_min` trong dữ liệu.
- Chỉ số GAEZ của ô ≥ `min_index` (mặc định 4000). Nếu chính cây hiện tại thấp hơn ngưỡng thì kết quả có cảnh báo, và các phương án thay thế vẫn chỉ gồm cây từ ngưỡng trở lên.
- Ruộng cạn không nhận cây ngập (lúa nước, khoai sọ ruộng nước). Ruộng ngập nhận cây cạn nhưng kèm rủi ro "cần thoát nước".
- Cả chuỗi vừa 365 ngày: tổng `cycle_days_min` cộng khoảng nghỉ sau mỗi vụ (kể cả từ vụ cuối sang vụ đầu của năm sau): `gap_rice` nếu hai vụ liền nhau đều là lúa nước, ngược lại `gap_other`.

## Mỗi phương án trả về
`components` (điểm GAEZ trung bình, số cặp vụ liên tiếp cùng họ theo vòng, có họ đậu, họ, tổng ngày, **`slack_days`** số ngày còn dư trong năm, vừa năm), `benefits`, `risks`, `evidence` (từng cây: chỉ số GAEZ và **nhãn lớp FAO** rất phù hợp / phù hợp / trung bình / biên / rất biên, độ dài vụ, họ, họ đậu, chế độ nước) và `evidence_source`. Không có điểm tổng: một điểm tổng chỉ nhắc lại trọng số tự chọn, không phải bằng chứng.

## Giới hạn phải nói rõ với người dùng
- **Thứ tự các vụ không được xếp lịch.** GAEZ chỉ cho ngày gieo tối ưu của từng cây đứng riêng, không cho cây đứng sau cây khác, và giá trị nhiễu giữa các ô kề nhau. `sequence` chỉ là liệt kê chuẩn (cây giữ lại trước, rồi cây thay thế theo điểm GAEZ).
- **Độ dài vụ lấy giống ngắn nhất** mà GAEZ thử (lúa 105 ngày). Vụ thực tế có thể dài hơn.
- **Chế độ nước** của mọi cây ngoài lúa và taro là mặc định của dự án, GAEZ không phân biệt.
- **Chưa có:** giá nông sản, độ phủ đất và xói mòn, đất, thiếu nước theo cây, thời gian chuyển vụ thực tế.
- Chỉ số GAEZ là tiềm năng (0–10000), không phải năng suất thực tế.
