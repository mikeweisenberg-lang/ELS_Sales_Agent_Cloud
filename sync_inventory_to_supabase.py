import os
import re
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

API_URL = "https://easylivingspaces.com/wp-json/els/v1/rooms"

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL")

if not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def clean_html(value):
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return None


def extract_images(acf):
    images = []

    for item in acf.get("room_images") or []:
        image = item.get("image") or {}
        url = image.get("url")
        if url:
            images.append(url)

    return images


def extract_video_links(acf):
    videos = []

    for item in acf.get("room_images") or []:
        video = item.get("video_link")
        if video:
            videos.append(video)

    return videos


def extract_features(items):
    features = []

    for item in items or []:
        feature = item.get("feature")
        if feature:
            features.append(feature)

    return features


def map_room(room):
    acf = room.get("acf") or {}

    listing_number = str(acf.get("listing_number") or room.get("id") or "").strip()

    return {
        "listing_number": listing_number,
        "title": room.get("title"),
        "url": room.get("url"),

        "location": acf.get("select_location") or acf.get("location"),
        "neighborhood": acf.get("location_") or acf.get("location"),

        "price": to_int(acf.get("discount_price") or acf.get("price")),

        "available_from": acf.get("availability_month") or acf.get("availability_month_2") or None,
        "available_status": (
            "available"
            if str(acf.get("is_available") or acf.get("is_available_2") or "").strip() == "1"
            else "not_available"
        ),

        "beds": to_int(acf.get("bed")),
        "bathrooms": to_int(acf.get("bathroom")),

        "room_description": clean_html(room.get("content")),
        "apartment_description": clean_html(room.get("excerpt")),

        "property_features": extract_features(acf.get("property_features")),
        "room_features": [],

        "images": extract_images(acf),
        "video_links": extract_video_links(acf),

        "raw_acf": acf,

        "last_synced_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_rooms():
    print("Fetching room inventory from website...")

    response = requests.get(API_URL, timeout=60)

    print(f"Website response status: {response.status_code}")

    if response.status_code not in (200, 202):
        raise RuntimeError(f"Failed to fetch inventory. Status code: {response.status_code}")

    if "sgcaptcha" in response.text.lower():
        raise RuntimeError("Website returned CAPTCHA instead of JSON. Endpoint must be whitelisted.")

    data = response.json()

    rooms = data.get("rooms", [])
    count = data.get("count", len(rooms))

    print(f"Website returned {count} rooms.")
    return rooms


def upsert_listing(row):
    listing_number = row["listing_number"]

    existing = (
        supabase
        .table("inventory_listings")
        .select("listing_number")
        .eq("listing_number", listing_number)
        .execute()
    )

    if existing.data:
        result = (
            supabase
            .table("inventory_listings")
            .update(row)
            .eq("listing_number", listing_number)
            .execute()
        )
        return "updated", result
    else:
        result = (
            supabase
            .table("inventory_listings")
            .insert(row)
            .execute()
        )
        return "inserted", result


def sync_inventory():
    rooms = fetch_rooms()

    inserted = 0
    updated = 0
    skipped = 0

    for room in rooms:
        try:
            row = map_room(room)

            if not row["listing_number"]:
                skipped += 1
                print("Skipped room with missing listing number:", room.get("title"))
                continue

            action, _ = upsert_listing(row)

            if action == "inserted":
                inserted += 1
            elif action == "updated":
                updated += 1

            print(f"{action.upper()} | #{row['listing_number']} | {row['title']} | ${row['price']}")

        except Exception as e:
            skipped += 1
            print(f"ERROR syncing room {room.get('title')}: {e}")

    print()
    print("Inventory sync complete.")
    print(f"Inserted: {inserted}")
    print(f"Updated: {updated}")
    print(f"Skipped/errors: {skipped}")


if __name__ == "__main__":
    sync_inventory()
