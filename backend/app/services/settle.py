"""电量结算业务规则：状态流转、字段校验与筛选口径都收在这里。

金额与结算周期的计算一律走 ``settle_calc`` 共用口径，本服务不再自己算钱。
列表、详情、导出三个入口取数时都经过同一道口径对齐，保证同一张结算单
在任何入口看到的结算金额都一致。
"""
from __future__ import annotations

from typing import Any

from app.services.settle_calc import (
    FINAL_STATUS,
    apply_caliber,
    freeze_on_settle,
    present_row,
    reconcile,
)
from app.store import store

MODULE = "settle"
REQUIRED_FIELDS = ["结算单号", "结算周期", "所属场站", "上网电量", "结算电价"]
NUMERIC_FIELDS = ["上网电量", "结算电价", "补贴金额"]
STATUS_ORDER = ["待核算", "已核算", "待复核", "已结清"]
ACTION_RULES = {"提交核算": "已核算", "提交复核": "待复核", "确认结清": FINAL_STATUS}
NEGATIVE_ACTIONS = []


class SettleService:
    def _aligned_rows(self) -> list[dict[str, Any]]:
        """先按共用口径全量对齐（以列表重算结果为准回写），再供各入口取用。"""
        return reconcile(store.rows(MODULE))

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._aligned_rows()
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("结算单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [present_row(row) for row in rows[start:start + size]]
        return page_rows, total

    def export_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """导出取数与列表完全同源：同一份口径对齐后的结果，只是不分页。"""
        rows = self._aligned_rows()
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("结算单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return [present_row(row) for row in rows]

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        rows = self._aligned_rows()
        entry = next((row for row in rows if int(row.get("id", 0)) == entry_id), None)
        return present_row(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in NUMERIC_FIELDS:
            if values.get(field) not in (None, ""):
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        # 新登记的单据直接按现行口径算好，三个入口拿到的是同一份值。
        apply_caliber(entry)
        rows.append(entry)
        return present_row(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电量结算单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于电量结算可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if entry.get("status") == FINAL_STATUS:
            # 已结清单据的金额已经核对固化，不允许再流转、再重算。
            return None, "电量结算单已结清，结算金额已核对固化，不能再执行状态动作"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if target == FINAL_STATUS:
            # 结清瞬间把金额与周期快照固化，以后口径调整也不动它。
            freeze_on_settle(entry)
        return present_row(entry), f"电量结算单已{action}"
