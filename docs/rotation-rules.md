# Quy tắc sinh phương án luân canh (DATA-02)

Mã: `pipeline/src/rotation/options.py`; thử bằng `python rotation_options.py --lat 10.45 --lon 105.35 --crop RCW` (từ `pipeline/`). Đây là công cụ **hỗ trợ**, không phải lịch gieo hay dự báo năng suất từng ruộng.

## Đầu vào
- Vị trí: ô lưới GAEZ gần nhất trong 0,1° (`gaez_grid`); xa hơn thì không trả lời.
- Cây hiện tại (một trong các cây một năm của `dim_crop`) và mức đầu vào GAEZ (`hilm/hrlm/lilm/lrlm`, mặc định nước trời + đầu vào cao).
- Số vụ trong năm: mặc định là số vụ cây hiện tại vừa trong 365 ngày (tối đa 3), có thể ghi đè.
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
- Điểm GAEZ của ô > 0 và ≥ 60% điểm của cây hiện tại (`MIN_RATIO`, ngưỡng của dự án, **chưa có cơ sở khoa học**).
- Ruộng cạn không nhận cây ngập (lúa nước, khoai sọ ruộng nước). Ruộng ngập nhận cây cạn nhưng kèm rủi ro "cần thoát nước".
- Cả chuỗi vừa 365 ngày: tổng `cycle_days_min` cộng 15 ngày chuyển vụ mỗi vụ (`BUFFER_DAYS`, giả định của dự án).

## Mỗi phương án trả về
`components` (điểm GAEZ trung bình, số cặp vụ liên tiếp cùng họ theo vòng, có họ đậu, họ, tổng ngày, vừa năm), `benefits`, `risks`, `evidence` (từng cây: chỉ số GAEZ, độ dài vụ, họ, họ đậu, chế độ nước) và `evidence_source`. Không có điểm tổng: một điểm tổng chỉ nhắc lại trọng số tự chọn, không phải bằng chứng.

## Giới hạn phải nói rõ với người dùng
- **Thứ tự các vụ không được xếp lịch.** GAEZ chỉ cho ngày gieo tối ưu của từng cây đứng riêng, không cho cây đứng sau cây khác, và giá trị nhiễu giữa các ô kề nhau. `sequence` chỉ là liệt kê chuẩn (cây giữ lại trước, rồi cây thay thế theo điểm GAEZ).
- **Độ dài vụ lấy giống ngắn nhất** mà GAEZ thử (lúa 105 ngày). Vụ thực tế có thể dài hơn.
- **Chế độ nước** của mọi cây ngoài lúa và taro là mặc định của dự án, GAEZ không phân biệt.
- **Chưa có:** giá nông sản, độ phủ đất và xói mòn, đất, thiếu nước theo cây, thời gian chuyển vụ thực tế.
- Chỉ số GAEZ là tiềm năng (0–10000), không phải năng suất thực tế.
