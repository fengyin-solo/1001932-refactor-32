"""电量结算共用计算口径：结算金额与结算周期只允许在这里算一遍。

结算列表、结算详情、导出清单三个入口都必须调用本模块的同一份结果，
杜绝三处各写一套算法、改一个入口另外两个入口跟着漂的问题。

现行口径（``CALC_VERSION``）：
    结算金额 = 上网电量 × 结算电价 + 补贴金额，四舍五入保留到分（两位小数）；
    结算周期统一归一化成 ``YYYY-MM``。

历史单据：
    已结清的单据视为已经核对完成，金额与周期按结清当时的快照原样保留
    （``金额快照`` / ``周期快照``），口径再怎么调整都不会重算；
    未结清的单据没有历史包袱，每次读取都按现行口径重算，
    三个入口出现分歧时以结算列表重算出的结果为准。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

# 现行金额口径版本。调整算法时升版本号：未结清单据会自动按新口径重算，
# 已结清单据仍按各自快照保留，不受版本变化影响。
CALC_VERSION = "v2"

#: 已结清是结算状态流转的终态，终态单据的金额、周期一律冻结。
FINAL_STATUS = "已结清"

MONEY_QUANT = Decimal("0.01")
_PERIOD_RE = re.compile(r"(\d{4})\D+(\d{1,2})")


def to_decimal(value: Any) -> Decimal | None:
    """把接口/种子里可能是字符串或数字的取值转成 Decimal；无法识别返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def normalize_period(raw: Any) -> str | None:
    """把结算周期归一化成 ``YYYY-MM``。

    兼容 ``2026年9月``、``2026-9``、``2026/09``、``2026-9-01`` 等写法；
    无法识别为年、月时原样返回文本，避免把非标准周期改坏。
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    match = _PERIOD_RE.search(text)
    if not match:
        return text
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return text
    return f"{year:04d}-{month:02d}"


def compute_amount(quantity: Any, price: Any, subsidy: Any) -> Decimal | None:
    """现行金额口径：上网电量 × 结算电价 + 补贴金额，四舍五入到分。

    上网电量或结算电价缺失/不是数值时返回 None，由调用方决定如何展示，
    不凭空造一个金额出来。
    """
    qty = to_decimal(quantity)
    price_value = to_decimal(price)
    if qty is None or price_value is None:
        return None
    subsidy_value = to_decimal(subsidy) or Decimal("0")
    return (qty * price_value + subsidy_value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def is_finalized(row: dict[str, Any]) -> bool:
    """已结清即历史核对完成的单据，金额不允许再随口径变动。"""
    return row.get("status") == FINAL_STATUS


def _freeze(row: dict[str, Any]) -> None:
    """把单据当前的金额、周期固化成快照；已带快照的保持快照不动。"""
    if row.get("金额快照") is None:
        # 早于快照机制结清的历史单据：以库里当时那份取值当场固化，
        # 保证“以前核对过的结算金额”不被新口径覆盖。
        snapshot = to_decimal(row.get("结算金额"))
        row["金额快照"] = float(snapshot) if snapshot is not None else row.get("结算金额")
    if row.get("周期快照") is None:
        row["周期快照"] = row.get("结算周期")
    row.setdefault("口径版本", "历史口径")


def apply_caliber(row: dict[str, Any]) -> dict[str, Any]:
    """按唯一口径对齐一行数据（就地更新并返回该行）。

    * 已结清：以快照为准恢复金额与周期，不参与重算；
    * 未结清：按现行口径重算金额、归一化周期，并标记为现行版本，
      这样早先按旧口径算出的、尚未结清的单据会被统一纠正。
    """
    if is_finalized(row):
        _freeze(row)
        snapshot_amount = to_decimal(row["金额快照"])
        row["结算金额"] = float(snapshot_amount) if snapshot_amount is not None else row["金额快照"]
        row["结算周期"] = row["周期快照"]
        return row

    amount = compute_amount(row.get("上网电量"), row.get("结算电价"), row.get("补贴金额"))
    if amount is not None:
        row["结算金额"] = float(amount)
    period = normalize_period(row.get("结算周期"))
    if period is not None:
        row["结算周期"] = period
    row["口径版本"] = CALC_VERSION
    return row


def reconcile(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """全量对齐口径。三个入口取数前都先走这里，列表页重算出的结果即准绳。"""
    for row in rows:
        apply_caliber(row)
    return rows


def freeze_on_settle(row: dict[str, Any]) -> None:
    """确认结清时调用：把当时的金额与周期按现行结果固化下来。"""
    apply_caliber(row)
    row["金额快照"] = row.get("结算金额")
    row["周期快照"] = row.get("结算周期")


def format_money(value: Any) -> str:
    """清单导出等文本场景使用的金额格式：固定两位小数；无值留空。"""
    amount = to_decimal(value)
    if amount is None:
        return ""
    return str(amount.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def present_row(row: dict[str, Any]) -> dict[str, Any]:
    """对外展示的行：结算状态取状态机字段，金额统一收敛到分。

    列表、详情、导出拿到的都是这一份结构，避免入口间字段口径再分叉。
    """
    item = dict(row)
    item.pop("金额快照", None)
    item.pop("周期快照", None)
    item["结算状态"] = row.get("status")
    amount = to_decimal(item.get("结算金额"))
    if amount is not None:
        item["结算金额"] = float(amount.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))
    return item
