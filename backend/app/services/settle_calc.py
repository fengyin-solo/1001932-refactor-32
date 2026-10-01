"""电量结算金额与结算周期的共用口径。

列表页、详情页、导出清单三个入口都只允许通过本模块取数，避免同一单据
在不同入口各算一遍、改一处另外两处跟着漂。

当前金额口径（AMOUNT_VERSION = "v2"）：
    结算金额 = 上网电量 × 结算电价，按分四舍五入，补贴金额不计入。

已经「确认结清」（核对过）的单据不再跟随口径变化：结清瞬间把当时取值
固化到「锁定结算金额」里，之后无论口径怎么调、电量电价怎么传，列表、
详情、导出都按固化值展示。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

# 金额口径版本：调整计算方式时升版，未结清的历史单据会按新版本重算。
AMOUNT_VERSION = "v2"

QUANT = Decimal("0.01")

# 结算列表的展示列顺序；导出清单按同一列序取数，保证和列表对得上。
AMOUNT_FIELDS = ["结算单号", "结算周期", "结算周期天数", "所属场站", "上网电量", "结算电价", "补贴金额", "结算金额", "结算状态"]

# 已结清核对过的单据用这些内部字段固化当初取值（不参与对外列序）。
LOCKED_AMOUNT_KEY = "锁定结算金额"
LOCKED_VERSION_KEY = "锁定金额口径版本"

# 形如 2026-09、2026-09-01、2026/9/1 的日期段；其余写法（自然语言等）无法解析。
_PERIOD_TOKEN = r"(\d{4})\s*[-/年.]\s*(\d{1,2})(?:\s*[-/月.]\s*(\d{1,2}))?\s*日?"


def _to_decimal(value: Any) -> Decimal | None:
    """把「1234.5」「1,234.50」「820 万 kWh」这类取值解析成 Decimal。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    text = str(value).strip()
    if not text:
        return None
    # 去掉千分位逗号与单位后缀里的空白，取第一段数字。
    cleaned = text.replace(",", "").replace("，", "")
    token = ""
    for ch in cleaned:
        if ch.isdigit() or ch in ".-":
            token += ch
        elif token:
            break
    if not token or token in {"-", ".", "-."}:
        return None
    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def calc_amount(energy: Any, price: Any) -> Decimal | None:
    """按当前口径计算结算金额：上网电量 × 结算电价，四舍五入到分。"""
    energy_decimal = _to_decimal(energy)
    price_decimal = _to_decimal(price)
    if energy_decimal is None or price_decimal is None:
        return None
    return (energy_decimal * price_decimal).quantize(QUANT, rounding=ROUND_HALF_UP)


def settle_period(raw_period: Any) -> tuple[str, int | None]:
    """把各种结算周期写法归一成「YYYY-MM」，并给出周期天数。

    单写月份按整月计；写清起止的按起止日（含首尾）计；解析不出时原样返回、
    天数留空。三个入口的周期展示都以这里的结果为准。
    """
    import re

    text = str(raw_period or "").strip()
    if not text:
        return "", None

    tokens = [
        (int(year), int(month), int(day) if day else None)
        for year, month, day in re.findall(_PERIOD_TOKEN, text)
    ]
    if not tokens:
        return text, None

    def normalize(token: tuple[int, int, int | None]) -> tuple[int, int, int | None]:
        year, month, day = token
        if not 1 <= month <= 12:
            return token
        if day is not None and not 1 <= day <= 31:
            day = None
        return year, month, day

    start = normalize(tokens[0])
    end = normalize(tokens[-1]) if len(tokens) > 1 else None

    if end is None:
        year, month, day = start
        canonical = f"{year:04d}-{month:02d}"
        if day is not None:
            # 写的是某一天，周期就按一天算，标签保留到日。
            return f"{year:04d}-{month:02d}-{day:02d}", 1
        if not 1 <= month <= 12:
            return text, None
        import calendar

        return canonical, calendar.monthrange(year, month)[1]

    from datetime import date

    def as_date(token: tuple[int, int, int | None], *, last_day: bool) -> date | None:
        year, month, day = token
        if not 1 <= month <= 12:
            return None
        if day is None:
            import calendar

            day = calendar.monthrange(year, month)[1] if last_day else 1
        if not 1 <= day <= 31:
            return None
        try:
            return date(year, month, day)
        except ValueError:
            return None

    start_date = as_date(start, last_day=False)
    end_date = as_date(end, last_day=True)
    if start_date is None or end_date is None:
        return text, None
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    days = (end_date - start_date).days + 1
    start_label = start_date.strftime("%Y-%m")
    end_label = end_date.strftime("%Y-%m")
    canonical = start_label if start_label == end_label else f"{start_label}~{end_label}"
    return canonical, days


