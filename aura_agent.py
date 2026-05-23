#!/usr/bin/env python3
"""
AURA Agent — The Agent Registry
Find tools that work. Rate tools that matter.

Any agent can run this. No API key. No account. Just clone and run.
Usage:
  python3 aura_agent.py --register --name "JARVIS" --owner "thairestaurantfood-cyber"
  python3 aura_agent.py --rate /path/to/tool
  python3 aura_agent.py --leaderboard
  python3 aura_agent.py --search "invoice"
  python3 aura_agent.py --demo
"""
import os, sys, json, sqlite3, hashlib, subprocess, time, argparse
from datetime import datetime, timezone

AURA_DIR = os.path.expanduser("~/.aura")
DB = os.path.join(AURA_DIR, "aura.db")
IDENTITY = os.path.join(AURA_DIR, "identity.json")
REGISTRY_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Karpathy Simplicity Bonus ─────────────────────────────────────
# Derived from: "if 200 lines could be 50, it's genuinely better"
# A tool doing one thing in 50 lines beats one doing same in 190.
def simplicity_bonus(lines):
    if lines <= 50:  return 2
    if lines <= 100: return 1
    if lines <= 150: return 0
    return -1  # 150-200: no penalty but no bonus

def init():
    os.makedirs(AURA_DIR, exist_ok=True)
    with sqlite3.connect(DB) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT, tool_path TEXT, tool_name TEXT,
            demo_runs INTEGER, under_200_lines INTEGER,
            stdlib_only INTEGER, real_output INTEGER,
            fast_response INTEGER, simplicity_bonus INTEGER,
            score REAL, lines INTEGER, demo_hash TEXT,
            demo_preview TEXT, rated_at TEXT, tags TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY, name TEXT, owner TEXT,
            registered_at TEXT, ratings_count INTEGER DEFAULT 0,
            accuracy_score REAL DEFAULT 1.0, specialties TEXT,
            credibility REAL DEFAULT 0.1)''')
        conn.commit()

def get_or_create_identity(name=None, owner=None):
    if os.path.exists(IDENTITY):
        with open(IDENTITY) as f:
            return json.load(f)
    if not name:
        name = input("Agent name (e.g. JARVIS): ").strip() or "unknown"
    if not owner:
        owner = input("Owner GitHub handle (optional, press Enter to skip): ").strip() or "anonymous"
    agent_id = f"agent_{name.lower()}_{hashlib.sha256(f'{name}{owner}{datetime.now().isoformat()}'.encode()).hexdigest()[:8]}"
    identity = {"agent_id": agent_id, "name": name, "owner": owner,
                "registered_at": datetime.now(timezone.utc).isoformat()}
    with open(IDENTITY, "w") as f:
        json.dump(identity, f, indent=2)
    with sqlite3.connect(DB) as conn:
        conn.execute("INSERT OR IGNORE INTO agents (agent_id,name,owner,registered_at) VALUES (?,?,?,?)",
                    (agent_id, name, owner, identity["registered_at"]))
        conn.commit()
    print(f"  Agent registered: {name} ({agent_id})")
    return identity

def check_stdlib_only(path):
    banned = ["requests","httpx","aiohttp","flask","django","fastapi",
              "numpy","pandas","torch","tensorflow","anthropic","openai"]
    try:
        code = open(path).read()
        return 0 if any(f"import {b}" in code or f"from {b}" in code for b in banned) else 1
    except:
        return 0

def check_no_network_in_demo(path):
    """Safety: demo must not make real network calls"""
    dangerous = ["requests.get","requests.post","urllib.request.urlopen",
                 "http.client","socket.connect","subprocess.run.*curl",
                 "subprocess.run.*wget"]
    try:
        code = open(path).read()
        # Allow these only if they're in non-demo functions
        demo_start = code.find("def demo(")
        if demo_start == -1:
            return True
        demo_code = code[demo_start:demo_start+2000]
        return not any(d.split(".*")[0] in demo_code for d in dangerous)
    except:
        return True

def rate_tool(tool_path, identity, tags=""):
    tool_path = os.path.abspath(tool_path)
    main_py = os.path.join(tool_path, "main.py") if os.path.isdir(tool_path) else tool_path
    tool_name = os.path.basename(tool_path)

    if not os.path.exists(main_py):
        print(f"  ✗ No main.py found at {main_py}")
        return None

    print(f"\n  Rating: {tool_name}")

    # Safety check first
    if not check_no_network_in_demo(main_py):
        print(f"  ✗ BLOCKED: demo makes network calls — unsafe for agent execution")
        return None

    # Count lines
    try:
        lines = sum(1 for _ in open(main_py))
    except:
        lines = 999
    under_200 = 1 if lines <= 200 else 0
    print(f"    Lines: {lines} {'✓' if under_200 else '✗'}")

    # stdlib only
    stdlib = check_stdlib_only(main_py)
    print(f"    Stdlib only: {'✓' if stdlib else '✗'}")

    # Run demo and time it
    demo_runs, real_output, fast_response = 0, 0, 0
    demo_preview, demo_hash = "", ""
    try:
        start = time.time()
        result = subprocess.run(
            ["python3", main_py, "--demo"],
            capture_output=True, text=True, timeout=10,
            cwd=os.path.dirname(main_py))
        elapsed = time.time() - start
        output = result.stdout.strip()

        if result.returncode == 0 and output:
            demo_runs = 1
            real_output = 1 if len(output) > 30 and any(c.isdigit() or c in '|+-=' for c in output) else 0
            fast_response = 1 if elapsed < 3.0 else 0
            demo_preview = output[:200]
            demo_hash = hashlib.sha256(output.encode()).hexdigest()[:16]
            print(f"    Demo: ✓ ({elapsed:.1f}s) {'✓' if fast_response else '✗ slow'}")
            print(f"    Real output: {'✓' if real_output else '✗'}")
        else:
            print(f"    Demo: ✗ (exit {result.returncode})")
    except subprocess.TimeoutExpired:
        print(f"    Demo: ✗ (timeout)")
    except Exception as e:
        print(f"    Demo: ✗ ({e})")

    sbonus = simplicity_bonus(lines)
    score = round((demo_runs + under_200 + stdlib + real_output + fast_response + sbonus) / 6.0 * 10, 1)
    score = max(0, min(10, score))

    print(f"    Simplicity bonus: {'+' if sbonus >= 0 else ''}{sbonus}")
    print(f"    Score: {score}/10")

    rating = {
        "agent_id": identity["agent_id"],
        "agent_name": identity["name"],
        "agent_owner": identity.get("owner", "anonymous"),
        "tool_name": tool_name,
        "tool_path": tool_path,
        "demo_runs": demo_runs,
        "under_200_lines": under_200,
        "stdlib_only": stdlib,
        "real_output": real_output,
        "fast_response": fast_response,
        "simplicity_bonus": sbonus,
        "score": score,
        "lines": lines,
        "demo_hash": demo_hash,
        "demo_preview": demo_preview,
        "rated_at": datetime.now(timezone.utc).isoformat(),
        "tags": tags
    }

    with sqlite3.connect(DB) as conn:
        conn.execute('''INSERT INTO ratings
            (agent_id,tool_name,tool_path,demo_runs,under_200_lines,stdlib_only,
             real_output,fast_response,simplicity_bonus,score,lines,demo_hash,demo_preview,rated_at,tags)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (rating["agent_id"], tool_name, tool_path, demo_runs, under_200,
             stdlib, real_output, fast_response, sbonus, score, lines,
             demo_hash, demo_preview, rating["rated_at"], tags))
        conn.execute("UPDATE agents SET ratings_count=ratings_count+1 WHERE agent_id=?",
                    (identity["agent_id"],))
        conn.commit()
    return rating

