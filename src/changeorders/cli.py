"""Command line for the change order log."""
from __future__ import annotations

import argparse
import sys

from . import db


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="changeorders", description=__doc__)
    parser.add_argument("--db", default="changeorders.db", help="SQLite file")
    sub = parser.add_subparsers(dest="cmd", required=True)

    contract = sub.add_parser("contract", help="set the original contract for a project")
    contract.add_argument("project")
    contract.add_argument("amount")
    contract.add_argument("--days", type=int, default=0, help="original duration in days")

    add = sub.add_parser("add", help="add a change order")
    add.add_argument("project")
    add.add_argument("number")
    add.add_argument("title")
    add.add_argument("amount", help="negative for a credit")
    add.add_argument("--days", type=int, default=0)
    add.add_argument("--status", default="pending", choices=db.STATUSES)
    add.add_argument("--submitted")

    for name in ("approve", "reject"):
        dec = sub.add_parser(name, help=f"{name} a change order")
        dec.add_argument("project")
        dec.add_argument("number")

    imp = sub.add_parser("import", help="load change orders from a CSV file")
    imp.add_argument("csv")

    rep = sub.add_parser("report", help="print totals and the change order list")
    rep.add_argument("--project")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command line; return the exit code."""
    args = build_parser().parse_args(argv)
    try:
        conn = db.connect(args.db)
        if args.cmd == "contract":
            db.set_contract(conn, args.project, args.amount, args.days)
            print(f"contract set: {args.project} {db.money(db.to_cents(args.amount))}")
        elif args.cmd == "add":
            db.add_change_order(conn, args.project, args.number, args.title, args.amount,
                                args.days, args.status, args.submitted)
            print(f"added {args.number} to {args.project}")
        elif args.cmd in ("approve", "reject"):
            status = "approved" if args.cmd == "approve" else "rejected"
            db.decide(conn, args.project, args.number, status)
            print(f"{args.number} {status}")
        elif args.cmd == "import":
            print(f"imported {db.import_csv(conn, args.csv)} change orders")
        else:
            print(db.report(conn, args.project))
    except (db.LogError, OSError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0