def is_locked(entry: dict[str, Any]) -> bool:
    """已核对固化过金额的单据（确认结清）。"""
    return LOCKED_AMOUNT_KEY in entry


def _decimal_to_number(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def apply_caliber(entry: dict[str, Any]) -> dict[str, Any]:
    """把共用口径落到一条单据上，返回同一条记录（就地补算展示字段）。

    - 已固化（核对过）的单据：结算金额永远取锁定值，口径变化不影响它；
    - 其余单据：结算金额按当前口径重算，保证口径调整后旧单跟着新口径走；
    - 结算周期统一走 settle_period 归一。
    """
    canonical_period, period_days = settle_period(entry.get("结算周期"))
    entry["结算周期"] = canonical_period
    entry["结算周期天数"] = period_days

    if entry.get("结算状态") is None:
        entry["结算状态"] = entry.get("status")

    if is_locked(entry):
        locked = _to_decimal(entry[LOCKED_AMOUNT_KEY])
        entry["结算金额"] = _decimal_to_number(locked)
    else:
        amount = calc_amount(entry.get("上网电量"), entry.get("结算电价"))
        entry["结算金额"] = _decimal_to_number(amount)

    subsidy = _to_decimal(entry.get("补贴金额"))
    if subsidy is not None:
        entry["补贴金额"] = float(subsidy.quantize(QUANT, rounding=ROUND_HALF_UP))

    entry["金额口径版本"] = entry.get(LOCKED_VERSION_KEY) if is_locked(entry) else AMOUNT_VERSION
    return entry


def freeze_checked_amount(entry: dict[str, Any]) -> dict[str, Any]:
    """确认结清时调用：把当前核对的结算金额固化下来，以后不再随口径变化。"""
    if not is_locked(entry):
        # 先按当前口径算一遍，以列表页那份取值为准固化，保证
        # 「三个入口对不上时以结算列表为准」。
        apply_caliber(entry)
        current = _to_decimal(entry.get("结算金额"))
        if current is None:
            current = Decimal("0")
        entry[LOCKED_AMOUNT_KEY] = float(current.quantize(QUANT, rounding=ROUND_HALF_UP))
        entry[LOCKED_VERSION_KEY] = AMOUNT_VERSION
    return apply_caliber(entry)


def export_rows(entries: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    """导出清单专用取数：列序与取值都来自同一份口径结果。

    任何一行在导出文件里的金额，都和它在结算列表里的展示值逐位相同。
    """
    def cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    lines = [[cell(entry.get(field)) for field in AMOUNT_FIELDS] for entry in entries]
    return list(AMOUNT_FIELDS), lines


def recalc_existing(entries: list[dict[str, Any]]) -> None:
    """口径调整后的迁移：未核对的单据按新口径重算；早先核对过的单据
    （已结清）把当初的取值补固化，金额保持不变。
    """
    for entry in entries:
        if entry.get("status") == "已结清" and not is_locked(entry):
            stored = _to_decimal(entry.get("结算金额"))
            if stored is None:
                stored = calc_amount(entry.get("上网电量"), entry.get("结算电价")) or Decimal("0")
            entry[LOCKED_AMOUNT_KEY] = float(stored.quantize(QUANT, rounding=ROUND_HALF_UP))
            entry[LOCKED_VERSION_KEY] = entry.get("金额口径版本", "v1")
        apply_caliber(entry)