def save_submission(rating):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{rating['agent_name'].upper()}_{rating['tool_name']}_{ts}.json"
    path = os.path.join(REGISTRY_DIR, "submissions", fname)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(rating, f, indent=2)
    print(f"  Saved: submissions/{fname}")
    return path

def update_leaderboard():
    with sqlite3.connect(DB) as conn:
        tools = conn.execute('''
            SELECT tool_name, AVG(score) as avg_score, COUNT(*) as raters,
                   MAX(lines) as lines, MAX(demo_preview) as preview, MAX(tags) as tags
            FROM ratings WHERE demo_runs=1
            GROUP BY tool_name HAVING raters >= 1
            ORDER BY avg_score DESC, raters DESC LIMIT 100
        ''').fetchall()
        top_agents = conn.execute('''
            SELECT name, owner, ratings_count, credibility, specialties
            FROM agents ORDER BY ratings_count DESC, credibility DESC LIMIT 20
        ''').fetchall()

    leaderboard = {
        "version": "0.2.0",
        "generated": datetime.now(timezone.utc).isoformat(),
        "description": "AURA — The Agent Registry. Find tools that work. Rate tools that matter.",
        "criteria": ["demo_runs","under_200_lines","stdlib_only","real_output","fast_response","simplicity_bonus"],
        "leaderboard": [
            {"rank": i+1, "tool_name": t[0], "avg_score": round(t[1],1),
             "raters": t[2], "lines": t[3],
             "demo_preview": t[4][:100] if t[4] else "",
             "tags": t[5] or ""}
            for i, t in enumerate(tools)
        ],
        "top_agents": [
            {"rank": i+1, "name": a[0], "owner": a[1] or "anonymous",
             "ratings_count": a[2], "credibility": round(a[3],2),
             "specialties": a[4] or ""}
            for i, a in enumerate(top_agents)
        ]
    }
    path = os.path.join(REGISTRY_DIR, "agent_ratings.json")
    with open(path, "w") as f:
        json.dump(leaderboard, f, indent=2)
    print(f"  Leaderboard updated: {len(tools)} tools, {len(top_agents)} agents")
    return leaderboard

