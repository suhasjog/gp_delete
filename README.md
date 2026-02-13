# Google Photos Duplicate Detector

Automatically finds duplicate and similar photos/memes in your Google Photos library using perceptual hashing, then generates an interactive HTML report for review.

## Features

- **Exact duplicate detection** — MD5 hash matching for identical files
- **Similar image detection** — Perceptual hashing (pHash + dHash) catches memes, screenshots, and resized copies
- **Incremental scanning** — After first run, only processes new photos (important for 50k+ libraries)
- **Interactive HTML report** — Side-by-side comparison with one-click selection
- **Scheduled runs** — Weekly via macOS launchd

## Setup (One-Time)

### 1. Install Python dependencies

```bash
cd google-photos-dedup
pip3 install -r requirements.txt
```

### 2. Create Google Cloud OAuth credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Enable the **Photos Library API**:
   - Go to **APIs & Services → Library**
   - Search for "Photos Library API" and click **Enable**
4. Create OAuth credentials:
   - Go to **APIs & Services → Credentials**
   - Click **+ Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Download the JSON file
5. Rename the downloaded file to `credentials.json` and place it in this project folder

### 3. First run (full scan)

```bash
python3 dedup.py --full-scan
```

- A browser window will open for Google OAuth — sign in and grant read-only access
- The first scan of 50k+ photos will take **1-3 hours** depending on your connection
- Progress is logged to the terminal
- Results are stored in `photos.db` so subsequent runs are fast

### 4. Review the report

After scanning completes, open the generated report:

```bash
open reports/duplicates_YYYYMMDD_HHMMSS.html
```

In the report you can:
- **Click photos** to mark them for deletion (red border = delete, green = keep)
- **"Auto-select duplicates"** — automatically selects all but the oldest in each group
- **"Open ↗"** — opens the photo in Google Photos for closer inspection
- **Filter** between exact matches and similar photos
- **"Export Selection as JSON"** — downloads a list of photo IDs to delete

### 5. Delete duplicates

Since the Google Photos API doesn't support deletion, you have two options:

**Option A: Manual deletion via Google Photos**
- Use the report to identify duplicates
- Click "Open ↗" on each duplicate to open it in Google Photos
- Delete from there

**Option B: Use the exported JSON with browser automation** (advanced)
- Export the selection JSON from the report
- Use a browser automation script to open each photo and delete it
- *(An automated deletion script can be added later if needed)*

## Scheduling Weekly Scans

### Set up the launchd job

1. Edit `com.user.google-photos-dedup.plist`:
   - Replace `/Users/YOUR_USERNAME/google-photos-dedup` with the actual path
   - Replace `/usr/local/bin/python3` with the output of `which python3`

2. Install the schedule:
```bash
cp com.user.google-photos-dedup.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.user.google-photos-dedup.plist
```

3. Verify it's loaded:
```bash
launchctl list | grep dedup
```

### To run manually anytime:
```bash
python3 dedup.py
```

### To uninstall the schedule:
```bash
launchctl unload ~/Library/LaunchAgents/com.user.google-photos-dedup.plist
rm ~/Library/LaunchAgents/com.user.google-photos-dedup.plist
```

## Configuration

Edit the constants at the top of `dedup.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `HASH_SIZE` | 16 | Perceptual hash size. Higher = more precise but slower |
| `SIMILARITY_THRESHOLD` | 10 | Hamming distance for "similar" match. Lower = stricter |
| `DOWNLOAD_THREADS` | 8 | Parallel download threads for thumbnails |
| `BATCH_SIZE` | 100 | Google API page size (max 100) |

### Tuning the similarity threshold

- **5 or below** — Only very close matches (nearly identical photos)
- **10** (default) — Good balance for memes and screenshots
- **15+** — Catches loosely similar images (may have false positives)

You can experiment without re-scanning:
```bash
python3 dedup.py --report-only --threshold 8
```

## File Structure

```
google-photos-dedup/
├── dedup.py                              # Main script
├── requirements.txt                      # Python dependencies
├── credentials.json                      # Google OAuth credentials (you provide)
├── token.json                            # Auto-generated auth token
├── photos.db                             # SQLite database of scanned photos
├── reports/                              # Generated HTML reports
│   └── duplicates_YYYYMMDD_HHMMSS.html
├── com.user.google-photos-dedup.plist    # macOS launchd schedule
└── README.md                             # This file
```

## Troubleshooting

**"Token has been expired or revoked"**
- Delete `token.json` and run again — it will re-authenticate

**Images show "Expired" in the report**
- Google Photos base URLs expire after ~1 hour
- Regenerate the report: `python3 dedup.py --report-only`

**Too many false positives**
- Lower the threshold: `python3 dedup.py --report-only --threshold 5`

**First scan is very slow**
- This is normal for 50k+ photos — it needs to download thumbnails
- Subsequent runs only scan new photos and will be much faster
