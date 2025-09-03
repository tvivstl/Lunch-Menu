#!/usr/bin/env python3
"""
fetch_menu.py

Fetches a Nutrislice weekly menu for a given school and menu-type,
extracts the "top" item for each day, and writes JSON + ICS outputs
suitable for use with DAKboard.

Defaults are tuned for:
https://parkwayschools.nutrislice.com/menu/pierremont-elementary/lunch
"""

from __future__ import annotations
import requests
import json
import argparse
from datetime import datetime, date, timedelta
import sys
import os
import logging
import uuid

# -------------- Configuration defaults --------------
DEFAULT_SCHOOL_SLUG = "pierremont-elementary"
DEFAULT_MENU_TYPE = "lunch"
BASE_URL_TEMPLATE = "https://parkwayschools.nutrislice.com/menu/api/weeks/school/{school}/menu-type/{menu_type}/{year}/{month:02d}/{day:02d}"

# Output filenames (written to output directory)
DEFAULT_OUTPUT_DIR = "public"
JSON_FILENAME = "dakboard_menu.json"
ICS_FILENAME = "dakboard_menu.ics"

# -------------- Logging --------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


# -------------- Nutrislice fetch --------------
def fetch_menu_week(school_slug: str, menu_type: str, target_date: date, timeout: int = 15) -> dict:
    url = BASE_URL_TEMPLATE.format(
        school=school_slug,
        menu_type=menu_type,
        year=target_date.year,
        month=target_date.month,
        day=target_date.day,
    )
    logging.info(f"Fetching Nutrislice menu from: {url}")
    headers = {
        "User-Agent": "nutrislice-dakboard-sync/1.0 (+https://github.com/yourusername/yourrepo)",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# -------------- Parsing heuristic for "top item" --------------
ENTREE_KEYWORDS = ("entree", "entrée", "entrees", "main", "hot", "chef")
IGNORE_CATEGORY_KEYWORDS = ("milk", "fruit", "dessert", "snack", "side", "sides", "vegetable", "veggie", "condiment", "salad bar")

def extract_top_item_for_day(day_obj: dict) -> str | None:
    """
    Given a 'day' object from the Nutrislice JSON, return the chosen top item name (string),
    or None if nothing suitable found.
    """
    # Nutrislice structure varies a bit; menu items commonly under 'menu_items'
    categories = day_obj.get("menu_items") or day_obj.get("categories") or day_obj.get("items") or []
    # Defensive: if each category contains 'food_category' or 'category' and 'food_items' or 'items'
    normalized = []
    for cat in categories:
        name = None
        if isinstance(cat, dict):
            # Several possible shapes — try multiple keys
            name = (
                (cat.get("food_category") or cat.get("category") or {}).get("name")
                if isinstance(cat.get("food_category") or cat.get("category"), dict)
                else cat.get("name") or cat.get("title") or None
            )
            # find list of food items
            items = cat.get("food_items") or cat.get("items") or cat.get("foodItemList") or []
            normalized.append({"name": (name or "").strip().lower(), "items": items})
    # 1) Look for an entree category first
    for cat in normalized:
        if any(k in cat["name"] for k in ENTREE_KEYWORDS):
            if cat["items"]:
                # pick the first item's food.name or item.name
                itm = cat["items"][0]
                if isinstance(itm, dict):
                    return (itm.get("food") or itm).get("name") if (itm.get("food") or itm).get("name") else str(itm)
                else:
                    return str(itm)
    # 2) Fallback: find the first category that isn't in ignore list and has items
    for cat in normalized:
        if not any(kw in cat["name"] for kw in IGNORE_CATEGORY_KEYWORDS):
            if cat["items"]:
                itm = cat["items"][0]
                if isinstance(itm, dict):
                    return (itm.get("food") or itm).get("name") if (itm.get("food") or itm).get("name") else str(itm)
                else:
                    return str(itm)
    # 3) As a last fallback, take any first available item
    for cat in normalized:
        if cat["items"]:
            itm = cat["items"][0]
            if isinstance(itm, dict):
                return (itm.get("food") or itm).get("name") if (itm.get("food") or itm).get("name") else str(itm)
            else:
                return str(itm)
    return None


# -------------- Convert menu JSON -> outputs --------------
def build_items_by_date(menu_json: dict) -> dict:
    items_by_date: dict[str, str] = {}
    days = menu_json.get("days") or menu_json.get("week") or menu_json.get("days_list") or []
    for day in days:
        # Day date usually under 'date' (ISO like '2025-09-01')
        day_date = day.get("date")
        if not day_date:
            # try other keys
            day_date = day.get("day") or day.get("dateString")
        if not day_date:
            continue
        top = extract_top_item_for_day(day)
        if top:
            items_by_date[day_date] = top
    return items_by_date


def write_dakboard_json(items_by_date: dict, outpath: str):
    # DAKboard-friendly simple list of date/title objects
    entries = []
    for d, title in sorted(items_by_date.items()):
        entries.append({"date": d, "title": title})
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    logging.info(f"Wrote JSON output: {outpath} ({len(entries)} entries)")


def make_ics_calendar(items_by_date: dict, outpath: str, calendar_name: str = "School Lunch"):
    """
    Create a simple .ics calendar with all-day events.
    Each event DTSTART is the given date; DTEND is next day (per RFC5545).
    """
    def fmt_date(dt_str: str) -> str:
        # expect YYYY-MM-DD
        return dt_str.replace("-", "")

    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    uid_base = str(uuid.uuid4())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//nutrislice-dakboard//{calendar_name}//EN",
        f"X-WR-CALNAME:{calendar_name}",
    ]
    for idx, (dstr, title) in enumerate(sorted(items_by_date.items())):
        dtstart = fmt_date(dstr)
        # dtend is next day
        try:
            y, m, dd = [int(x) for x in dstr.split("-")]
            dtend_date = date(y, m, dd) + timedelta(days=1)
            dtend = dtend_date.strftime("%Y%m%d")
        except Exception:
            dtend = dtstart  # fallback
        uid = f"{uid_base}-{idx}@nutrislice-dakboard"
        lines += [
            "BEGIN:VEVENT",
            f"DTSTAMP:{now}",
            f"UID:{uid}",
            f"SUMMARY:{title}",
            # all-day event format:
            f"DTSTART;VALUE=DATE:{dtstart}",
            f"DTEND;VALUE=DATE:{dtend}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines))
    logging.info(f"Wrote ICS output: {outpath} ({len(items_by_date)} events)")


# -------------- CLI --------------
def main():
    p = argparse.ArgumentParser(description="Fetch Nutrislice menu and publish DAKboard JSON + ICS")
    p.add_argument("--school", default=DEFAULT_SCHOOL_SLUG, help="School slug (as used in Nutrislice URLs)")
    p.add_argument("--menu-type", default=DEFAULT_MENU_TYPE, help="Menu type (e.g., lunch, breakfast)")
    p.add_argument("--date", default=None, help="Any date inside the target week (YYYY-MM-DD). Defaults to today.")
    p.add_argument("--outdir", default=os.getenv("OUTPUT_DIR", DEFAULT_OUTPUT_DIR), help="Output directory")
    p.add_argument("--json-name", default=JSON_FILENAME, help="JSON filename")
    p.add_argument("--ics-name", default=ICS_FILENAME, help="ICS filename")
    args = p.parse_args()

    if args.date:
        try:
            target = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            logging.error("Invalid --date format: expected YYYY-MM-DD")
            sys.exit(2)
    else:
        target = date.today()

    # fetch
    try:
        menu_json = fetch_menu_week(args.school, args.menu_type, target)
    except Exception as e:
        logging.exception("Failed to fetch menu JSON")
        sys.exit(1)

    items_by_date = build_items_by_date(menu_json)
    if not items_by_date:
        logging.warning("No menu items found for that week. Exiting.")
        # still write empty files so DAKboard won't error if configured
        os.makedirs(args.outdir, exist_ok=True)
        write_dakboard_json({}, os.path.join(args.outdir, args.json_name))
        make_ics_calendar({}, os.path.join(args.outdir, args.ics_name))
        sys.exit(0)

    os.makedirs(args.outdir, exist_ok=True)
    json_path = os.path.join(args.outdir, args.json_name)
    ics_path = os.path.join(args.outdir, args.ics_name)

    write_dakboard_json(items_by_date, json_path)
    make_ics_calendar(items_by_date, ics_path)
    logging.info("Done.")


if __name__ == "__main__":
    main()
