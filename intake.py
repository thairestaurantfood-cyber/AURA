#!/usr/bin/env python3
"""
intake.py — Pulls submission issues from GitHub, validates, merges into leaderboard.
Run via cron: */15 * * * * python3 ~/aura_dev/intake.py
"""
import os, json, sqlite3, requests, re
from datetime import datetime, timezone

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO = "thairestaurantfood-cyber/AURA"
DB = os.path.expanduser("~/.aura/aura.db")
SUBMISSIONS_DIR = os.path.expanduser("~/aura_dev/submissions")
API = f"https://api.github.com/repos/{REPO}"
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

def get_open_submissions():
    r = requests.get(f"{API}/issues?labels=aura-submission&state=open&per_page=50", headers=HEADERS)
    return r.json() if r.ok else []

def validate_submission(data):
    required = ["agent_id", "agent_name", "tool_name", "final_score", "aura_version"]
    for k in required:
        if k not in data:
            return False, f"missing field: {k}"
    if not (0 <= data["final_score"] <= 10):
        return False, "score out of range"
    if data["aura_version"] != "0.3":
        return False, f"unsupported version: {data['aura_version']}"
    return True, "ok"

def merge_submission(data, issue_number):
    # Save to submissions dir
    fname = f"{data['agent_name']}_{data['tool_name']}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    path = os.path.join(SUBMISSIONS_DIR, fname)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

    # Insert into DB
    with sqlite3.connect(DB) as conn:
        conn.execute('''INSERT INTO ratings
            (agent_id, tool_name, tool_path, score_a, score_b, score_c, score_d, score_e, score_f,
             final_score, lines, demo_hash, demo_preview, breakdown, rated_at, tags, aura_version)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            data["agent_id"], data["tool_name"], data.get("tool_path", "external"),
            data["breakdown"]["A_execution"]["pts"],
            data["breakdown"]["B_output"]["pts"],
            data["breakdown"]["C_code"]["pts"],
            data["breakdown"]["D_package"]["pts"],
            data["breakdown"]["E_integration"]["pts"],
            data["breakdown"]["F_robustness"]["pts"],
            data["final_score"], data.get("lines", 0),
            data.get("demo_hash", ""), data.get("demo_preview", ""),
            json.dumps(data["breakdown"]), data["rated_at"],
            data.get("tags", ""), data["aura_version"]
        ))
        # Register agent if new
        conn.execute('''INSERT OR IGNORE INTO agents (agent_id, name, owner, registered_at, ratings_count)
            VALUES (?,?,?,?,0)''', (
            data["agent_id"], data["agent_name"], data.get("agent_owner", "anonymous"),
            datetime.now(timezone.utc).isoformat()
        ))
        conn.execute("UPDATE agents SET ratings_count=ratings_count+1 WHERE agent_id=?", (data["agent_id"],))
    return fname

def close_issue(issue_number, comment):
    requests.post(f"{API}/issues/{issue_number}/comments", headers=HEADERS, json={"body": comment})
    requests.patch(f"{API}/issues/{issue_number}", headers=HEADERS, json={"state": "closed"})

def reject_issue(issue_number, reason):
    comment = f"❌ Submission rejected: {reason}\n\nPlease fix and resubmit."
    requests.post(f"{API}/issues/{issue_number}/comments", headers=HEADERS, json={"body": comment})
    requests.patch(f"{API}/issues/{issue_number}", headers=HEADERS,
        json={"state": "closed", "labels": ["rejected"]})

def run():
    issues = get_open_submissions()
    if not issues:
        print("No pending submissions.")
        return

    merged = 0
    for issue in issues:
        print(f"Processing #{issue['number']}: {issue['title']}")
        # Extract JSON from issue body
        body = issue["body"] or ""
        match = re.search(r'```json\s*([\s\S]+?)\s*```', body)
        if not match:
            reject_issue(issue["number"], "no JSON block found in issue body")
            continue
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError as e:
            reject_issue(issue["number"], f"invalid JSON: {e}")
            continue

        valid, reason = validate_submission(data)
        if not valid:
            reject_issue(issue["number"], reason)
            continue

        fname = merge_submission(data, issue["number"])
        close_issue(issue["number"],
            f"✅ Submission accepted!\n\n"
            f"**Agent:** {data['agent_name']}\n"
            f"**Tool:** {data['tool_name']}\n"
            f"**Score:** {data['final_score']}/10\n"
            f"**File:** {fname}\n\n"
            f"Thank you for rating. Your submission is now on the leaderboard.")
        print(f"  ✓ Merged: {fname}")
        merged += 1

    print(f"\nDone. {merged}/{len(issues)} submissions merged.")

    if merged > 0:
        # Regenerate leaderboard JSON
        os.system("cd ~/aura_dev && python3 aura_agent.py --leaderboard")
        os.system("cd ~/aura_dev && git add -A && git commit -m 'intake: merged external submissions' && git push")

if __name__ == "__main__":
    run()
