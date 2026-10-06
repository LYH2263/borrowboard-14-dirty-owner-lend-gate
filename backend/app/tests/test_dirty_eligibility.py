import threading
import pytest
from fastapi import HTTPException

from app import seed
from app import main
from app.db import connect
from app.engines.borrow_rules import can_lend, item_flags

DIRTY_ID = 3   # 种子: ("脏数据-无主", "", "available", "dirty")
DRILL_ID = 1   # 种子: ("电钻", "老周", "available", "clean")

@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seed.init_db()
    return tmp_path

def _item(iid):
    c = connect()
    row = dict(c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone())
    c.close()
    return row

# ---------- 纯规则: 脏物资格拍板=放行 ----------

def test_dirty_is_released_by_policy():
    ok = can_lend("available", 0, "dirty")
    assert ok["ok"] is True
    assert item_flags({"data_quality": "dirty", "owner": ""}) == {"dirty": True, "owner_missing": True}

def test_dirty_still_respects_own_mutex():
    # 脏物不豁免"同一物品一笔活动借据"，但互斥只数自己那一笔。
    assert can_lend("available", 1, "dirty")["reason"] == "already_on_loan"
    assert can_lend("on_loan", 0, "dirty")["reason"] == "item_not_available"

# ---------- 三处可借计数: 物主栏/可借栏/顶细条 ----------

def test_dirty_counts_in_all_three_spots(fresh_db):
    b = main.board()
    titles = [i["title"] for i in b["available"]]
    assert "脏数据-无主" in titles                      # 可借栏看得到
    assert b["counts"]["available"] == 3              # 顶细条可借数算上它
    dirty = next(i for i in b["available"] if i["id"] == DIRTY_ID)
    assert dirty["dirty"] is True and dirty["owner_missing"] is True
    owners = main.items()                             # 物主栏同一批数据
    assert {i["id"] for i in owners} >= {DIRTY_ID, DRILL_ID}
    assert next(i for i in owners if i["id"] == DIRTY_ID)["status"] == "available"

# ---------- 脏物能完成借出, 且全链路不洗数据 ----------

def test_lend_dirty_succeeds_without_laundering(fresh_db):
    r = main.lend(DIRTY_ID, main.LendIn(borrower="邻居乙", due_date="2026-12-31"))
    assert r["dirty"] is True and r["owner_missing"] is True
    row = _item(DIRTY_ID)
    assert row["status"] == "on_loan"
    assert row["data_quality"] == "dirty"             # 没被改成 clean
    assert row["owner"] == ""                         # 没补写 owner

def test_failed_lend_keeps_dirty_and_owner(fresh_db):
    main.lend(DIRTY_ID, main.LendIn(borrower="先到", due_date="2026-12-31"))
    with pytest.raises(HTTPException) as e:
        main.lend(DIRTY_ID, main.LendIn(borrower="后到", due_date="2026-12-31"))
    assert e.value.status_code == 409
    row = _item(DIRTY_ID)
    assert row["data_quality"] == "dirty" and row["owner"] == "" and row["status"] == "on_loan"
    c = connect()
    n = c.execute("SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'", (DIRTY_ID,)).fetchone()["c"]
    c.close()
    assert n == 1

def test_return_dirty_stays_dirty_ownerless(fresh_db):
    lid = main.lend(DIRTY_ID, main.LendIn(borrower="邻居乙", due_date="2026-12-31"))["loan_id"]
    main.return_loan(lid)
    row = _item(DIRTY_ID)
    assert row["status"] == "available" and row["data_quality"] == "dirty" and row["owner"] == ""

# ---------- 并发: 脏物一借一得; 电钻绝不被脏物挡住 ----------

def test_concurrent_dirty_contenders_and_drill_are_independent(fresh_db):
    n_contenders = 4
    barrier = threading.Barrier(n_contenders + 1)
    results = {}

    def contend(slot):
        barrier.wait()
        try:
            r = main.lend(DIRTY_ID, main.LendIn(borrower=f"抢{slot}", due_date="2026-12-31"))
            results[("dirty", slot)] = ("ok", r["loan_id"])
        except HTTPException as e:
            results[("dirty", slot)] = (e.status_code, e.detail)

    def drill():
        barrier.wait()
        try:
            r = main.lend(DRILL_ID, main.LendIn(borrower="钻友", due_date="2026-12-31"))
            results["drill"] = ("ok", r["loan_id"])
        except HTTPException as e:
            results["drill"] = (e.status_code, e.detail)

    threads = [threading.Thread(target=contend, args=(s,)) for s in range(n_contenders)]
    threads.append(threading.Thread(target=drill))
    for t in threads: t.start()
    for t in threads: t.join()

    dirty_outcomes = [results[("dirty", s)] for s in range(n_contenders)]
    assert sum(1 for o in dirty_outcomes if o[0] == "ok") == 1   # 恰好一笔扣到
    assert {o[0] for o in dirty_outcomes} <= {"ok", 409}
    assert results["drill"][0] == "ok"                            # 电钻不被脏物互斥
    c = connect()
    assert c.execute("SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'", (DIRTY_ID,)).fetchone()["c"] == 1
    assert c.execute("SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'", (DRILL_ID,)).fetchone()["c"] == 1
    dirty_row = dict(c.execute("SELECT * FROM items WHERE id=?", (DIRTY_ID,)).fetchone())
    drill_row = dict(c.execute("SELECT * FROM items WHERE id=?", (DRILL_ID,)).fetchone())
    c.close()
    assert (dirty_row["status"], dirty_row["data_quality"], dirty_row["owner"]) == ("on_loan", "dirty", "")
    assert (drill_row["status"], drill_row["data_quality"]) == ("on_loan", "clean")
