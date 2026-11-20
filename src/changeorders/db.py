"""SQLite storage and reporting for change orders."""
from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

STATUSES = ("pending", "approved", "rejected")

SCHEMA = """
CREATE TABLE IF NOT EXISTS contracts (
    project TEXT PRIMARY KEY,
    amount_cents INTEGER NOT NULL,
    days INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS change_orders (
    project TEXT NOT NULL,
    number TEXT NOT NULL,
    title TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    days_added INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    submitted TEXT,
    PRIMARY KEY (project, number)
);
"""


class LogError(ValueError):
    """Raised for bad input or an unknown record."""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the database and make sure the tables exist."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def to_cents(text: str | float | int) -> int:
    """Convert '12,500.50' or '-300' to integer cents."""
    try:
        cleaned = str(text).replace(",", "").replace("$", "").strip()
        return round(float(cleaned) * 100)
    except ValueError as error:
        raise LogError(f"not a money amount: {text!r}") from error


def money(cents: int) -> str:
    """Format cents as dollars with a sign for negatives."""
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def set_contract(conn: sqlite3.Connection, project: str, amount: str, days: int = 0) -> None:
    """Create or replace the original contract for a project."""
    conn.execute(
        "INSERT INTO contracts VALUES (?, ?, ?) ON CONFLICT(project) "
        "DO UPDATE SET amount_cents = excluded.amount_cents, days = excluded.days",
        (project, to_cents(amount), days),
    )
    conn.commit()


def add_change_order(
    conn: sqlite3.Connection,
    project: str,
    number: str,
    title: str,
    amount: str,
    days_added: int = 0,
    status: str = "pending",
    submitted: str | None = None,
) -> None:
    """Insert a change order; the project must have a contract."""
    if status not in STATUSES:
        raise LogError(f"status must be one of {', '.join(STATUSES)}")
    if not conn.execute("SELECT 1 FROM contracts WHERE project = ?", (project,)).fetchone():
        raise LogError(f"no contract for project {project!r}; add it first")
    try:
        conn.execute(
            "INSERT INTO change_orders VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project, number, title, to_cents(amount), days_added, status, submitted),
        )
    except sqlite3.IntegrityError as error:
        raise LogError(f"{number} already exists for {project}") from error
    conn.commit()


def decide(conn: sqlite3.Connection, project: str, number: str, status: str) -> None:
    """Mark a change order approved or rejected."""
    if status not in ("approved", "rejected"):
        raise LogError("decision must be approved or rejected")
    cursor = conn.execute(
        "UPDATE change_orders SET status = ? WHERE project = ? AND number = ?",
        (status, project, number),
    )
    if cursor.rowcount == 0:
        raise LogError(f"no change order {number} on {project}")
    conn.commit()


def import_csv(conn: sqlite3.Connection, path: str | Path) -> int:
    """Load change orders from a CSV with project, number, title, amount, days_added,
    status, submitted columns. Returns the number of rows added."""
    count = 0
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            add_change_order(
                conn,
                row["project"],
                row["number"],
                row["title"],
                row["amount"],
                int(row.get("days_added") or 0),
                (row.get("status") or "pending").lower(),
                row.get("submitted") or None,
            )
            count += 1
    return count


@dataclass(frozen=True)
class Summary:
    """Contract totals for one project."""

    project: str
    original: int
    approved: int
    pending: int
    rejected: int
    days_approved: int

    @property
    def revised(self) -> int:
        """Original contract plus approved change orders."""
        return self.original + self.approved

    @property
    def percent_change(self) -> float:
        """Approved change as a percent of the original contract."""
        return 100.0 * self.approved / self.original if self.original else 0.0


def summarize(conn: sqlite3.Connection, project: str | None = None) -> list[Summary]:
    """Totals per project, or for one project."""
    rows = conn.execute("SELECT * FROM contracts ORDER BY project").fetchall()
    result = []
    for row in rows:
        if project and row["project"] != project:
            continue
        sums = {s: 0 for s in STATUSES}
        days = 0
        for co in conn.execute(
            "SELECT status, amount_cents, days_added FROM change_orders WHERE project = ?",
            (row["project"],),
        ):
            sums[co["status"]] += co["amount_cents"]
            if co["status"] == "approved":
                days += co["days_added"]
        result.append(
            Summary(row["project"], row["amount_cents"], sums["approved"],
                    sums["pending"], sums["rejected"], days)
        )
    if project and not result:
        raise LogError(f"unknown project {project!r}")
    return result


def report(conn: sqlite3.Connection, project: str | None = None) -> str:
    """Text report: totals and the change order list for each project."""
    out = []
    for s in summarize(conn, project):
        out.append(f"Project: {s.project}")
        out.append(f"  Original contract  {money(s.original):>14}")
        out.append(f"  Approved changes   {money(s.approved):>14}  ({s.percent_change:+.1f}%)")
        out.append(f"  Revised contract   {money(s.revised):>14}")
        out.append(f"  Pending exposure   {money(s.pending):>14}")
        out.append(f"  Rejected           {money(s.rejected):>14}")
        out.append(f"  Days added (approved): {s.days_approved}")
        rows = conn.execute(
            "SELECT * FROM change_orders WHERE project = ? ORDER BY number", (s.project,)
        )
        for co in rows:
            out.append(
                f"    {co['number']}  {co['status']:<8} {money(co['amount_cents']):>12}  "
                f"{co['days_added']:>3}d  {co['title']}"
            )
        out.append("")
    return "\n".join(out).rstrip() if out else "no projects"
