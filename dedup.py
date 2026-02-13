#!/usr/bin/env python3
"""
Google Photos Duplicate Detector
Scans your Google Photos library using perceptual hashing to find
exact and near-duplicate images, then generates an HTML review report.

Supports incremental scanning for large libraries (50k+ photos).
"""

import os
import io
import json
import time
import hashlib
import logging
import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import imagehash
from PIL import Image
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# --- Configuration ---
SCOPES = ["https://www.googleapis.com/auth/photoslibrary.readonly"]
DB_PATH = Path(__file__).parent / "photos.db"
CREDENTIALS_PATH = Path(__file__).parent / "credentials.json"
TOKEN_PATH = Path(__file__).parent / "token.json"
REPORT_DIR = Path(__file__).parent / "reports"
CACHE_DIR = Path(__file__).parent / "cache"
HASH_SIZE = 16  # Higher = more precise perceptual hash
SIMILARITY_THRESHOLD = 10  # Hamming distance; lower = stricter matching
BATCH_SIZE = 100  # Google API page size (max 100)
DOWNLOAD_THREADS = 8  # Parallel thumbnail downloads
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("dedup")


# ============================================================
# Database Layer — stores photo metadata + hashes for incremental runs
# ============================================================

def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            id TEXT PRIMARY KEY,
            filename TEXT,
            mime_type TEXT,
            creation_time TEXT,
            width INTEGER,
            height INTEGER,
            base_url TEXT,
            product_url TEXT,
            phash TEXT,
            dhash TEXT,
            md5 TEXT,
            scanned_at TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_phash ON photos(phash)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_dhash ON photos(dhash)
    """)
    conn.commit()
    return conn


# ============================================================
# Google Photos API Authentication
# ============================================================

def authenticate() -> Credentials:
    """Authenticate with Google Photos API using OAuth2."""
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired token...")
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                logger.error(
                    f"Missing {CREDENTIALS_PATH}. Download OAuth2 credentials from "
                    "Google Cloud Console → APIs & Services → Credentials."
                )
                raise FileNotFoundError(f"{CREDENTIALS_PATH} not found")

            logger.info("Starting OAuth2 flow (browser will open)...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        logger.info("Token saved.")

    return creds


# ============================================================
# Photo Listing — paginated, with incremental support
# ============================================================

def list_all_photos(service, conn: sqlite3.Connection, full_scan: bool = False):
    """
    Fetch all photo metadata from Google Photos.
    If not full_scan, only fetches photos not already in the DB.
    """
    existing_ids = set()
    if not full_scan:
        cursor = conn.execute("SELECT id FROM photos")
        existing_ids = {row[0] for row in cursor.fetchall()}
        logger.info(f"Found {len(existing_ids)} previously scanned photos in DB.")

    page_token = None
    total_fetched = 0
    new_photos = []

    while True:
        body = {"pageSize": BATCH_SIZE}
        if page_token:
            body["pageToken"] = page_token

        try:
            response = service.mediaItems().list(**body).execute()
        except Exception as e:
            logger.error(f"API error listing photos: {e}")
            time.sleep(5)
            continue

        items = response.get("mediaItems", [])
        total_fetched += len(items)

        for item in items:
            if item["id"] not in existing_ids:
                # Only process images, skip videos
                if item.get("mimeType", "").startswith("image/"):
                    new_photos.append(item)

        logger.info(f"Fetched {total_fetched} items from API ({len(new_photos)} new images)...")

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    logger.info(f"Total: {total_fetched} items in library, {len(new_photos)} new images to scan.")
    return new_photos


# ============================================================
# Thumbnail Download & Hashing
# ============================================================

def download_and_hash(item: dict) -> dict | None:
    """Download a thumbnail and compute perceptual + MD5 hashes."""
    import requests

    media_id = item["id"]
    # Request a 512px thumbnail — good enough for perceptual hashing
    base_url = item.get("baseUrl", "")
    thumb_url = f"{base_url}=w512-h512"

    try:
        resp = requests.get(thumb_url, timeout=30)
        resp.raise_for_status()
        img_bytes = resp.content

        img = Image.open(io.BytesIO(img_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")

        phash = str(imagehash.phash(img, hash_size=HASH_SIZE))
        dhash = str(imagehash.dhash(img, hash_size=HASH_SIZE))
        md5 = hashlib.md5(img_bytes).hexdigest()

        metadata = item.get("mediaMetadata", {})
        return {
            "id": media_id,
            "filename": item.get("filename", ""),
            "mime_type": item.get("mimeType", ""),
            "creation_time": metadata.get("creationTime", ""),
            "width": int(metadata.get("width", 0)),
            "height": int(metadata.get("height", 0)),
            "base_url": base_url,
            "product_url": item.get("productUrl", ""),
            "phash": phash,
            "dhash": dhash,
            "md5": md5,
            "scanned_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.warning(f"Failed to process {item.get('filename', media_id)}: {e}")
        return None


def scan_photos(photos: list, conn: sqlite3.Connection):
    """Download thumbnails and compute hashes in parallel, storing results in DB."""
    logger.info(f"Scanning {len(photos)} new photos with {DOWNLOAD_THREADS} threads...")

    processed = 0
    batch = []

    with ThreadPoolExecutor(max_workers=DOWNLOAD_THREADS) as executor:
        futures = {executor.submit(download_and_hash, p): p for p in photos}

        for future in as_completed(futures):
            result = future.result()
            if result:
                batch.append(result)

            processed += 1
            if processed % 100 == 0:
                logger.info(f"  Processed {processed}/{len(photos)}...")

            # Batch insert every 500 items
            if len(batch) >= 500:
                _insert_batch(conn, batch)
                batch = []

    if batch:
        _insert_batch(conn, batch)

    logger.info(f"Scanning complete. {processed} photos processed.")


def _insert_batch(conn: sqlite3.Connection, batch: list):
    conn.executemany(
        """
        INSERT OR REPLACE INTO photos
        (id, filename, mime_type, creation_time, width, height,
         base_url, product_url, phash, dhash, md5, scanned_at)
        VALUES (:id, :filename, :mime_type, :creation_time, :width, :height,
                :base_url, :product_url, :phash, :dhash, :md5, :scanned_at)
        """,
        batch,
    )
    conn.commit()


# ============================================================
# Duplicate Detection
# ============================================================

def hex_to_hash(hex_str: str) -> imagehash.ImageHash:
    """Convert hex string back to ImageHash for comparison."""
    return imagehash.hex_to_hash(hex_str)


def find_duplicates(conn: sqlite3.Connection, threshold: int = SIMILARITY_THRESHOLD) -> list:
    """
    Find duplicate groups using perceptual hash similarity.
    Returns list of groups, each group is a list of photo dicts.
    """
    logger.info("Finding duplicates...")

    cursor = conn.execute(
        "SELECT id, filename, creation_time, width, height, product_url, phash, dhash, md5 "
        "FROM photos ORDER BY creation_time"
    )
    all_photos = cursor.fetchall()
    columns = ["id", "filename", "creation_time", "width", "height", "product_url", "phash", "dhash", "md5"]

    # --- Pass 1: Exact MD5 duplicates ---
    md5_groups = defaultdict(list)
    for row in all_photos:
        photo = dict(zip(columns, row))
        md5_groups[photo["md5"]].append(photo)

    exact_dupes = {k: v for k, v in md5_groups.items() if len(v) > 1}
    logger.info(f"Found {len(exact_dupes)} exact duplicate groups (MD5 match).")

    # --- Pass 2: Perceptual hash similarity (for memes/screenshots) ---
    # Use Union-Find for grouping
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    photo_map = {}
    hash_index = defaultdict(list)  # phash -> list of photo ids

    for row in all_photos:
        photo = dict(zip(columns, row))
        pid = photo["id"]
        parent[pid] = pid
        photo_map[pid] = photo
        hash_index[photo["phash"]].append(pid)

    # First, group exact phash matches (fast)
    for phash, ids in hash_index.items():
        if len(ids) > 1:
            for i in range(1, len(ids)):
                union(ids[0], ids[i])

    # Then, compare across different phashes using hamming distance
    # For efficiency with 50k+ photos, we bucket by phash prefix
    prefix_len = 8  # First 8 hex chars as bucket key
    buckets = defaultdict(list)
    unique_hashes = {}

    for row in all_photos:
        photo = dict(zip(columns, row))
        pid = photo["id"]
        phash_str = photo["phash"]
        prefix = phash_str[:prefix_len]

        # Check against all photos in nearby buckets
        for existing_id, existing_hash_str in buckets.get(prefix, []):
            if existing_id == pid:
                continue
            h1 = hex_to_hash(phash_str)
            h2 = hex_to_hash(existing_hash_str)
            distance = h1 - h2
            if distance <= threshold:
                union(pid, existing_id)

        buckets[prefix].append((pid, phash_str))

    # Build groups
    groups = defaultdict(list)
    for pid in photo_map:
        root = find(pid)
        groups[root].append(photo_map[pid])

    # Filter to groups with 2+ members
    duplicate_groups = [g for g in groups.values() if len(g) > 1]

    # Sort groups: exact MD5 matches first, then by group size
    for group in duplicate_groups:
        group.sort(key=lambda p: p["creation_time"] or "")

    duplicate_groups.sort(key=lambda g: len(g), reverse=True)

    total_dupes = sum(len(g) - 1 for g in duplicate_groups)
    logger.info(
        f"Found {len(duplicate_groups)} duplicate groups "
        f"({total_dupes} photos that could be removed)."
    )

    return duplicate_groups


# ============================================================
# HTML Report Generation
# ============================================================

def generate_report(duplicate_groups: list, conn: sqlite3.Connection) -> Path:
    """Generate an HTML report with side-by-side duplicate comparisons."""
    REPORT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"duplicates_{timestamp}.html"

    # Refresh base URLs (they expire after ~1hr)
    # We'll use product_url links instead for the report
    total_dupes = sum(len(g) - 1 for g in duplicate_groups)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Google Photos Duplicate Report — {timestamp}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f0f0f; color: #e0e0e0; padding: 24px;
  }}
  .header {{
    text-align: center; padding: 32px 0; border-bottom: 1px solid #333;
    margin-bottom: 32px;
  }}
  .header h1 {{ font-size: 28px; color: #fff; margin-bottom: 8px; }}
  .header .stats {{ color: #888; font-size: 15px; }}
  .stats span {{ color: #f59e0b; font-weight: 600; }}
  .controls {{
    position: sticky; top: 0; z-index: 100; background: #1a1a1a;
    padding: 16px 24px; border-radius: 12px; margin-bottom: 24px;
    display: flex; justify-content: space-between; align-items: center;
    border: 1px solid #333;
  }}
  .controls button {{
    background: #f59e0b; color: #000; border: none; padding: 10px 20px;
    border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 14px;
  }}
  .controls button:hover {{ background: #d97706; }}
  .controls button.danger {{ background: #ef4444; color: #fff; }}
  .controls button.danger:hover {{ background: #dc2626; }}
  .controls .selected-count {{ font-size: 14px; color: #888; }}
  .group {{
    background: #1a1a1a; border-radius: 16px; padding: 24px;
    margin-bottom: 20px; border: 1px solid #2a2a2a;
  }}
  .group-header {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 16px;
  }}
  .group-header h3 {{ font-size: 16px; color: #ccc; }}
  .group-header .badge {{
    background: #f59e0b22; color: #f59e0b; padding: 4px 12px;
    border-radius: 20px; font-size: 13px; font-weight: 600;
  }}
  .group-header .badge.exact {{ background: #ef444422; color: #ef4444; }}
  .photos {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 16px;
  }}
  .photo-card {{
    position: relative; border-radius: 12px; overflow: hidden;
    border: 2px solid transparent; cursor: pointer; transition: all 0.2s;
  }}
  .photo-card:hover {{ border-color: #555; }}
  .photo-card.selected {{ border-color: #ef4444; }}
  .photo-card.keep {{ border-color: #22c55e; }}
  .photo-card img {{
    width: 100%; aspect-ratio: 1; object-fit: cover; display: block;
  }}
  .photo-meta {{
    padding: 10px 12px; background: #111; font-size: 12px;
  }}
  .photo-meta .filename {{
    color: #ccc; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; margin-bottom: 4px;
  }}
  .photo-meta .details {{ color: #666; }}
  .photo-card .keep-badge {{
    position: absolute; top: 8px; left: 8px; background: #22c55e;
    color: #fff; font-size: 11px; font-weight: 700; padding: 3px 8px;
    border-radius: 6px;
  }}
  .photo-card .select-badge {{
    position: absolute; top: 8px; right: 8px; background: #ef4444;
    color: #fff; font-size: 11px; font-weight: 700; padding: 3px 8px;
    border-radius: 6px; display: none;
  }}
  .photo-card.selected .select-badge {{ display: block; }}
  .photo-card a.open-link {{
    position: absolute; bottom: 52px; right: 8px; background: #ffffff22;
    color: #fff; font-size: 11px; padding: 4px 8px; border-radius: 6px;
    text-decoration: none; opacity: 0; transition: opacity 0.2s;
  }}
  .photo-card:hover a.open-link {{ opacity: 1; }}
  .filter-bar {{ display: flex; gap: 8px; }}
  .filter-bar button {{
    background: #2a2a2a; color: #ccc; border: 1px solid #444;
    padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px;
  }}
  .filter-bar button.active {{ background: #f59e0b; color: #000; border-color: #f59e0b; }}
</style>
</head>
<body>

<div class="header">
  <h1>📸 Duplicate Photo Report</h1>
  <p class="stats">
    Generated {datetime.now().strftime("%B %d, %Y at %I:%M %p")}<br>
    <span>{len(duplicate_groups)}</span> duplicate groups &middot;
    <span>{total_dupes}</span> potential duplicates to remove
  </p>
</div>

<div class="controls">
  <div class="filter-bar">
    <button class="active" onclick="filterGroups('all')">All ({len(duplicate_groups)})</button>
    <button onclick="filterGroups('exact')">Exact Matches</button>
    <button onclick="filterGroups('similar')">Similar</button>
  </div>
  <div>
    <span class="selected-count"><span id="selectedCount">0</span> selected for deletion</span>
    &nbsp;
    <button onclick="autoSelectDupes()">Auto-select duplicates (keep oldest)</button>
    &nbsp;
    <button class="danger" onclick="exportSelected()">Export Selection as JSON</button>
  </div>
</div>
"""

    for i, group in enumerate(duplicate_groups):
        # Determine if exact match (all same MD5)
        md5s = set(p["md5"] for p in group)
        is_exact = len(md5s) == 1
        badge_class = "exact" if is_exact else ""
        badge_text = "Exact Match" if is_exact else "Similar"

        html += f"""
<div class="group" data-type="{'exact' if is_exact else 'similar'}">
  <div class="group-header">
    <h3>Group {i + 1} — {len(group)} photos</h3>
    <span class="badge {badge_class}">{badge_text}</span>
  </div>
  <div class="photos">
"""
        for j, photo in enumerate(group):
            created = photo.get("creation_time", "Unknown")[:10]
            dims = f"{photo.get('width', '?')}×{photo.get('height', '?')}"
            keep_class = "keep" if j == 0 else ""
            keep_badge = '<span class="keep-badge">KEEP</span>' if j == 0 else ""
            product_url = photo.get("product_url", "#")

            html += f"""
    <div class="photo-card {keep_class}"
         data-id="{photo['id']}" data-group="{i}"
         onclick="toggleSelect(this)">
      {keep_badge}
      <span class="select-badge">DELETE</span>
      <a class="open-link" href="{product_url}" target="_blank"
         onclick="event.stopPropagation()">Open ↗</a>
      <img src="{photo.get('base_url', '')}=w300-h300-c"
           alt="{photo.get('filename', '')}"
           loading="lazy"
           onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 300 300%22><rect fill=%22%23333%22 width=%22300%22 height=%22300%22/><text x=%2250%%25%22 y=%2250%%25%22 text-anchor=%22middle%22 fill=%22%23666%22 font-size=%2214%22>Expired</text></svg>'">
      <div class="photo-meta">
        <div class="filename">{photo.get('filename', 'Unknown')}</div>
        <div class="details">{created} · {dims}</div>
      </div>
    </div>
"""

        html += "  </div>\n</div>\n"

    html += """
<script>
const selectedIds = new Set();

function toggleSelect(card) {
  const id = card.dataset.id;
  if (card.classList.contains('keep')) {
    // Don't allow selecting the "keep" photo
    return;
  }
  card.classList.toggle('selected');
  if (card.classList.contains('selected')) {
    selectedIds.add(id);
  } else {
    selectedIds.delete(id);
  }
  document.getElementById('selectedCount').textContent = selectedIds.size;
}

function autoSelectDupes() {
  // Select all but the first (oldest) in each group
  document.querySelectorAll('.group').forEach(group => {
    const cards = group.querySelectorAll('.photo-card');
    cards.forEach((card, i) => {
      if (i > 0 && !card.classList.contains('selected')) {
        card.classList.add('selected');
        selectedIds.add(card.dataset.id);
      }
    });
  });
  document.getElementById('selectedCount').textContent = selectedIds.size;
}

function filterGroups(type) {
  document.querySelectorAll('.filter-bar button').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  document.querySelectorAll('.group').forEach(g => {
    if (type === 'all') { g.style.display = ''; }
    else { g.style.display = g.dataset.type === type ? '' : 'none'; }
  });
}

function exportSelected() {
  const data = JSON.stringify([...selectedIds], null, 2);
  const blob = new Blob([data], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'photos_to_delete.json';
  a.click();
  URL.revokeObjectURL(url);
}
</script>
</body>
</html>
"""

    with open(report_path, "w") as f:
        f.write(html)

    logger.info(f"Report saved to {report_path}")
    return report_path


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Google Photos Duplicate Detector")
    parser.add_argument(
        "--full-scan", action="store_true",
        help="Re-scan entire library (ignore previously scanned photos)"
    )
    parser.add_argument(
        "--threshold", type=int, default=SIMILARITY_THRESHOLD,
        help=f"Similarity threshold for perceptual hashing (default: {SIMILARITY_THRESHOLD})"
    )
    parser.add_argument(
        "--report-only", action="store_true",
        help="Skip scanning, just regenerate report from existing DB"
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Google Photos Duplicate Detector")
    logger.info("=" * 60)

    conn = init_db()

    if not args.report_only:
        creds = authenticate()
        service = build("photoslibrary", "v1", credentials=creds, static_discovery=False)

        photos = list_all_photos(service, conn, full_scan=args.full_scan)

        if photos:
            scan_photos(photos, conn)
        else:
            logger.info("No new photos to scan.")

    duplicate_groups = find_duplicates(conn, threshold=args.threshold)

    if duplicate_groups:
        report_path = generate_report(duplicate_groups, conn)
        logger.info(f"\n✅ Done! Open the report to review duplicates:")
        logger.info(f"   open {report_path}")
    else:
        logger.info("\n✅ No duplicates found!")

    conn.close()


if __name__ == "__main__":
    main()
