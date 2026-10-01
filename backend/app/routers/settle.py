"""电量结算接口：维护电量结算单，覆盖提交核算、提交复核、确认结清等动作。

列表、详情、导出三个入口的数据都经过 SettleService 的共用金额口径，
导出清单与结算列表逐项对得上。
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.settle import SettleService
from app.services.settle_calc import export_rows

router = APIRouter(prefix="/api/settle", tags=["电量结算"])

service = SettleService()

STATUSES = ["待核算", "已核算", "待复核", "已结清"]


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


@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None, description="按结算单号检索"),
    status: str | None = Query(default=None, description="待核算、已核算、待复核、已结清"),
    format: str = Query(default="csv", description="导出格式：csv 或 json"),
):
    """导出电量结算清单：与结算列表同一过滤条件、同一份金额口径。

    注意：该路由必须声明在 /{entry_id} 之前，否则「export」会被当成单据编号。
    """
    # 全量取数但走的是和列表完全相同的 service 入口，金额不会出现第二套写法。
    items, total = service.list_entries(keyword=keyword, status=status, page=1, size=10000)

    if format == "json":
        return {"module": "settle", "total": total, "items": items}

    header, lines = export_rows(items)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(lines)
    # 带 BOM，Excel 直接打开中文不乱码。
    data = "\ufeff" + buffer.getvalue()
    return StreamingResponse(
        iter([data.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=settle_export.csv"},
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
