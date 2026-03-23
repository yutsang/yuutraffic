"""
MTR Bus route metadata: approximate map line endpoints (WGS84) and district labels.

Sources: MTR Bus API spec (routeName list), corridor geography in NW NT / Tai Po / Lantau.
Coordinates are for linear interpolation between first/last stop only — not survey-grade.
"""

from __future__ import annotations

# --- Shared corridor segments (lat, lng) ---
# Tai Po (feeder K12–K18): Tai Po Market / Tai Wo ↔ industrial / residential north-east
_TAI_PO: tuple[tuple[float, float], tuple[float, float]] = (
    (22.4440, 114.1688),
    (22.4495, 114.1765),
)

# Tuen Mun town / LR core
_TUEN_MUN: tuple[tuple[float, float], tuple[float, float]] = (
    (22.3920, 113.9725),
    (22.3985, 113.9820),
)

# Tuen Mun Ferry / west coast ↔ town (506, K52 Lung Kwu Tan corridor)
_TUEN_MUN_W: tuple[tuple[float, float], tuple[float, float]] = (
    (22.3720, 113.9660),
    (22.3955, 113.9785),
)

# Tuen Mun South / Butterfly / Siu Shan (K40 series, some feeders)
_TUEN_MUN_S: tuple[tuple[float, float], tuple[float, float]] = (
    (22.3825, 113.9780),
    (22.3960, 113.9845),
)

# Yuen Long town ↔ Long Ping / West corridors
_YUEN_LONG: tuple[tuple[float, float], tuple[float, float]] = (
    (22.4445, 114.0225),
    (22.4520, 114.0340),
)

# Yuen Long ↔ Lau Fau Shan
_LAU_FAU_SHAN: tuple[tuple[float, float], tuple[float, float]] = (
    (22.4455, 114.0230),
    (22.4280, 113.9840),
)

# Long Ping ↔ Tai Tong (K66 family)
_TAI_TONG: tuple[tuple[float, float], tuple[float, float]] = (
    (22.4490, 114.0220),
    (22.4285, 114.0380),
)

# Tin Shui Wai Station ↔ north (Tin Heng) — K76-style
_TSW_N: tuple[tuple[float, float], tuple[float, float]] = (
    (22.4478, 114.0045),
    (22.4683, 114.0017),
)

# Tin Heng ↔ Yuen Long West (K73)
_TSW_YLW: tuple[tuple[float, float], tuple[float, float]] = (
    (22.4683, 114.0017),
    (22.4460, 114.0220),
)

# Tin Shui Wai town centre / LR loop (705/706/720/751)
_LRT_TSW: tuple[tuple[float, float], tuple[float, float]] = (
    (22.4555, 114.0005),
    (22.4645, 114.0145),
)

# Light Rail Tuen Mun loop / Siu Hong–style (506/507/610/614/615)
_LRT_TM: tuple[tuple[float, float], tuple[float, float]] = (
    (22.4560, 114.0045),
    (22.4625, 114.0125),
)

# Long Tuen Mun Ferry–style trunk (506 Tuen Mun Ferry → Siu Lun)
_TM_FERRY_LR: tuple[tuple[float, float], tuple[float, float]] = (
    (22.3720, 113.9660),
    (22.4650, 114.0060),
)

# Airport / North Lantau / Tsing Yi (A-route approximation)
_AIRPORT: tuple[tuple[float, float], tuple[float, float]] = (
    (22.3580, 114.1080),
    (22.3080, 113.9150),
)

# Airport express-style NT west (Tuen Mun ↔ HZMB / Lantau) — A33X, A36, etc.
_AIRPORT_NT: tuple[tuple[float, float], tuple[float, float]] = (
    (22.3950, 113.9750),
    (22.3180, 113.9480),
)

# Every route in data_updater.MTR_BUS_ROUTE_CANDIDATES must appear here.
MTR_ROUTE_LINES: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    # Tai Po feeders (spec: Tai Po Market / Mega Mall / Fu Shin / Kwong Fuk)
    "K12": _TAI_PO,
    "K14": _TAI_PO,
    "K17": _TAI_PO,
    "K18": _TAI_PO,
    # Tuen Mun area
    "K40": _TUEN_MUN_S,
    "K41": _TUEN_MUN_S,
    "K45": _TUEN_MUN,
    "K45A": _TUEN_MUN,
    "K48": _TUEN_MUN,
    "K50": _TUEN_MUN,
    "K51": _TUEN_MUN,
    "K52": _TUEN_MUN_W,
    "K53": _TUEN_MUN,
    "K54": _TUEN_MUN,
    "K58": _TUEN_MUN,
    "K63A": _TUEN_MUN,
    "K63B": _TUEN_MUN,
    "K64P": _TUEN_MUN,
    "K64S": _TUEN_MUN,
    "K66A": _YUEN_LONG,
    "K66S": _YUEN_LONG,
    "K67": _YUEN_LONG,
    # Yuen Long / Lau Fau Shan / Long Ping
    "K65": _LAU_FAU_SHAN,
    "K66": _TAI_TONG,
    "K68": _YUEN_LONG,
    # Tin Shui Wai / Yuen Long West
    "K71": _TSW_N,
    "K72": _TSW_N,
    "K73": _TSW_YLW,
    "K74": _LRT_TSW,
    "K75": _TSW_N,
    "K76": _TSW_N,
    # Light Rail Tuen Mun
    "506": _TM_FERRY_LR,
    "506A": _LRT_TM,
    "507": _LRT_TM,
    "507P": _LRT_TM,
    "610": _LRT_TM,
    "614": _LRT_TM,
    "614P": _LRT_TM,
    "615": _LRT_TM,
    "615P": _LRT_TM,
    # Light Rail Tin Shui Wai
    "705": _LRT_TSW,
    "706": _LRT_TSW,
    "720": _LRT_TSW,
    "720M": _LRT_TSW,
    "751": _LRT_TSW,
    "751P": _LRT_TSW,
    # Airport buses (approximate; corridor varies by route)
    "A30": _AIRPORT_NT,
    "A31": _AIRPORT,
    "A32": _AIRPORT,
    "A33": _AIRPORT_NT,
    "A33X": _AIRPORT_NT,
    "A34": _AIRPORT_NT,
    "A36": _AIRPORT_NT,
    "A37": _AIRPORT_NT,
    "A38": _AIRPORT,
    "A41": _AIRPORT_NT,
    "A41P": _AIRPORT_NT,
    "A42": _AIRPORT_NT,
    "A43": _AIRPORT_NT,
    "A43P": _AIRPORT_NT,
    "A46": _AIRPORT,
    "A47X": _AIRPORT_NT,
}

