# NextCrop: hỗ trợ ra quyết định luân canh cho Việt Nam

**NASA Space Apps Challenge 2026, đề "Field Shift: Adapting Farms with NASA Data".**
Sản phẩm của đội **NextCrop** · sự kiện địa phương TP. Hồ Chí Minh, 14–15/11/2026 · [Video demo (≤30 giây)](https://drive.google.com/file/d/1EJ7CVDyAiW8Od_vqXjTzXIZxEunJ27KZ/view?usp=sharing)

> **English: [README.md](README.md).**

Người dùng chọn một nơi ở Việt Nam và cây đang trồng ở đó. NextCrop so sánh **ít nhất ba phương án luân canh, luôn gồm "giữ nguyên cây hiện tại"**, và nói bằng lời dễ hiểu vì sao, lợi ích và rủi ro là gì, điều gì còn chưa biết, và mỗi phương án đánh đổi thế nào so với cách nông hộ đang làm. Đây là công cụ **hỗ trợ tư vấn**: nó hỗ trợ, không thay thế phán đoán của nông dân và cán bộ khuyến nông địa phương.

> Giao diện có **tiếng Việt và tiếng Anh** (nút VI | EN ở đầu trang). Phần lớn ghi chú kỹ thuật trong `docs/` bằng tiếng Việt vì đó là ngôn ngữ làm việc của đội.

## Có thể làm gì
- Bấm vào bất kỳ chỗ nào trên bản đồ (hoặc chọn tỉnh) và chọn cây. Bản đồ tô màu từng ô ~9 km theo mức phù hợp với cây đó.
- Xem 3–4 phương án luân canh cho ô đã chọn, mỗi phương án có lợi ích, rủi ro, mức đánh đổi so với "giữ nguyên" và các giả định. Có thể đổi số vụ, số ngày nghỉ giữa các vụ và ưu tiên.
- Mở tab **NASA** để xem khí hậu từng tháng của nơi đó: nhiệt độ (NASA POWER) và, quanh sáu vùng demo, độ xanh thực vật (NASA MODIS NDVI) bên cạnh lượng mưa (CHIRPS).
- Ở sáu vùng demo, mỗi phương án còn có nhãn **kiểm tra độ ẩm**: phương án có nằm trọn trong mùa đủ ẩm nhờ mưa của vùng không? (mưa CHIRPS so với bốc thoát hơi nước tham chiếu tính từ NASA POWER theo FAO-56.)

## Dữ liệu NASA được dùng thế nào (và cái gì không phải NASA)
| Dữ liệu | Nguồn | Xuất hiện ở đâu |
|---|---|---|
| Thời tiết theo ngày 2015–2025: nhiệt độ, độ ẩm, gió, bức xạ | **NASA POWER** | Biểu đồ nhiệt độ (cả nước); ET0 (FAO-56 Penman-Monteith) cho sáu vùng demo, dùng cho nhãn kiểm tra độ ẩm |
| NDVI và cờ chất lượng | **NASA MODIS MOD13Q1** (qua AppEEARS) | Biểu đồ NDVI ở các vùng demo. Chỉ dùng các lần đo thật đã qua kiểm tra chất lượng; số nội suy không bao giờ được hiện như số đo |
| Độ ẩm đất, lớp phủ đất, độ cao, mặt nạ đất canh tác | **NASA SMAP, MCD12Q1, NASADEM, GFSAD30** | Pipeline xử lý và nạp vào cơ sở dữ liệu; chưa hiện trên giao diện |
| Chỉ số độ phù hợp của cây (0–10000) | **FAO GAEZ v5** (không phải NASA) | Màu trên bản đồ và thứ tự xếp hạng các phương án |
| Lượng mưa | **CHIRPS v3** (không phải NASA) | Cột mưa và nhãn kiểm tra độ ẩm; mưa của NASA POWER từng lệch tới 2,3 lần so với CHIRPS ở một vùng nên không dùng |

**Tóm tắt trung thực:** *thứ tự* các phương án luân canh dựa trên chỉ số phù hợp FAO GAEZ cộng các luật rõ ràng (họ cây, cây họ đậu, độ dài vụ). Dữ liệu NASA nuôi phần bối cảnh khí hậu, các biểu đồ NDVI, mưa, nhiệt độ và nhãn kiểm tra độ ẩm; nó không đổi thứ tự các phương án. Xem [docs/LIMITATIONS.md](docs/LIMITATIONS.md) (bằng tiếng Anh).

## Tự chạy
App đọc một cơ sở dữ liệu PostgreSQL do pipeline nạp. Bản demo trực tuyến dùng cơ sở dữ liệu riêng của đội, **không** nằm trong repo này, nên để chạy app bạn cần tự nạp một bản bằng pipeline (xem [pipeline/README.md](pipeline/README.md); cần tài khoản NASA Earthdata miễn phí để lấy dữ liệu AppEEARS).

```bash
# 1. API và giao diện web (API phục vụ luôn giao diện ở "/")
cd app/api
pip install -r requirements.txt
export APP_DATABASE_URL="postgresql://user:password@host:5432/db?sslmode=require"   # chỉ cần quyền đọc
uvicorn fieldshift_api.main:app --port 8000        # giao diện: http://localhost:8000/   tài liệu API: /docs

# 2. Test (không cần database, trừ các test Postgres do CI chạy)
cd app/api && pytest
cd app/web && node --test                           # Node 20 trở lên, không cần cài gói
cd pipeline && pytest
```
Chi tiết hơn: [app/README.md](app/README.md), [app/api/README.md](app/api/README.md).

## Cấu trúc repo
```
app/api/      backend FastAPI, chỉ đọc (mỗi yêu cầu chạy trong giao dịch READ ONLY)
app/web/      giao diện: HTML/CSS/JavaScript thuần (không cần build), MapLibre GL cho bản đồ, biểu đồ SVG tự viết
pipeline/     lấy, làm sạch, kiểm tra và đóng gói dữ liệu; nạp vào PostgreSQL (và data lake)
docs/         hợp đồng dữ liệu, luật luân canh, kiểm toán dữ liệu và các vấn đề đã biết (phần lớn tiếng Việt)
.github/      CI: chạy test API, web và pipeline ở mỗi pull request
```

## Tài liệu
- [docs/rotation-rules.md](docs/rotation-rules.md): cách sinh phương án, các con số nghĩa là gì, cái gì chỉnh được.
- [docs/data-contract.md](docs/data-contract.md): các bảng giữa pipeline và app.
- [docs/data-issues.md](docs/data-issues.md), [docs/data-audit.md](docs/data-audit.md), [docs/system-audit.md](docs/system-audit.md): chất lượng dữ liệu, vấn đề đã biết và kiểm toán.
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md): những điều công cụ này **không** làm (tiếng Anh).
- [docs/AI_USAGE.md](docs/AI_USAGE.md): khai báo công cụ AI đã dùng (tiếng Anh).

