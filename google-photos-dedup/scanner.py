"""Scan Google Photos library and compute perceptual hashes."""

import os
import io
import json
import hashlib
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import imagehash
from PIL import Image
from tqdm import tqdm

from auth import get_authenticated_service, get_photos_api_url

DATA_DIR = "data"
PHOTO_INDEX_PATH = os.path.join(DATA_DIR, "photo_index.json")
HASH_DB_PATH = os.path.join(DATA_DIR, "hash_db.json")
THUMBNAILS_DIR = os.path.join(DATA_DIR, "thumbnails")


def ensure_dirs():
    """Create data directories if they don't exist."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(THUMBNAILS_DIR, exist_ok=True)


def load_json(path, default=None):
    """Load JSON file or return default."""
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path, data):
    """Save data as JSON."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def fetch_all_media_items(creds, days=None, progress_callback=None):
    """
    Fetch all media items from Google Photos.
    
    Args:
        creds: Authenticated credentials
        days: If set, only fetch items from the last N days
        progress_callback: Optional callback for progress updates
    
    Returns:
        List of media item dicts
    """
    base_url = get_photos_api_url()
    headers = {"Authorization": f"Bearer {creds.token}"}
    
    all_items = []
    page_token = None
    page_count = 0

    # Build request body
    body = {"pageSize": 100}
    
    if days:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        body["filters"] = {
            "dateFilter": {
                "ranges": [{
                    "startDate": {
                        "year": start_date.year,
                        "month": start_date.month,
                        "day": start_date.day,
                    },
                    "endDate": {
                        "year": end_date.year,
                        "month": end_date.month,
                        "day": end_date.day,
                    },
                }]
            }
        }

    while True:
        if page_token:
            body["pageToken"] = page_token

        resp = requests.post(
            f"{base_url}/mediaItems:search",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

        items = data.get("mediaItems", [])
        # Only include images (skip videos)
        image_items = [
            item for item in items
            if item.get("mimeType", "").startswith("image/")
        ]
        all_items.extend(image_items)

        page_count += 1
        if progress_callback:
            progress_callback(len(all_items), page_count)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

        # Rate limiting
        time.sleep(0.1)

    return all_items


def download_thumbnail(item, creds, size=256):
    """
    Download a thumbnail for a media item.
    
    Returns:
        (item_id, PIL.Image) or (item_id, None) on failure
    """
    item_id = item["id"]
    thumb_path = os.path.join(THUMBNAILS_DIR, f"{item_id}.jpg")

    # Use cached thumbnail if exists
    if os.path.exists(thumb_path):
        try:
            return item_id, Image.open(thumb_path)
        except Exception:
            pass

    try:
        url = f"{item['baseUrl']}=w{size}-h{size}"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        img.save(thumb_path, "JPEG", quality=85)
        return item_id, img
    except Exception as e:
        return item_id, None


def compute_hashes(img):
    """
    Compute multiple perceptual hashes for an image.
    
    Returns:
        dict with hash type -> hash string
    """
    return {
        "phash": str(imagehash.phash(img, hash_size=16)),
        "dhash": str(imagehash.dhash(img, hash_size=16)),
        "md5": hashlib.md5(img.tobytes()).hexdigest(),
    }


def scan_library(days=None, config=None):
    """
    Main scan function: fetch photos, download thumbnails, compute hashes.
    
    Args:
        days: If set, only scan photos from last N days
        config: Config dict
    
    Returns:
        (photo_index, hash_db) dicts
    """
    if config is None:
        config = load_json("config.json", {})

    ensure_dirs()
    
    max_workers = config.get("max_concurrent_downloads", 10)
    thumb_size = config.get("thumbnail_size", 256)

    # Load existing data for incremental scanning
    photo_index = load_json(PHOTO_INDEX_PATH, {})
    hash_db = load_json(HASH_DB_PATH, {})

    # Authenticate
    print("Authenticating...")
    creds = get_authenticated_service()

    # Fetch media items
    print(f"Fetching media items{f' (last {days} days)' if days else ''}...")
    
    def progress(count, pages):
        print(f"  Fetched {count} images across {pages} pages...", end="\r")

    items = fetch_all_media_items(creds, days=days, progress_callback=progress)
    print(f"\nFound {len(items)} images total.")

    # Determine which items are new
    new_items = [item for item in items if item["id"] not in hash_db]
    print(f"  {len(new_items)} new images to process.")

    if not new_items:
        print("No new images to process.")
        return photo_index, hash_db

    # Update photo index
    for item in items:
        photo_index[item["id"]] = {
            "id": item["id"],
            "filename": item.get("filename", "unknown"),
            "mimeType": item.get("mimeType", ""),
            "creationTime": item.get("mediaMetadata", {}).get("creationTime", ""),
            "baseUrl": item.get("baseUrl", ""),
            "productUrl": item.get("productUrl", ""),
            "width": item.get("mediaMetadata", {}).get("width", ""),
            "height": item.get("mediaMetadata", {}).get("height", ""),
        }

    # Download thumbnails and compute hashes
    print("Downloading thumbnails and computing hashes...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(download_thumbnail, item, creds, thumb_size): item
            for item in new_items
        }

        with tqdm(total=len(new_items), desc="Processing") as pbar:
            for future in as_completed(futures):
                item_id, img = future.result()
                if img is not None:
                    hashes = compute_hashes(img)
                    hash_db[item_id] = hashes
                else:
                    hash_db[item_id] = {"error": "download_failed"}
                pbar.update(1)

    # Save progress
    save_json(PHOTO_INDEX_PATH, photo_index)
    save_json(HASH_DB_PATH, hash_db)
    
    print(f"Scan complete. {len(hash_db)} images in database.")
    return photo_index, hash_db
