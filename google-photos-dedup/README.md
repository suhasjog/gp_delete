# Google Photos Duplicate Finder

Automatically scans your Google Photos library for duplicate and similar images using perceptual hashing, generates an HTML review report, and optionally helps delete flagged duplicates.

## Features

- **Exact duplicate detection** via file hash (MD5)
- **Similar image detection** via perceptual hashing (pHash, dHash) — catches resized, recompressed, and similar memes/screenshots
- **HTML review report** with side-by-side thumbnails for easy decision-making
- **Batch deletion helper** via Selenium browser automation
- **Incremental scanning** — only processes new photos on subsequent runs
- **Cron-friendly** for scheduled automation

## Setup

### 1. Google Cloud Project & OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable the **Photos Library API**:
   - Go to APIs & Services → Library
   - Search "Photos Library API" → Enable
4. Create OAuth 2.0 credentials:
   - Go to APIs & Services → Credentials
   - Click "Create Credentials" → "OAuth client ID"
   - Application type: **Desktop app**
   - Download the JSON file
   - Save it as `credentials.json` in this project folder

5. Configure the OAuth consent screen:
   - Go to APIs & Services → OAuth consent screen
   - Add your email as a test user (while in "Testing" mode)

### 2. Install Dependencies

```bash
cd google-photos-dedup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. First Run (Authentication)

```bash
python main.py scan
```

This will open a browser window for Google OAuth. Sign in and grant access. A `token.json` file will be saved for future runs.

### 4. Review Duplicates

After scanning, open the generated `report.html` in your browser to review flagged duplicates.

### 5. (Optional) Schedule with Cron

```bash
# Run weekly scan every Sunday at 2am
crontab -e
# Add:
0 2 * * 0 cd /path/to/google-photos-dedup && ./venv/bin/python main.py scan
```

## Usage

```bash
# Full scan (first time — will take a while for 50k+ photos)
python main.py scan

# Scan only photos from the last 7 days (faster for scheduled runs)
python main.py scan --days 7

# Generate report from existing scan data
python main.py report

# Open deletion helper (Selenium-based, requires Chrome)
python main.py delete --report report.html
```

## How It Works

1. **Scan**: Fetches photo metadata and thumbnails via Google Photos API
2. **Hash**: Computes perceptual hashes (pHash + dHash) for each image
3. **Compare**: Groups images by hash similarity (configurable threshold)
4. **Report**: Generates an HTML report with duplicate groups
5. **Delete** (optional): Uses Selenium to automate trash operations in Google Photos web UI

## Configuration

Edit `config.json` to adjust:

```json
{
  "similarity_threshold": 6,
  "scan_batch_size": 100,
  "thumbnail_size": 256,
  "max_concurrent_downloads": 10,
  "keep_strategy": "oldest"
}
```

- `similarity_threshold`: Hamming distance cutoff (0 = exact match, lower = stricter). Default 6 works well for memes/screenshots.
- `keep_strategy`: Which photo to recommend keeping — `oldest` or `newest`
