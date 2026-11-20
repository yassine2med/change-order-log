from pathlib import Path

import pytest

from changeorders import db
from changeorders.cli import main

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "change_orders.csv"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.set_contract(c, "Alpha", "100,000.00", 90)
    return c


def test_to_cents_and_money():
    assert db.to_cents("1,234.56") == 123456
    assert db.to_cents("-$5") == -500
    assert db.money(-250) == "-$2.50"


def test_to_cents_rejects_text():
    with pytest.raises(db.LogError):
        db.to_cents("abc")


def test_totals_by_status(conn):
    db.add_change_order(conn, "Alpha", "CO-1", "a", "10000", 5, "approved")
    db.add_change_order(conn, "Alpha", "CO-2", "b", "-2000", 0, "approved")
    db.add_change_order(conn, "Alpha", "CO-3", "c", "3000")
    db.add_change_order(conn, "Alpha", "CO-4", "d", "500", 1, "rejected")
    s = db.summarize(conn)[0]
    assert (s.approved, s.pending, s.rejected) == (800000, 300000, 50000)
    assert s.revised == 10800000
    assert s.days_approved == 5
    assert round(s.percent_change, 1) == 8.0


def test_decide_changes_totals(conn):
    db.add_change_order(conn, "Alpha", "CO-1", "a", "1000")
    db.decide(conn, "Alpha", "CO-1", "approved")
    assert db.summarize(conn)[0].approved == 100000


def test_decide_unknown_number(conn):
    with pytest.raises(db.LogError):
        db.decide(conn, "Alpha", "CO-9", "approved")


def test_decide_rejects_bad_status(conn):
    with pytest.raises(db.LogError):
        db.decide(conn, "Alpha", "CO-1", "pending")


def test_duplicate_number_rejected(conn):
    db.add_change_order(conn, "Alpha", "CO-1", "a", "1")
    with pytest.raises(db.LogError):
        db.add_change_order(conn, "Alpha", "CO-1", "again", "2")


def test_needs_contract_first(conn):
    with pytest.raises(db.LogError):
        db.add_change_order(conn, "Nope", "CO-1", "a", "1")


def test_bad_status_on_add(conn):
    with pytest.raises(db.LogError):
        db.add_change_order(conn, "Alpha", "CO-1", "a", "1", status="maybe")


def test_unknown_project_report(conn):
    with pytest.raises(db.LogError):
        db.report(conn, "Zed")


def test_empty_report(tmp_path):
    assert db.report(db.connect(tmp_path / "e.db")) == "no projects"


def test_import_example(tmp_path):
    c = db.connect(tmp_path / "i.db")
    db.set_contract(c, "Building A Renovation", "500000")
    db.set_contract(c, "Building B Roof", "250000")
    assert db.import_csv(c, EXAMPLE) == 7
    a = db.summarize(c, "Building A Renovation")[0]
    assert a.approved == (485000 + 1820000 - 230000)


def test_cli_roundtrip(tmp_path, capsys):
    path = str(tmp_path / "c.db")
    assert main(["--db", path, "contract", "Alpha", "1000"]) == 0
    assert main(["--db", path, "add", "Alpha", "CO-1", "Fix", "100"]) == 0
    assert main(["--db", path, "approve", "Alpha", "CO-1"]) == 0
    assert main(["--db", path, "report"]) == 0
    assert "Revised contract" in capsys.readouterr().out


def test_cli_error_exit(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "x.db"), "approve", "A", "CO-1"]) == 2
    assert "error" in capsys.readouterr().err
