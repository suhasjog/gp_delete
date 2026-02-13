"""
Selenium-based deletion helper for Google Photos.

Opens flagged photos in Google Photos and assists with moving them to trash.
Requires Chrome and ChromeDriver.
"""

import json
import time
import sys

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from scanner import load_json, PHOTO_INDEX_PATH


def load_delete_list(path="delete_list.json"):
    """Load the delete list exported from the HTML report."""
    return load_json(path, [])


def create_driver(headless=False):
    """Create a Chrome WebDriver instance."""
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    # Use existing Chrome profile so we're already logged into Google
    options.add_argument("--user-data-dir=/tmp/chrome-photos-dedup")
    
    driver = webdriver.Chrome(options=options)
    return driver


def delete_photos_interactive(delete_list_path="delete_list.json"):
    """
    Interactive deletion helper.
    
    Opens each flagged photo in Google Photos and waits for user confirmation
    before moving to trash.
    """
    delete_list = load_delete_list(delete_list_path)
    photo_index = load_json(PHOTO_INDEX_PATH, {})

    if not delete_list:
        print("No items in delete list. Export from the HTML report first.")
        return

    print(f"\n{'='*60}")
    print(f"  Google Photos Deletion Helper")
    print(f"  {len(delete_list)} photos to delete")
    print(f"{'='*60}")
    print(f"\nThis will open Chrome and navigate to each photo.")
    print(f"You'll need to sign into Google Photos on the first run.")
    print(f"\nCommands during deletion:")
    print(f"  [Enter]  = Move current photo to trash")
    print(f"  [s]      = Skip this photo")
    print(f"  [q]      = Quit\n")

    input("Press Enter to start...")

    driver = create_driver()
    deleted = 0
    skipped = 0

    try:
        # Navigate to Google Photos first for login
        print("Opening Google Photos — please sign in if needed...")
        driver.get("https://photos.google.com")
        input("Press Enter once you're signed in to Google Photos...")

        for i, item in enumerate(delete_list):
            item_id = item["id"] if isinstance(item, dict) else item
            info = photo_index.get(item_id, {})
            product_url = info.get("productUrl", "")
            filename = info.get("filename", "unknown")

            if not product_url:
                print(f"  [{i+1}/{len(delete_list)}] Skipping {filename} — no URL")
                skipped += 1
                continue

            print(f"\n  [{i+1}/{len(delete_list)}] {filename}")
            print(f"  URL: {product_url}")

            driver.get(product_url)
            time.sleep(2)

            action = input("  [Enter]=Delete  [s]=Skip  [q]=Quit: ").strip().lower()

            if action == "q":
                print("Quitting.")
                break
            elif action == "s":
                skipped += 1
                continue
            else:
                # Try to delete via keyboard shortcut (Shift+D in Google Photos)
                try:
                    # Focus the page
                    body = driver.find_element(By.TAG_NAME, "body")
                    # Google Photos uses '#' key to move to trash
                    body.send_keys("#")
                    time.sleep(1)

                    # Look for the "Move to trash" confirmation button
                    try:
                        confirm_btn = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable(
                                (By.XPATH, "//button[contains(., 'Move to trash') or contains(., 'Move to Trash')]")
                            )
                        )
                        confirm_btn.click()
                        deleted += 1
                        print(f"  ✓ Moved to trash")
                        time.sleep(1)
                    except Exception:
                        # Try alternative: click the three-dot menu → Delete
                        print("  ⚠ Auto-delete failed. Please delete manually in the browser.")
                        input("  Press Enter when done...")
                        deleted += 1

                except Exception as e:
                    print(f"  ⚠ Error: {e}")
                    print("  Please delete manually in the browser.")
                    input("  Press Enter when done...")
                    deleted += 1

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        print(f"\n{'='*60}")
        print(f"  Done! Deleted: {deleted}, Skipped: {skipped}")
        print(f"  Remaining: {len(delete_list) - deleted - skipped}")
        print(f"{'='*60}")
        driver.quit()


def batch_open_urls(delete_list_path="delete_list.json", batch_size=10):
    """
    Open photos in batches in the browser for manual deletion.
    
    Alternative to the interactive mode — opens N tabs at a time
    for manual review and deletion.
    """
    delete_list = load_delete_list(delete_list_path)
    photo_index = load_json(PHOTO_INDEX_PATH, {})

    urls = []
    for item in delete_list:
        item_id = item["id"] if isinstance(item, dict) else item
        info = photo_index.get(item_id, {})
        url = info.get("productUrl", "")
        if url:
            urls.append(url)

    print(f"Opening {len(urls)} photos in batches of {batch_size}...")

    driver = create_driver()

    try:
        driver.get("https://photos.google.com")
        input("Sign in to Google Photos, then press Enter...")

        for i in range(0, len(urls), batch_size):
            batch = urls[i : i + batch_size]
            print(f"\nBatch {i // batch_size + 1}: Opening {len(batch)} photos...")

            for url in batch:
                driver.execute_script(f"window.open('{url}', '_blank');")
                time.sleep(0.5)

            print(f"Delete unwanted photos in the browser tabs.")
            input(f"Press Enter when done with this batch...")

            # Close all tabs except the first
            handles = driver.window_handles
            for handle in handles[1:]:
                driver.switch_to.window(handle)
                driver.close()
            driver.switch_to.window(handles[0])

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        driver.quit()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Delete flagged photos from Google Photos")
    parser.add_argument("--list", default="delete_list.json", help="Path to delete_list.json")
    parser.add_argument("--batch", action="store_true", help="Use batch mode (opens tabs)")
    parser.add_argument("--batch-size", type=int, default=10, help="Tabs per batch")
    args = parser.parse_args()

    if args.batch:
        batch_open_urls(args.list, args.batch_size)
    else:
        delete_photos_interactive(args.list)
