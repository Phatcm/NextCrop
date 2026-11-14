"""English display names of the 24 GAEZ crops in dim_crop (the Vietnamese names live in the database).

Kept next to the generator so the API, the command line and the tests share one list. The names follow the GAEZ v5
crop captions in plain English; `tests/test_rotation_en.py` fails if a crop in crop_traits.csv has no entry here.
"""
from __future__ import annotations

NAMES_EN: dict[str, str] = {
    "RCW": "Wetland rice", "RCD": "Dryland rice", "MZE": "Maize", "CSV": "Cassava", "SPO": "Sweet potato",
    "WPO": "White potato", "TAROW": "Wetland taro", "SOY": "Soybean", "GRD": "Groundnut", "COW": "Cowpea",
    "SES": "Sesame", "ONI": "Onion", "COF": "Coffee", "RUB": "Rubber", "TEA": "Tea", "CSH": "Cashew",
    "CON": "Coconut", "OLP": "Oil palm", "SUC": "Sugarcane", "BAN": "Banana", "CIT": "Citrus", "CAB": "Cabbage",
    "TOM": "Tomato", "WMEL": "Watermelon",
}