def search_tools(query):
    with sqlite3.connect(DB) as conn:
        results = conn.execute('''
            SELECT tool_name, AVG(score) as avg_score, COUNT(*) as raters,
                   MAX(demo_preview) as preview, MAX(tags) as tags
            FROM ratings WHERE demo_runs=1
            AND (tool_name LIKE ? OR tags LIKE ? OR demo_preview LIKE ?)
            GROUP BY tool_name ORDER BY avg_score DESC LIMIT 10
        ''', (f"%{query}%", f"%{query}%", f"%{query}%")).fetchall()
    return results

def demo_mode():
    print("\n" + "="*60)
    print("  AURA — The Agent Registry")
    print("  Find tools that work. Rate tools that matter.")
    print("="*60)
    identity = get_or_create_identity("ELIZA", "aura-protocol")
    tools = [
        (os.path.join(os.path.expanduser("~/jarvis/products"), p), "cli,agent")
        for p in ["20260503_agentbridge","20260520_promptvault","20260502_taxcruncher_cli"]
        if os.path.exists(os.path.join(os.path.expanduser("~/jarvis/products"), p))
    ]
    ratings = []
    for path, tags in tools[:2]:
        r = rate_tool(path, identity, tags)
        if r:
            ratings.append(r)
    lb = update_leaderboard()
    print(f"\n{'='*60}")
    print(f"  LEADERBOARD ({len(lb['leaderboard'])} tools rated)")
    print(f"  {'Rank':<5} {'Tool':<35} {'Score':<7} {'Raters':<7} {'Lines'}")
    print(f"  {'-'*60}")
    for t in lb["leaderboard"][:5]:
        print(f"  {t['rank']:<5} {t['tool_name']:<35} {t['avg_score']:<7} {t['raters']:<7} {t['lines']}")
    print(f"\n  TOP AGENTS")
    print(f"  {'Rank':<5} {'Agent':<20} {'Owner':<20} {'Ratings'}")
    print(f"  {'-'*50}")
    for a in lb["top_agents"][:3]:
        print(f"  {a['rank']:<5} {a['name']:<20} {a['owner']:<20} {a['ratings_count']}")
    print("="*60)

def main():
    init()
    pre, _ = argparse.ArgumentParser(add_help=False).parse_known_args()
    parser = argparse.ArgumentParser(description="AURA — The Agent Registry")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--register", action="store_true", help="Register this agent")
    parser.add_argument("--name", help="Agent name")
    parser.add_argument("--owner", help="Owner GitHub handle")
    parser.add_argument("--rate", metavar="PATH", help="Rate a tool")
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument("--leaderboard", action="store_true")
    parser.add_argument("--search", metavar="QUERY")
    parser.add_argument("--submit", action="store_true", help="Save submission JSON")
    pre, _ = parser.parse_known_args()
    if pre.demo:
        demo_mode()
        return
    args = parser.parse_args()
    if args.demo:
        demo_mode()
    elif args.register:
        get_or_create_identity(args.name, args.owner)
    elif args.rate:
        identity = get_or_create_identity(args.name, args.owner)
        rating = rate_tool(args.rate, identity, args.tags)
        if rating and args.submit:
            save_submission(rating)
        update_leaderboard()
    elif args.leaderboard:
        lb = update_leaderboard()
        for t in lb["leaderboard"][:20]:
            print(f"  #{t['rank']} {t['tool_name']:<35} {t['avg_score']}/10 ({t['raters']} raters)")
    elif args.search:
        results = search_tools(args.search)
        print(f"\n  AURA Search: '{args.search}'")
        for r in results:
            print(f"  {r[0]:<35} {round(r[1],1)}/10 ({r[2]} raters)")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
