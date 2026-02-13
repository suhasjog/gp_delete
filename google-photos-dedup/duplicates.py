"""Find duplicate and similar images using perceptual hash comparison."""

import json
from collections import defaultdict
from itertools import combinations

import imagehash

from scanner import load_json, PHOTO_INDEX_PATH, HASH_DB_PATH


def hamming_distance(hash1_hex, hash2_hex):
    """Compute Hamming distance between two hex hash strings."""
    try:
        h1 = imagehash.hex_to_hash(hash1_hex)
        h2 = imagehash.hex_to_hash(hash2_hex)
        return h1 - h2
    except Exception:
        return float("inf")


def find_exact_duplicates(hash_db):
    """
    Find exact duplicates by MD5 hash.
    
    Returns:
        List of groups, each group is a list of item IDs sharing the same MD5.
    """
    md5_groups = defaultdict(list)
    
    for item_id, hashes in hash_db.items():
        md5 = hashes.get("md5")
        if md5:
            md5_groups[md5].append(item_id)

    # Only return groups with 2+ items
    return [group for group in md5_groups.values() if len(group) > 1]


def find_similar_images(hash_db, threshold=6, hash_type="phash"):
    """
    Find similar images using perceptual hash comparison.
    
    Uses a bucket-based approach for efficiency with large libraries:
    1. Group by exact hash (distance 0)
    2. For remaining, compare within nearby buckets
    
    Args:
        hash_db: Dict of item_id -> hash dict
        threshold: Max Hamming distance to consider similar
        hash_type: Which hash to use ('phash' or 'dhash')
    
    Returns:
        List of groups, where each group is a list of (item_id, distance_to_anchor) tuples.
    """
    # Step 1: Group by exact perceptual hash
    exact_groups = defaultdict(list)
    items_with_hashes = []
    
    for item_id, hashes in hash_db.items():
        h = hashes.get(hash_type)
        if h and "error" not in hashes:
            exact_groups[h].append(item_id)
            items_with_hashes.append((item_id, h))

    # Step 2: For efficiency with 50k+ images, use prefix bucketing
    # Group hashes by their first 4 hex chars and compare within/across nearby buckets
    prefix_buckets = defaultdict(list)
    for item_id, h in items_with_hashes:
        # Use first 4 chars as bucket key
        prefix = h[:4]
        prefix_buckets[prefix].append((item_id, h))

    # Union-Find for grouping
    parent = {}
    
    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    # Compare within exact groups first
    for h, group in exact_groups.items():
        if len(group) > 1:
            for i in range(1, len(group)):
                union(group[0], group[i])

    # Compare across prefix buckets for near-matches
    # This is O(n * bucket_size) instead of O(n^2)
    seen_pairs = set()
    all_prefixes = sorted(prefix_buckets.keys())
    
    print(f"Comparing {len(items_with_hashes)} images across {len(all_prefixes)} hash buckets...")
    
    for i, prefix in enumerate(all_prefixes):
        bucket = prefix_buckets[prefix]
        
        # Compare within this bucket
        for j in range(len(bucket)):
            for k in range(j + 1, len(bucket)):
                id_j, h_j = bucket[j]
                id_k, h_k = bucket[k]
                pair = tuple(sorted([id_j, id_k]))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    dist = hamming_distance(h_j, h_k)
                    if dist <= threshold:
                        union(id_j, id_k)

        # Compare with neighboring prefixes (handles boundary cases)
        for other_prefix in all_prefixes[i + 1 : i + 3]:
            other_bucket = prefix_buckets[other_prefix]
            for id_j, h_j in bucket:
                for id_k, h_k in other_bucket:
                    pair = tuple(sorted([id_j, id_k]))
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        dist = hamming_distance(h_j, h_k)
                        if dist <= threshold:
                            union(id_j, id_k)

    # Collect groups
    groups = defaultdict(list)
    for item_id, h in items_with_hashes:
        root = find(item_id)
        groups[root].append(item_id)

    # Return only groups with duplicates, sorted by size
    dup_groups = [g for g in groups.values() if len(g) > 1]
    dup_groups.sort(key=len, reverse=True)
    
    return dup_groups


def find_all_duplicates(threshold=6, config=None):
    """
    Run all duplicate detection methods and merge results.
    
    Returns:
        List of duplicate groups with metadata.
    """
    if config is None:
        config = load_json("config.json", {})

    hash_db = load_json(HASH_DB_PATH, {})
    photo_index = load_json(PHOTO_INDEX_PATH, {})

    if not hash_db:
        print("No hash data found. Run 'scan' first.")
        return []

    threshold = config.get("similarity_threshold", threshold)
    keep_strategy = config.get("keep_strategy", "oldest")

    print(f"Searching for duplicates (threshold={threshold})...")

    # Find exact duplicates
    exact_groups = find_exact_duplicates(hash_db)
    print(f"  Found {len(exact_groups)} groups of exact duplicates")

    # Find similar images
    similar_groups = find_similar_images(hash_db, threshold=threshold)
    print(f"  Found {len(similar_groups)} groups of similar images")

    # Merge (similar_groups already includes exact matches via union-find)
    # Enrich with metadata
    result_groups = []
    for group_ids in similar_groups:
        group = []
        for item_id in group_ids:
            info = photo_index.get(item_id, {})
            hashes = hash_db.get(item_id, {})
            group.append({
                "id": item_id,
                "filename": info.get("filename", "unknown"),
                "creationTime": info.get("creationTime", ""),
                "productUrl": info.get("productUrl", ""),
                "width": info.get("width", ""),
                "height": info.get("height", ""),
                "phash": hashes.get("phash", ""),
                "md5": hashes.get("md5", ""),
            })

        # Sort by creation time
        group.sort(key=lambda x: x.get("creationTime", ""))

        # Mark which to keep vs delete
        if keep_strategy == "oldest":
            keep_idx = 0
        else:
            keep_idx = len(group) - 1

        for i, item in enumerate(group):
            item["action"] = "keep" if i == keep_idx else "delete"

        # Compute pairwise distances for the group
        if len(group) <= 10:  # Only for small groups
            distances = {}
            for i, j in combinations(range(len(group)), 2):
                h1 = group[i].get("phash", "")
                h2 = group[j].get("phash", "")
                if h1 and h2:
                    distances[f"{i}-{j}"] = hamming_distance(h1, h2)
            group_info = {"max_distance": max(distances.values()) if distances else 0}
        else:
            group_info = {"max_distance": "N/A (large group)"}

        result_groups.append({
            "items": group,
            "size": len(group),
            "is_exact": all(
                g.get("md5") == group[0].get("md5") for g in group if g.get("md5")
            ),
            **group_info,
        })

    # Sort: exact dupes first, then by group size
    result_groups.sort(key=lambda g: (not g["is_exact"], -g["size"]))

    print(f"\nTotal: {len(result_groups)} duplicate groups, "
          f"{sum(g['size'] - 1 for g in result_groups)} photos flagged for deletion")

    return result_groups