# District hint when no per-stop override exists: (English, Traditional Chinese)
MTR_ROUTE_REGION: dict[str, tuple[str, str]] = {
    "K12": ("Tai Po", "大埔"),
    "K14": ("Tai Po", "大埔"),
    "K17": ("Tai Po", "大埔"),
    "K18": ("Tai Po", "大埔"),
    "K40": ("Tuen Mun South", "屯門南"),
    "K41": ("Tuen Mun South", "屯門南"),
    "K45": ("Tuen Mun", "屯門"),
    "K45A": ("Tuen Mun", "屯門"),
    "K48": ("Tuen Mun", "屯門"),
    "K50": ("Tuen Mun", "屯門"),
    "K51": ("Tuen Mun", "屯門"),
    "K52": ("Tuen Mun / Lung Kwu Tan", "屯門／龍鼓灘"),
    "K53": ("Tuen Mun", "屯門"),
    "K54": ("Tuen Mun", "屯門"),
    "K58": ("Tuen Mun", "屯門"),
    "K63A": ("Tuen Mun", "屯門"),
    "K63B": ("Tuen Mun", "屯門"),
    "K64P": ("Tuen Mun", "屯門"),
    "K64S": ("Tuen Mun", "屯門"),
    "K65": ("Yuen Long / Lau Fau Shan", "元朗／流浮山"),
    "K66": ("Yuen Long / Tai Tong", "元朗／大棠"),
    "K66A": ("Yuen Long", "元朗"),
    "K66S": ("Yuen Long", "元朗"),
    "K67": ("Yuen Long", "元朗"),
    "K68": ("Yuen Long", "元朗"),
    "K71": ("Tin Shui Wai", "天水圍"),
    "K72": ("Tin Shui Wai", "天水圍"),
    "K73": ("Tin Shui Wai / Yuen Long", "天水圍／元朗"),
    "K74": ("Tin Shui Wai", "天水圍"),
    "K75": ("Tin Shui Wai", "天水圍"),
    "K76": ("Tin Shui Wai", "天水圍"),
    "506": ("Tuen Mun (Light Rail)", "屯門（輕鐵）"),
    "506A": ("Tuen Mun (Light Rail)", "屯門（輕鐵）"),
    "507": ("Tuen Mun (Light Rail)", "屯門（輕鐵）"),
    "507P": ("Tuen Mun (Light Rail)", "屯門（輕鐵）"),
    "610": ("Tuen Mun (Light Rail)", "屯門（輕鐵）"),
    "614": ("Tuen Mun (Light Rail)", "屯門（輕鐵）"),
    "614P": ("Tuen Mun (Light Rail)", "屯門（輕鐵）"),
    "615": ("Tuen Mun (Light Rail)", "屯門（輕鐵）"),
    "615P": ("Tuen Mun (Light Rail)", "屯門（輕鐵）"),
    "705": ("Tin Shui Wai (Light Rail)", "天水圍（輕鐵）"),
    "706": ("Tin Shui Wai (Light Rail)", "天水圍（輕鐵）"),
    "720": ("Tin Shui Wai (Light Rail)", "天水圍（輕鐵）"),
    "720M": ("Tin Shui Wai (Light Rail)", "天水圍（輕鐵）"),
    "751": ("Tin Shui Wai (Light Rail)", "天水圍（輕鐵）"),
    "751P": ("Tin Shui Wai (Light Rail)", "天水圍（輕鐵）"),
    "A30": ("Airport / Lantau", "機場／大嶼山"),
    "A31": ("Airport / Lantau", "機場／大嶼山"),
    "A32": ("Airport / Lantau", "機場／大嶼山"),
    "A33": ("Airport / NT West", "機場／新界西"),
    "A33X": ("Airport / NT West", "機場／新界西"),
    "A34": ("Airport / NT West", "機場／新界西"),
    "A36": ("Airport / NT West", "機場／新界西"),
    "A37": ("Airport / NT West", "機場／新界西"),
    "A38": ("Airport / Lantau", "機場／大嶼山"),
    "A41": ("Airport / NT West", "機場／新界西"),
    "A41P": ("Airport / NT West", "機場／新界西"),
    "A42": ("Airport / NT West", "機場／新界西"),
    "A43": ("Airport / NT West", "機場／新界西"),
    "A43P": ("Airport / NT West", "機場／新界西"),
    "A46": ("Airport / Lantau", "機場／大嶼山"),
    "A47X": ("Airport / NT West", "機場／新界西"),
}
