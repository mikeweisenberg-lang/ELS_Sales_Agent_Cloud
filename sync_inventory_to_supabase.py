import os
import requests
from supabase import create_client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Supabase connection
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# WordPress inventory endpoint
API_URL = "https://easylivingspaces.com/wp-json/els/v1/rooms"


def fetch_rooms():
    print("Fetching room inventory from website...")

    response = requests.get(API_URL)

    if response.status_code != 200:
        raise Exception(
            f"Failed to fetch inventory. Status code: {response.status_code}"
        )

    data = response.json()

    room_count = data.get("count", 0)
    rooms = data.get("rooms", [])

    print(f"Found {room_count} rooms.")
    print()

    for room in rooms[:5]:
        acf = room.get("acf", {})

        print("------------------------")
        print("Title:", room.get("title"))
        print("Listing Number:", acf.get("listing_number"))
        print("Price:", acf.get("price"))
        print("Location:", acf.get("location"))
        print("URL:", room.get("url"))
        print("------------------------")
        print()

    print("Inventory test completed successfully.")


if __name__ == "__main__":
    fetch_rooms()