## Giới hạn trong một đoạn
Một ô (~80–85 km²) chỉ cho một đáp án, nên kết quả **không** dùng cho từng thửa ruộng. Chỉ số phù hợp là *tiềm năng*, không phải năng suất hay lợi nhuận. Mưa và NDVI chỉ có ở sáu vùng demo (mỗi vùng rộng khoảng 10 km; trong sáu vị trí, năm vị trí còn là tọa độ ước lượng, xem cấu hình pipeline). Ranh giới tỉnh trên bản đồ là năm 2008, không theo đợt sáp nhập 2025. Không có gì ở đây là dự báo. Chi tiết trong [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Ghi công dữ liệu
- FAO & IIASA. 2025. Global Agro-ecological Zoning version 5 (GAEZ v5) Model Documentation (CC BY 4.0).
- NASA POWER, MODIS (MOD13Q1, MCD12Q1), SMAP, NASADEM, GFSAD30: dữ liệu mở của NASA.
- CHIRPS v3 (Climate Hazards Center, Đại học California Santa Barbara).
- Ranh giới tỉnh: geoBoundaries (gbOpen, ADM1, Việt Nam, bản đã đơn giản hóa).
- Ảnh vệ tinh nền: Esri World Imagery (Esri, Maxar, Earthstar Geographics), tải từ Esri lúc chạy; điều khoản sử dụng chưa được xem xét.
- Thư viện bản đồ: MapLibre GL JS (BSD-3-Clause), tải từ CDN.

## Đội và công cụ AI
Do hai thành viên của đội NextCrop thực hiện (GitHub: `Phatcm`, `hnguyen021`). Công cụ AI đã được dùng và khai báo tại [docs/AI_USAGE.md](docs/AI_USAGE.md). Khuyến nghị chỉ mang tính tư vấn.

## Giấy phép
Mã nguồn và tài liệu trong repo này theo [giấy phép MIT](LICENSE). Dữ liệu và tài liệu bên thứ ba giữ điều khoản riêng: FAO GAEZ v5 (CC BY 4.0), dữ liệu mở NASA, CHIRPS, geoBoundaries, ảnh Esri và MapLibre, xem "Ghi công dữ liệu" ở trên.
