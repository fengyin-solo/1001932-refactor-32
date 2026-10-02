"""电量结算接口：维护电量结算单，覆盖提交核算、提交复核、确认结清等动作。"""
from __future__ import annotations

import csv
import io
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.settle import SettleService
from app.services.settle_calc import format_money

router = APIRouter(prefix="/api/settle", tags=["电量结算"])

service = SettleService()

LIST_FIELDS = ["结算单号", "结算周期", "所属场站", "上网电量", "结算电价", "补贴金额", "结算金额", "结算状态"]
STATUSES = ["待核算", "已核算", "待复核", "已结清"]
# 清单里按“金额”展示的列，固定两位小数，保证与列表页看到的取值逐分对齐。
MONEY_FIELDS = ["补贴金额", "结算金额"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按结算单号检索"),
    status: str | None = Query(default=None, description="待核算、已核算、待复核、已结清"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按结算单号与状态过滤电量结算列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


# 注意：导出路由必须声明在 /{entry_id} 之前，否则 export 会被当成结算单 id 解析。
@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None, description="按结算单号检索，与列表筛选一致"),
    status: str | None = Query(default=None, description="按结算状态过滤，与列表筛选一致"),
) -> Response:
    """导出电量结算清单：数据直接取列表页同一份口径结果，另存为 CSV 清单。

    清单里的金额由共用逻辑固定格式化成两位小数，和结算列表对得上。
    """
    items = service.export_entries(keyword=keyword, status=status)
    buffer = io.StringIO()
    # UTF-8 BOM，保证 Excel 直接打开中文不乱码。
    buffer.write("﻿")
    writer = csv.writer(buffer)
    writer.writerow(LIST_FIELDS)
    for item in items:
        writer.writerow([
            format_money(item.get(field)) if field in MONEY_FIELDS else (item.get(field) if item.get(field) is not None else "")
            for field in LIST_FIELDS
        ])
    filename = quote("电量结算清单.csv")
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条电量结算单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"电量结算单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条电量结算单，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="电量结算单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条电量结算单执行提交核算、提交复核、确认结清；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
