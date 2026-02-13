#!/usr/bin/env python3
"""
Google Photos Duplicate Finder — Main CLI

Usage:
    python main.py scan [--days N]       Scan library and compute hashes
    python main.py report                Generate HTML review report
    python main.py delete [--batch]      Interactive or batch deletion helper
    python main.py run [--days N]        Full pipeline: scan → find → report
"""

import argparse
import sys
import json
import os

from scanner import scan_library, load_json
from duplicates import find_all_duplicates
from report import generate_report


def cmd_scan(args):
    """Scan Google Photos library."""
    config = load_json("config.json", {})
    scan_library(days=args.days, config=config)


def cmd_report(args):
    """Find duplicates and generate HTML report."""
    config = load_json("config.json", {})
    groups = find_all_duplicates(config=config)
    
    output_path = args.output or config.get("report_path", "report.html")
    generate_report(groups, output_path=output_path)


def cmd_delete(args):
    """Launch deletion helper."""
    from deleter import delete_photos_interactive, batch_open_urls
    
    if args.batch:
        batch_open_urls(args.list, batch_size=args.batch_size)
    else:
        delete_photos_interactive(args.list)


def cmd_run(args):
    """Full pipeline: scan → find duplicates → generate report."""
    config = load_json("config.json", {})
    
    # Step 1: Scan
    print("=" * 60)
    print("  Step 1: Scanning Google Photos Library")
    print("=" * 60)
    scan_library(days=args.days, config=config)

    # Step 2: Find duplicates
    print("\n" + "=" * 60)
    print("  Step 2: Finding Duplicates")
    print("=" * 60)
    groups = find_all_duplicates(config=config)

    if not groups:
        print("\n✨ No duplicates found!")
        return

    # Step 3: Generate report
    print("\n" + "=" * 60)
    print("  Step 3: Generating Report")
    print("=" * 60)
    output_path = config.get("report_path", "report.html")
    generate_report(groups, output_path=output_path)

    print(f"\n✅ Done! Open {output_path} in your browser to review duplicates.")


def main():
    parser = argparse.ArgumentParser(
        description="Google Photos Duplicate Finder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # scan
    scan_parser = subparsers.add_parser("scan", help="Scan Google Photos library")
    scan_parser.add_argument(
        "--days", type=int, default=None,
        help="Only scan photos from the last N days"
    )

    # report
    report_parser = subparsers.add_parser("report", help="Generate duplicate report")
    report_parser.add_argument(
        "--output", "-o", default=None,
        help="Output path for HTML report"
    )

    # delete
    delete_parser = subparsers.add_parser("delete", help="Deletion helper")
    delete_parser.add_argument(
        "--list", default="delete_list.json",
        help="Path to delete_list.json"
    )
    delete_parser.add_argument(
        "--batch", action="store_true",
        help="Use batch mode (opens tabs)"
    )
    delete_parser.add_argument(
        "--batch-size", type=int, default=10,
        help="Number of tabs per batch"
    )

    # run (full pipeline)
    run_parser = subparsers.add_parser("run", help="Full pipeline: scan → report")
    run_parser.add_argument(
        "--days", type=int, default=None,
        help="Only scan photos from the last N days"
    )

    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "delete":
        cmd_delete(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
