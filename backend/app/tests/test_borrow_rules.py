import os

from fastapi.testclient import TestClient

from app.db import connect
from app.engines.borrow_rules import (
    annotate_item, can_lend, classify_loans, is_overdue, lend_eligibility,
)

DIRTY = {"id": 3, "title": "脏数据-无主", "owner": "", "status": "available", "data_quality": "dirty"}
DRILL = {"id": 1, "title": "电钻", "owner": "老周", "status": "available", "data_quality": "clean"}


def test_mutex():
    assert can_lend("available", 0, item=DRILL)["ok"]
    assert can_lend("available", 1, item=DRILL)["reason"] == "already_on_loan"
    assert can_lend("retired", 0, item=DRILL)["ok"] is False


def test_overdue():
    assert is_overdue("2020-01-01", "2026-01-01", "active")
    assert not is_overdue("2020-01-01", "2026-01-01", "returned")


def test_classify():
    r = classify_loans([
        {"id": 1, "status": "active", "due_date": "2020-01-01"},
        {"id": 2, "status": "active", "due_date": "2099-01-01"},
        {"id": 3, "status": "returned", "due_date": "2020-01-01"},
    ], "2026-01-01")
    assert len(r["overdue"]) == 1 and len(r["active"]) == 1 and len(r["returned"]) == 1


def test_dirty_item_fails_eligibility():
    # 拍板拒绝：无主 + dirty 双理由
    r = lend_eligibility(DIRTY)
    assert r["ok"] is False
    assert set(r["reasons"]) == {"owner_missing", "dirty_data"}
    # 资格闸先于互斥闸
    assert can_lend("available", 0, item=DIRTY)["reason"] == "owner_missing"
    assert can_lend("available", 5, item=DIRTY)["reason"] == "owner_missing"
    # 单有脏标记或单无主也拒绝；干净有主才放行
    assert not lend_eligibility({**DIRTY, "owner": "阿强"})["ok"]
    assert not lend_eligibility({**DRILL, "owner": ""})["ok"]
    assert lend_eligibility(DRILL)["ok"] is True


def test_annotate():
    assert annotate_item(DIRTY)["lend_status"] == "blocked"
    assert annotate_item(DRILL)["lend_status"] == "lendable"
    on_loan = {**DRILL, "status": "on_loan"}
    assert annotate_item(on_loan)["lend_status"] == "on_loan"


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import seed
    from app.main import app
    seed.init_db()  # 每个 tmp 库显式播种，不依赖 startup 是否首次触发
    return TestClient(app)


def _item(c, title):
    return next(r for r in c.get("/api/items").json() if r["title"] == title)


def test_dirty_loan_rejected_and_not_rewritten(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        b = client.get("/api/board").json()
        titles = [i["title"] for i in b["available"]]
        blocked_titles = [i["title"] for i in b["blocked"]]
        # 可借栏、顶细条可借数都不含脏物；脏物单独在 blocked 里
        assert "电钻" in titles and "折叠桌" in titles and "脏数据-无主" not in titles
        assert blocked_titles == ["脏数据-无主"]
        assert b["counts"]["available"] == 2 and b["counts"]["blocked"] == 1

        dirty_id = _item(client, "脏数据-无主")["id"]
        loans_before = connect().execute("SELECT COUNT(*) c FROM loans").fetchone()["c"]

        # 试借脏物：409，且不洗数据、不补 owner、不产生 loan
        resp = client.post(f"/api/items/{dirty_id}/lend",
                           json={"borrower": "邻居乙", "due_date": "2026-12-31"})
        assert resp.status_code == 409
        assert resp.json()["detail"] in ("owner_missing", "dirty_data")

        c = connect()
        row = c.execute("SELECT * FROM items WHERE id=?", (dirty_id,)).fetchone()
        loans_after = c.execute("SELECT COUNT(*) c FROM loans").fetchone()["c"]
        c.close()
        assert row["data_quality"] == "dirty"
        assert row["owner"] == ""
        assert row["status"] == "available"
        assert loans_after == loans_before

        # 资格判定互不串行：脏物挡不住电钻，电钻借出成功
        drill_id = _item(client, "电钻")["id"]
        ok = client.post(f"/api/items/{drill_id}/lend",
                         json={"borrower": "邻居乙", "due_date": "2026-12-31"})
        assert ok.status_code == 200

        # 电钻在借后，脏物再试仍是同一拒绝，依旧不被改写
        again = client.post(f"/api/items/{dirty_id}/lend",
                            json={"borrower": "邻居丙", "due_date": "2026-12-31"})
        assert again.status_code == 409
        c = connect()
        row = c.execute("SELECT * FROM items WHERE id=?", (dirty_id,)).fetchone()
        c.close()
        assert row["data_quality"] == "dirty" and row["owner"] == ""

        # 物主栏 status 同步：电钻在借、脏物 blocked
        items = {i["title"]: i for i in client.get("/api/items").json()}
        assert items["电钻"]["lend_status"] == "on_loan"
        assert items["脏数据-无主"]["lend_status"] == "blocked"
        # 顶细条：电钻离开可借栏后可借数为 1，在借数为 1，脏物始终不计入可借
        b2 = client.get("/api/board").json()
        assert b2["counts"]["available"] == 1
        assert b2["counts"]["active"] == 1
        assert b2["counts"]["blocked"] == 1
