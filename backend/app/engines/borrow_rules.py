"""One active loan per item + overdue detection.

Dirty-data policy (拍板: 放行):
    An item whose data_quality is "dirty" (e.g. seeded with an empty owner)
    is still lendable. Dirtyness is advisory data quality, never a lending
    blocker: it must be counted on the board, shown in the owner list and be
    allowed to complete a loan. The lend path must in return never launder it
    — a failed or successful loan neither rewrites data_quality to "clean"
    nor fills in the missing owner.

Mutex scope:
    The one-active-loan rule is scoped to the item's own active loans only.
    A dirty item is never treated as a mutex partner of any other item, so a
    concurrent loan on e.g. the drill is not blocked by loans on the dirty
    item (and vice versa).
"""

def item_flags(item: dict) -> dict:
    """Advisory flags shown by the API; neither flag affects eligibility."""
    dq = item.get("data_quality") or "clean"
    owner = item.get("owner") or ""
    return {"dirty": dq == "dirty", "owner_missing": not owner.strip()}

def can_lend(item_status: str, active_loans: int, data_quality: str = "clean") -> dict:
    # data_quality is accepted deliberately: even "dirty" is released.
    if item_status != "available":
        return {"ok": False, "reason": "item_not_available"}
    if active_loans > 0:
        return {"ok": False, "reason": "already_on_loan"}
    return {"ok": True, "reason": ""}

def is_overdue(due_date: str, today: str, loan_status: str) -> bool:
    if loan_status != "active":
        return False
    return bool(due_date) and due_date < today

def classify_loans(loans: list[dict], today: str) -> dict:
    active, overdue, returned = [], [], []
    for L in loans:
        st = L.get("status")
        if st == "returned":
            returned.append(L)
        elif is_overdue(L.get("due_date"), today, st):
            overdue.append({**L, "overdue": True})
        elif st == "active":
            active.append({**L, "overdue": False})
    return {"active": active, "overdue": overdue, "returned": returned}
