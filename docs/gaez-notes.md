# Ghi chú GAEZ v5 (đã kiểm tra 10–14/11/2026)

## Lớp dùng
- **`RES05-SXX30AS`**: chỉ số thích hợp cây trồng liên tục, **0–10000** (cao = hợp hơn), ~0,9 km, kiểu int16, **nodata = -9**. Đã đối chiếu: giá trị đọc từ file khớp với con số cổng GAEZ tại nhiều điểm.
- Không dùng `RES05-SIX` (~9 km, 9 hạng): là sản phẩm khác.
- Giai đoạn `HP0120` (2001–2020), khí hậu `AGERA5`, kịch bản `HIST`. Giai đoạn `HP8100` là 1981–2000; tương lai `FP2140`…`FP8100` (tên file cần kiểm tra).
- Nguồn: `https://storage.googleapis.com/fao-gismgr-gaez-v5-data/DATA/GAEZ-V5/MAPSET/RES05-SXX30AS/GAEZ-V5.RES05-SXX30AS.<PERIOD>.<CLIM>.<SSP>.<CROP>.<MODE>.tif`
- Mỗi file toàn cầu ~150 MB, nhưng là GeoTIFF dạng tile: **đọc cửa sổ qua mạng** (rasterio) lấy vùng nhỏ chỉ mất vài giây.

## Mức (mode)
`HILM` tưới + đầu vào cao · `HRLM` mưa + cao · `LILM` tưới + thấp · `LRLM` mưa + thấp. Mức đầu vào ảnh hưởng rất lớn (ví dụ một điểm lúa nước ĐBSCL: 1.940 ở `LRLM`, 8.634 ở `HRLM`).

## Mã cây (bucket 3 chữ, KHÁC mã Excel 4 chữ)
Đã đối chiếu với cổng bằng cách bấm điểm, mức `HRLM`:

| Mã | Cây | Mã | Cây |
|---|---|---|---|
| RCW | Lúa nước | COF | Cà phê |
| RCD | Lúa cạn | RUB | Cao su |
| MZE | Ngô | TEA | Chè |
| CSV | Sắn | CSH | Điều |
| SPO | Khoai lang | **CON** | Dừa (COC là loại phụ) |
| WPO | Khoai tây | OLP | Cọ dầu |
| TAROW | Khoai sọ ruộng nước | SUC | Mía (khớp số; tên chưa xác nhận chính thức) |
| SOY | Đậu tương | BAN | Chuối |
| GRD | Lạc | CIT | Cây có múi |
| COW | Đậu đũa | CAB | Bắp cải |
| SES | Vừng | TOM | Cà chua |
| ONI | Hành | WMEL | Dưa hấu |

Iowa (Mỹ): WHE lúa mì, ALF linh lăng, OAT yến mạch, SRG cao lương chưa đối chiếu với cổng (chọn theo tên).

## Lưu ý khi dùng
- Chỉ số là mức thích hợp **tiềm năng**, trung bình 20 năm, không phải từng năm.
- Giá trị nhảy giữa pixel kề nhau (đã thấy bắp cải 449 và 304 ở hai pixel cạnh nhau): nên lấy **trung bình vùng nhỏ** quanh vị trí.
- Nhiều cây có thể trùng giá trị tại một điểm (do chỉ số tính từ tỉ lệ các hạng): đừng nhận diện cây bằng một con số.
- Mô hình có thể lệch thực tế (ví dụ cà phê ở khu vực Buôn Ma Thuột ra thấp): cần nêu rõ trong phần giới hạn.
- Trích dẫn: FAO & IIASA. 2025. Global Agro-ecological Zoning version 5 (GAEZ v5) Model Documentation. Giấy phép dữ liệu theo danh mục FAO: CC BY 4.0.
