#!/usr/bin/env python3
"""
records.csv に投稿結果を1行追記するスクリプト。

使い方（手動）:
  python scripts/log_result.py \
    --url https://note.com/taku629/n/nXXXX \
    --likes 12 \
    --pv 340 \
    --cta A

使い方（引数なし → 対話モード）:
  python scripts/log_result.py
"""
import argparse
import csv
import sys
from datetime import date
from pathlib import Path

RECORDS = Path(__file__).parent.parent / "records.csv"
DRAFTS  = Path(__file__).parent.parent / "drafts.json"

FIELDNAMES = [
    "date", "title", "category", "topic_source", "note_url",
    "pv", "likes", "comments", "followers_gained",
    "cta_type", "paid_clicks", "revenue", "remarks",
]


def find_draft_by_url(url: str) -> dict:
    """drafts.json から URL に一致するエントリを探す。"""
    import json
    if not DRAFTS.exists():
        return {}
    for d in json.loads(DRAFTS.read_text(encoding="utf-8")):
        if d.get("public_url") == url or d.get("key") and d["key"] in url:
            return d
    return {}


def prompt_input(field: str, default: str = "") -> str:
    val = input(f"  {field} [{default}]: ").strip()
    return val if val else default


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url",      default="")
    parser.add_argument("--likes",    default="")
    parser.add_argument("--pv",       default="")
    parser.add_argument("--comments", default="")
    parser.add_argument("--followers-gained", default="")
    parser.add_argument("--cta",      default="")
    parser.add_argument("--paid-clicks", default="")
    parser.add_argument("--revenue",  default="")
    parser.add_argument("--remarks",  default="")
    args = parser.parse_args()

    interactive = not any([args.url, args.likes, args.pv])

    if interactive:
        print("=== records.csv 追記（対話モード）===")
        url      = prompt_input("note_url")
        likes    = prompt_input("likes")
        pv       = prompt_input("pv")
        comments = prompt_input("comments")
        followers_gained = prompt_input("followers_gained")
        cta      = prompt_input("cta_type (A/B/C)")
        paid_clicks = prompt_input("paid_clicks")
        revenue  = prompt_input("revenue")
        remarks  = prompt_input("remarks")
    else:
        url      = args.url
        likes    = args.likes
        pv       = args.pv
        comments = args.comments
        followers_gained = args.followers_gained
        cta      = args.cta
        paid_clicks = args.paid_clicks
        revenue  = args.revenue
        remarks  = args.remarks

    # drafts.json から title / category / topic_source を補完
    draft = find_draft_by_url(url)
    title        = draft.get("title", "")
    topic_source = "trend" if draft.get("trend_raw") and draft.get("score", 0) >= 1 else "fallback"
    cta_type     = cta or draft.get("cta_type", "")

    # category は drafts.json にないので空欄（手入力）
    category = ""
    if interactive:
        category = prompt_input("category (お金/副業/AI活用/etc.)", "")

    row = {
        "date":             str(date.today()),
        "title":            title,
        "category":         category,
        "topic_source":     topic_source,
        "note_url":         url,
        "pv":               pv,
        "likes":            likes,
        "comments":         comments,
        "followers_gained": followers_gained,
        "cta_type":         cta_type,
        "paid_clicks":      paid_clicks,
        "revenue":          revenue,
        "remarks":          remarks,
    }

    write_header = not RECORDS.exists() or RECORDS.stat().st_size == 0
    with RECORDS.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    print(f"\n✓ records.csv に追記しました: {row['date']} | {row['title'][:30]}")


if __name__ == "__main__":
    main()
