"""Generate an HTML report for reviewing duplicate groups."""

import os
import json
import base64
from datetime import datetime

from scanner import load_json, THUMBNAILS_DIR


def thumbnail_to_base64(item_id):
    """Load thumbnail and return as base64 data URI."""
    path = os.path.join(THUMBNAILS_DIR, f"{item_id}.jpg")
    if os.path.exists(path):
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"
    return ""


def generate_report(duplicate_groups, output_path="report.html"):
    """
    Generate an interactive HTML report showing duplicate groups.
    
    Args:
        duplicate_groups: Output from find_all_duplicates()
        output_path: Where to save the HTML file
    """
    total_dupes = sum(g["size"] - 1 for g in duplicate_groups)
    exact_count = sum(1 for g in duplicate_groups if g["is_exact"])
    similar_count = len(duplicate_groups) - exact_count

    # Build HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Google Photos Duplicate Report</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #0f0f0f;
        color: #e0e0e0;
        padding: 20px;
    }}
    .header {{
        text-align: center;
        padding: 30px 20px;
        margin-bottom: 30px;
        background: #1a1a2e;
        border-radius: 12px;
        border: 1px solid #2a2a4a;
    }}
    .header h1 {{ color: #fff; font-size: 28px; margin-bottom: 10px; }}
    .stats {{
        display: flex;
        justify-content: center;
        gap: 30px;
        margin-top: 15px;
    }}
    .stat {{
        text-align: center;
        padding: 10px 20px;
        background: #252545;
        border-radius: 8px;
    }}
    .stat .number {{ font-size: 32px; font-weight: bold; color: #7c83ff; }}
    .stat .label {{ font-size: 12px; color: #888; margin-top: 4px; }}
    
    .controls {{
        display: flex;
        gap: 10px;
        margin-bottom: 20px;
        flex-wrap: wrap;
    }}
    .controls button {{
        padding: 8px 16px;
        border: 1px solid #444;
        background: #222;
        color: #ddd;
        border-radius: 6px;
        cursor: pointer;
        font-size: 13px;
    }}
    .controls button:hover {{ background: #333; }}
    .controls button.active {{ background: #7c83ff; color: #fff; border-color: #7c83ff; }}
    
    .group {{
        background: #1a1a1a;
        border: 1px solid #333;
        border-radius: 12px;
        margin-bottom: 20px;
        overflow: hidden;
    }}
    .group-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 20px;
        background: #222;
        border-bottom: 1px solid #333;
    }}
    .group-header .badge {{
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
    }}
    .badge-exact {{ background: #ff4444; color: #fff; }}
    .badge-similar {{ background: #ff9800; color: #fff; }}
    .group-header .group-info {{ font-size: 13px; color: #888; }}
    
    .group-items {{
        display: flex;
        flex-wrap: wrap;
        padding: 15px;
        gap: 15px;
    }}
    .item {{
        flex: 0 0 auto;
        width: 220px;
        border: 2px solid #333;
        border-radius: 8px;
        overflow: hidden;
        transition: border-color 0.2s;
        position: relative;
    }}
    .item.keep {{ border-color: #4caf50; }}
    .item.delete {{ border-color: #f44336; }}
    .item img {{
        width: 100%;
        height: 180px;
        object-fit: cover;
        display: block;
        cursor: pointer;
    }}
    .item-info {{
        padding: 8px 10px;
        font-size: 11px;
        background: #111;
    }}
    .item-info .filename {{
        font-weight: 600;
        color: #ddd;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    .item-info .meta {{ color: #777; margin-top: 3px; }}
    .item-actions {{
        display: flex;
        gap: 4px;
        padding: 6px 10px;
        background: #111;
        border-top: 1px solid #222;
    }}
    .item-actions button {{
        flex: 1;
        padding: 5px;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-size: 11px;
        font-weight: 600;
    }}
    .btn-keep {{ background: #1b5e20; color: #81c784; }}
    .btn-keep:hover {{ background: #2e7d32; }}
    .btn-delete {{ background: #b71c1c; color: #ef9a9a; }}
    .btn-delete:hover {{ background: #c62828; }}
    .btn-open {{ background: #1a237e; color: #9fa8da; }}
    .btn-open:hover {{ background: #283593; }}
    
    .action-label {{
        position: absolute;
        top: 8px;
        right: 8px;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: bold;
        text-transform: uppercase;
    }}
    .action-label.keep {{ background: #4caf50; color: #fff; }}
    .action-label.delete {{ background: #f44336; color: #fff; }}
    
    .export-bar {{
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: #1a1a2e;
        border-top: 2px solid #7c83ff;
        padding: 12px 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        z-index: 100;
    }}
    .export-bar .summary {{ font-size: 14px; }}
    .export-bar button {{
        padding: 10px 24px;
        background: #7c83ff;
        color: #fff;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        font-weight: 600;
        font-size: 14px;
    }}
    .export-bar button:hover {{ background: #6a71e0; }}
    
    .spacer {{ height: 70px; }}
</style>
</head>
<body>

<div class="header">
    <h1>📸 Duplicate Photos Report</h1>
    <p style="color:#888">Generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
    <div class="stats">
        <div class="stat">
            <div class="number">{len(duplicate_groups)}</div>
            <div class="label">Duplicate Groups</div>
        </div>
        <div class="stat">
            <div class="number">{total_dupes}</div>
            <div class="label">Photos to Review</div>
        </div>
        <div class="stat">
            <div class="number">{exact_count}</div>
            <div class="label">Exact Duplicates</div>
        </div>
        <div class="stat">
            <div class="number">{similar_count}</div>
            <div class="label">Similar Images</div>
        </div>
    </div>
</div>

<div class="controls">
    <button class="active" onclick="filterGroups('all')">All Groups</button>
    <button onclick="filterGroups('exact')">Exact Only</button>
    <button onclick="filterGroups('similar')">Similar Only</button>
    <span style="margin-left:auto; color:#888; font-size:13px; padding:8px;">
        Click thumbnails to view full size in Google Photos
    </span>
</div>

<div id="groups">
"""

    for i, group in enumerate(duplicate_groups):
        group_type = "exact" if group["is_exact"] else "similar"
        badge_class = "badge-exact" if group["is_exact"] else "badge-similar"
        badge_text = "Exact Match" if group["is_exact"] else f"Similar (dist ≤ {group.get('max_distance', '?')})"

        html += f"""
<div class="group" data-type="{group_type}" id="group-{i}">
    <div class="group-header">
        <div>
            <span class="badge {badge_class}">{badge_text}</span>
            <span class="group-info" style="margin-left:10px">{group['size']} photos in group</span>
        </div>
        <div class="group-info">Group #{i + 1}</div>
    </div>
    <div class="group-items">
"""
        for item in group["items"]:
            action = item.get("action", "delete")
            thumb_b64 = thumbnail_to_base64(item["id"])
            product_url = item.get("productUrl", "#")
            creation = item.get("creationTime", "Unknown date")
            if "T" in str(creation):
                creation = creation.split("T")[0]
            dimensions = ""
            if item.get("width") and item.get("height"):
                dimensions = f"{item['width']}×{item['height']}"

            html += f"""
        <div class="item {action}" data-id="{item['id']}" data-group="{i}">
            <span class="action-label {action}">{action}</span>
            <img src="{thumb_b64}" alt="{item['filename']}"
                 onclick="window.open('{product_url}', '_blank')"
                 onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22220%22 height=%22180%22><rect fill=%22%23333%22 width=%22220%22 height=%22180%22/><text fill=%22%23666%22 x=%2250%25%22 y=%2250%25%22 text-anchor=%22middle%22>No preview</text></svg>'">
            <div class="item-info">
                <div class="filename" title="{item['filename']}">{item['filename']}</div>
                <div class="meta">{creation} {(' · ' + dimensions) if dimensions else ''}</div>
            </div>
            <div class="item-actions">
                <button class="btn-keep" onclick="setAction(this, 'keep')">✓ Keep</button>
                <button class="btn-delete" onclick="setAction(this, 'delete')">✗ Delete</button>
                <button class="btn-open" onclick="window.open('{product_url}', '_blank')">↗</button>
            </div>
        </div>
"""

        html += """
    </div>
</div>
"""

    html += """
</div>

<div class="spacer"></div>

<div class="export-bar">
    <div class="summary" id="summary">
        Review items above, then export your decisions.
    </div>
    <div>
        <button onclick="exportDecisions()" style="margin-right:8px">Export Delete List (JSON)</button>
        <button onclick="exportUrls()" style="background:#444">Copy Google Photos URLs</button>
    </div>
</div>

<script>
function setAction(btn, action) {
    const item = btn.closest('.item');
    item.className = 'item ' + action;
    item.querySelector('.action-label').className = 'action-label ' + action;
    item.querySelector('.action-label').textContent = action;
    updateSummary();
}

function filterGroups(type) {
    document.querySelectorAll('.controls button').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
    
    document.querySelectorAll('.group').forEach(g => {
        if (type === 'all' || g.dataset.type === type) {
            g.style.display = '';
        } else {
            g.style.display = 'none';
        }
    });
}

function updateSummary() {
    const deleteCount = document.querySelectorAll('.item.delete').length;
    const keepCount = document.querySelectorAll('.item.keep').length;
    document.getElementById('summary').textContent = 
        `${keepCount} to keep · ${deleteCount} to delete`;
}

function exportDecisions() {
    const decisions = [];
    document.querySelectorAll('.item.delete').forEach(item => {
        decisions.push({
            id: item.dataset.id,
            group: parseInt(item.dataset.group),
        });
    });
    
    const blob = new Blob([JSON.stringify(decisions, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'delete_list.json';
    a.click();
    URL.revokeObjectURL(url);
}

function exportUrls() {
    const urls = [];
    document.querySelectorAll('.item.delete img').forEach(img => {
        const onclick = img.getAttribute('onclick');
        const match = onclick && onclick.match(/window\\.open\\('([^']+)'/);
        if (match) urls.push(match[1]);
    });
    navigator.clipboard.writeText(urls.join('\\n')).then(() => {
        alert(`Copied ${urls.length} Google Photos URLs to clipboard.\\nOpen each to manually delete, or use the deletion helper script.`);
    });
}

updateSummary();
</script>

</body>
</html>
"""

    with open(output_path, "w") as f:
        f.write(html)

    print(f"Report saved to: {output_path}")
    print(f"Open in browser to review {len(duplicate_groups)} duplicate groups.")
    return output_path
