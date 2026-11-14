# Hợp đồng dữ liệu giữa pipeline và app (NHÁP, cần Phat và Hùng chốt)

App chỉ đọc file tĩnh trên Cloudflare R2. Gợi ý để hai bên làm song song:

```
<R2 public base>/index.json                     danh sách vị trí và phiên bản dữ liệu
<R2 public base>/locations/<id>.json            dữ liệu một vị trí
<R2 public base>/suitability/<region>.json      (tùy chọn) bảng thích hợp theo cây x mức cho vùng
```

`locations/<id>.json` (đề xuất, chưa cố định):
```json
{
  "id": "thai-binh",
  "name": "Thái Bình",
  "lat": 20.45, "lon": 106.30,
  "climate": {
    "source": "NASA POWER",
    "monthly": { "T2M": [], "PRECTOTCORR": [], "GWETROOT": [] },
    "units": { "T2M": "C", "PRECTOTCORR": "mm/day", "GWETROOT": "1" }
  },
  "ndvi": [
    { "date": "2023-04-23", "value": 0.70, "flag_bad": false, "source": "observed" }
  ],
  "suitability": {
    "source": "FAO GAEZ v5 RES05-SXX30AS, 2001-2020",
    "values": { "RCW": { "HILM": 0, "HRLM": 0, "LILM": 0, "LRLM": 0 } },
    "note": "0-10000, cao = hợp hơn; mức đầu vào ảnh hưởng mạnh"
  },
  "meta": { "generated_at": "", "pipeline_version": "" }
}
```

Điều cần chốt: danh sách vị trí hero, đơn vị thời gian của khí hậu (tháng hay ngày), cách tính giá trị thích hợp (một pixel hay trung bình vùng nhỏ), cách đánh dấu ngày NDVI hỏng, tên bucket R2 và đường dẫn công khai.
