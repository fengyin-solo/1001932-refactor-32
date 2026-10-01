"""电量结算业务规则：状态流转、字段校验与筛选口径都收在这里。

金额与结算周期的计算不在本文件内各写一遍，统一走 settle_calc，
列表、详情、导出取同一份结果。
"""
from __future__ import annotations

from typing import Any

from app.services.settle_calc import apply_caliber, freeze_checked_amount, recalc_existing
from app.store import store

MODULE = "settle"
REQUIRED_FIELDS = ["结算单号", "结算周期", "所属场站"]
OPTIONAL_FIELDS = ["上网电量", "结算电价", "补贴金额"]
STATUS_ORDER = ["待核算", "已核算", "待复核", "已结清"]
ACTION_RULES = {"提交核算": "已核算", "提交复核": "待复核", "确认结清": "已结清"}
NEGATIVE_ACTIONS = []


class SettleService:
    def __init__(self) -> None:
        # 启动即按当前金额口径迁移一遍：未核对的旧单按新口径重算，
        # 已核对过的单据固化当初取值、保持不变。
        recalc_existing(store.rows(MODULE))

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("结算单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [apply_caliber(dict(row)) for row in rows[start:start + size]]
        return page_rows, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        # 详情页与列表页共用同一份口径，不允许单独再算一遍。
        return apply_caliber(dict(entry))

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry.update({field: values.get(field) for field in OPTIONAL_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        # 新建单据也走共用口径，保证登记后列表、详情、导出立刻一致。
        return apply_caliber(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电量结算单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于电量结算可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if target == "已结清":
            # 核对结清的瞬间固化金额，以后口径调整也不动这张单。
            freeze_checked_amount(entry)
        else:
            apply_caliber(entry)
        return apply_caliber(dict(entry)), f"电量结算单已{action}"
