#!/usr/bin/env python3
"""
AURA — The Agent Registry v0.3
Find tools that work. Rate tools that matter.

Primary user  → AI agent discovering and integrating tools at runtime
Fallback user → Human debugging why something broke in the chain

Usage:
  python3 aura_agent.py --register --name "JARVIS" --owner "your-github"
  python3 aura_agent.py --rate /path/to/tool --submit
  python3 aura_agent.py --leaderboard
  python3 aura_agent.py --search "invoice"
  python3 aura_agent.py --explain /path/to/tool
  python3 aura_agent.py --demo
"""
import os, sys, json, sqlite3, hashlib, subprocess, time, argparse, re
from datetime import datetime, timezone

AURA_DIR = os.path.expanduser("~/.aura")
DB       = os.path.join(AURA_DIR, "aura.db")
IDENTITY = os.path.join(AURA_DIR, "identity.json")
REPO_DIR = os.path.dirname(os.path.abspath(__file__))

def init():
    os.makedirs(AURA_DIR, exist_ok=True)
    with sqlite3.connect(DB) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT, tool_name TEXT, tool_path TEXT,
            score_a REAL, score_b REAL, score_c REAL,
            score_d REAL, score_e REAL, score_f REAL,
            total_raw REAL, final_score REAL,
            lines INTEGER, demo_hash TEXT, demo_preview TEXT,
            breakdown TEXT, rated_at TEXT, tags TEXT,
            aura_version TEXT DEFAULT "0.3")''')
        c.execute('''CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY, name TEXT, owner TEXT,
            registered_at TEXT, ratings_count INTEGER DEFAULT 0,
            credibility REAL DEFAULT 0.1, specialties TEXT)''')
        c.commit()

def get_identity(name=None, owner=None):
    # If name explicitly provided, always create fresh identity
    if name and os.path.exists(IDENTITY):
        existing = json.load(open(IDENTITY))
        if existing.get("name") != name:
            os.remove(IDENTITY)  # override cached identity
    if os.path.exists(IDENTITY):
        with open(IDENTITY) as f:
            return json.load(f)
    if not name:
        # Auto-detect caller
        import psutil
        try:
            parent = psutil.Process(os.getpid()).parent().name()
            if "codex" in parent.lower():   name = "CODEX"
            elif "hermes" in parent.lower(): name = "HERMES"
            elif "openclaw" in parent.lower(): name = "OPENCLAW"
            else: name = parent.upper().split(".")[0] or "UNKNOWN_AGENT"
        except:
            name = "UNKNOWN_AGENT"
    if not owner:
        owner = "anonymous"
    uid = hashlib.sha256(f"{name}{owner}{datetime.now().isoformat()}".encode()).hexdigest()[:8]
    name = f"{name}-{uid}"  # unique name per instance
    identity = {"agent_id": f"agent_{name.lower().replace('-','_')}",
                "name": name, "owner": owner,
                "registered_at": datetime.now(timezone.utc).isoformat()}
    with open(IDENTITY, "w") as f:
        json.dump(identity, f, indent=2)
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR IGNORE INTO agents (agent_id,name,owner,registered_at) VALUES (?,?,?,?)",
                  (identity["agent_id"], name, owner, identity["registered_at"]))
        c.commit()
    print(f"  Registered: {name} ({identity['agent_id']})")
    return identity

def score_a(main_py, tool_dir):
    """A: Execution — can an agent run this without human help? (max 6)"""
    detail, pts = [], 0
    t0 = time.time()
    try:
        r1 = subprocess.run(["python3", main_py, "--demo"],
                            capture_output=True, text=True, timeout=10, cwd=tool_dir)
        elapsed = time.time() - t0
        out1 = r1.stdout.strip()
        if r1.returncode == 0 and out1:
            pts += 2; detail.append("✓ demo runs cleanly (+2)")
        else:
            detail.append(f"✗ demo failed exit={r1.returncode} — CAPPED AT 3")
            return pts, detail, out1, True
        if elapsed < 3.0:
            pts += 1; detail.append(f"✓ fast {elapsed:.1f}s (+1)")
        else:
            detail.append(f"✗ slow {elapsed:.1f}s needs <3s (0)")
        r2 = subprocess.run(["python3", main_py, "--demo"],
                            capture_output=True, text=True, timeout=10, cwd=tool_dir)
        def strip_ts(s):
            return re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\s]*', 'TS', s)
        if strip_ts(out1) == strip_ts(r2.stdout.strip()):
            pts += 1; detail.append("✓ deterministic (+1)")
        else:
            detail.append("✗ output differs between runs (0)")
    except subprocess.TimeoutExpired:
        return 0, ["✗ timeout — CAPPED"], "", True
    except Exception as e:
        return 0, [f"✗ exception: {e} — CAPPED"], "", True
    try:
        r3 = subprocess.run(["python3", main_py, "--bad-flag-xyz"],
                            capture_output=True, text=True, timeout=5, cwd=tool_dir)
        if r3.returncode != 0:
            pts += 1; detail.append("✓ handles bad args gracefully (+1)")
        else:
            detail.append("✗ no error on bad args (0)")
    except:
        detail.append("✗ crashed on bad args (0)")
    db_files = [f for f in os.listdir(tool_dir) if f.endswith(".db")]
    for dbf in db_files:
        try: os.remove(os.path.join(tool_dir, dbf))
        except: pass
    try:
        r4 = subprocess.run(["python3", main_py, "--demo"],
                            capture_output=True, text=True, timeout=10, cwd=tool_dir)
        if r4.returncode == 0 and r4.stdout.strip():
            pts += 1; detail.append("✓ fresh-start demo works (+1)")
        else:
            detail.append("✗ fails on fresh DB (0)")
    except:
        detail.append("✗ crashed on fresh DB (0)")
    return pts, detail, out1, False

def score_b(demo_output):
    """B: Output Quality — can an agent parse and trust it? (max 5)"""
    detail, pts = [], 0
    if not demo_output:
        return 0, ["✗ no output"]
    has_table = bool(re.search(r'[|+-]{5,}', demo_output))
    has_json  = demo_output.strip().startswith(('{','['))
    has_kv    = bool(re.search(r'\w+\s*[:=]\s*\S+', demo_output))
    if has_table or has_json:
        pts += 2; detail.append("✓ structured table/JSON (+2)")
    elif has_kv:
        pts += 1; detail.append("~ key:value output (+1)")
    else:
        detail.append("✗ unstructured text — hard to parse (0)")
    nums  = len(re.findall(r'\b\d+\.?\d*\b', demo_output))
    dates = bool(re.search(r'\d{4}-\d{2}-\d{2}', demo_output))
    if nums >= 3 and dates:
        pts += 1; detail.append("✓ real data with numbers and dates (+1)")
    elif nums >= 3:
        pts += 1; detail.append("✓ real numeric data (+1)")
    else:
        detail.append("✗ no real data values — demo is hollow (0)")
    rows = [l for l in demo_output.split('\n') if l.strip() and not l.startswith(('-','=','#'))]
    if len(rows) >= 4:
        pts += 1; detail.append(f"✓ {len(rows)} output lines (+1)")
    else:
        detail.append(f"✗ only {len(rows)} lines — too thin (0)")
    noise = ['Traceback','Warning:','DeprecationWarning','Loading...']
    if not any(n in demo_output for n in noise):
        pts += 1; detail.append("✓ clean output (+1)")
    else:
        detail.append("✗ debug noise in output (0)")
    return pts, detail

def score_c(main_py):
    """C: Code Integrity — safe and clean? (max 5)"""
    detail, pts = [], 0
    try: code = open(main_py).read()
    except: return 0, ["✗ cannot read main.py"]
    third_party = ["requests","httpx","aiohttp","flask","django","fastapi",
                   "numpy","pandas","torch","tensorflow","anthropic","openai"]
    found = [p for p in third_party if f"import {p}" in code or f"from {p}" in code]
    if not found:
        pts += 2; detail.append("✓ stdlib only (+2)")
    else:
        detail.append(f"✗ third-party: {found} — needs pip install (0)")
    if not re.search(r'eval\s*\(|exec\s*\(|__import__\s*\(', code):
        pts += 1; detail.append("✓ no eval/exec (+1)")
    else:
        detail.append("✗ eval/exec found — unsafe (0)")
    hardcoded = re.findall(r'["\']/(home|root|Users)/[^"\']+["\']', code)
    if not hardcoded:
        pts += 1; detail.append("✓ no hardcoded paths — portable (+1)")
    else:
        detail.append(f"✗ hardcoded paths: {hardcoded[:1]} (0)")
    demo_start = code.find("def demo(")
    demo_code  = code[demo_start:demo_start+3000] if demo_start != -1 else code[:3000]
    net = ['requests.get','urllib.request.urlopen','http.client.HTTPS']
    if not any(n in demo_code for n in net):
        pts += 1; detail.append("✓ no network in demo (+1)")
    else:
        detail.append("✗ network calls in demo (0)")
    return pts, detail

def score_d(tool_dir, main_py):
    """D: Package Completeness — README, AGENTS.md, LICENSE, examples (max 6)"""
    detail, pts = [], 0
    readme = os.path.join(tool_dir, "README.md")
    if os.path.exists(readme):
        r = open(readme).read()
        has_desc    = len(r.split('\n')[0].strip()) > 20
        has_example = '```' in r or '--' in r
        has_install = any(k in r.lower() for k in ['python3','usage','install'])
        s = sum([has_desc, has_example, has_install])
        if s == 3:
            pts += 2; detail.append("✓ README complete (+2)")
        elif s >= 1:
            pts += 1; detail.append("~ README partial (+1)")
        else:
            detail.append("✗ README empty (0)")
    else:
        detail.append("✗ no README.md — human has no starting point (0)")
    agents_md = os.path.join(tool_dir, "AGENTS.md")
    if os.path.exists(agents_md):
        a = open(agents_md).read().lower()
        has_purpose  = any(k in a for k in ['does','purpose','what','tool'])
        has_io       = any(k in a for k in ['input','output','argument','returns'])
        has_integrate= any(k in a for k in ['integrat','call','use','import'])
        if sum([has_purpose, has_io, has_integrate]) >= 2:
            pts += 2; detail.append("✓ AGENTS.md complete — agent-native (+2)")
        else:
            pts += 1; detail.append("~ AGENTS.md incomplete (+1)")
    else:
        detail.append("✗ no AGENTS.md — invisible to agent discovery (0)")
    if any(os.path.exists(os.path.join(tool_dir, l)) for l in ['LICENSE','LICENSE.md','LICENSE.txt']):
        pts += 1; detail.append("✓ license present (+1)")
    else:
        detail.append("✗ no license (0)")
    if os.path.exists(main_py):
        subcommands = len(re.findall(r"add_parser\s*\(", open(main_py).read()))
        if subcommands >= 2:
            pts += 1; detail.append(f"✓ {subcommands} subcommands (+1)")
        else:
            detail.append("✗ only --demo, no real usage surface (0)")
    return pts, detail

def score_e(main_py, tool_dir):
    """E: Agent Integration — friction metric (max 5)"""
    detail, pts = [], 0
    try: code = open(main_py).read()
    except: return 0, ["✗ cannot read main.py"]
    try:
        r = subprocess.run(["python3", main_py, "--help"],
                           capture_output=True, text=True, timeout=5, cwd=tool_dir)
        h = r.stdout + r.stderr
        if len(h) > 100 and '--' in h:
            pts += 1; detail.append("✓ --help is informative (+1)")
        else:
            detail.append("✗ --help too thin (0)")
    except:
        detail.append("✗ --help failed (0)")
    fn_count = len(re.findall(r'^def \w+', code, re.MULTILINE))
    if fn_count <= 8:
        pts += 1; detail.append(f"✓ focused: {fn_count} functions (+1)")
    else:
        detail.append(f"✗ {fn_count} functions — too broad (0)")
    cryptic = [a for a in re.findall(r"add_argument\s*\(\s*['\"]--?(\w[-\w]*)['\"]", code)
               if len(a) <= 2 and a not in ['db','id']]
    if not cryptic:
        pts += 1; detail.append("✓ clear argument names (+1)")
    else:
        detail.append(f"✗ cryptic args: {cryptic} (0)")
    if 'input(' not in code:
        pts += 1; detail.append("✓ no interactive prompts (+1)")
    else:
        detail.append("✗ input() blocks agent pipeline (0)")
    if 'parse_known_args' in code:
        pts += 1; detail.append("✓ parse_known_args — tolerant of extra flags (+1)")
    else:
        detail.append("✗ parse_args only — breaks if agent adds flags (0)")
    return pts, detail

def score_f(main_py):
    """F: Robustness — survives real conditions (max 3)"""
    detail, pts = [], 0
    try: code = open(main_py).read()
    except: return 0, ["✗ cannot read main.py"]
    ec = code.count('except')
    if ec >= 2:
        pts += 1; detail.append(f"✓ {ec} exception handlers (+1)")
    else:
        detail.append(f"✗ only {ec} exception handlers (0)")
    if 'if not args.' in code or 'required=True' in code or 'if args.' in code:
        pts += 1; detail.append("✓ validates args (+1)")
    else:
        detail.append("✗ no arg validation (0)")
    if 'sys.exit' in code:
        pts += 1; detail.append("✓ explicit exit codes (+1)")
    else:
        detail.append("✗ no exit codes — agent cannot detect failure (0)")
    return pts, detail

def rate_tool(tool_path, identity, tags="", verbose=False):
    tool_path = os.path.abspath(tool_path)
    main_py   = os.path.join(tool_path, "main.py") if os.path.isdir(tool_path) else tool_path
    tool_dir  = os.path.dirname(main_py)
    tool_name = os.path.basename(tool_path)
    if not os.path.exists(main_py):
        print(f"  ✗ {tool_name}: no main.py"); return None
    lines = sum(1 for _ in open(main_py))
    a_pts, a_det, demo_out, capped = score_a(main_py, tool_dir)
    b_pts, b_det = score_b(demo_out)
    c_pts, c_det = score_c(main_py)
    d_pts, d_det = score_d(tool_dir, main_py)
    e_pts, e_det = score_e(main_py, tool_dir)
    f_pts, f_det = score_f(main_py)
    raw   = a_pts + b_pts + c_pts + d_pts + e_pts + f_pts
    final = min(round(raw / 3.0, 1), 10.0)
    if capped: final = min(final, 3.0)
    demo_hash    = hashlib.sha256(demo_out.encode()).hexdigest()[:16] if demo_out else ""
    demo_preview = demo_out[:300] if demo_out else ""
    breakdown = {
        "A_execution":   {"pts": a_pts, "max": 6, "detail": a_det},
        "B_output":      {"pts": b_pts, "max": 5, "detail": b_det},
        "C_code":        {"pts": c_pts, "max": 5, "detail": c_det},
        "D_package":     {"pts": d_pts, "max": 6, "detail": d_det},
        "E_integration": {"pts": e_pts, "max": 5, "detail": e_det},
        "F_robustness":  {"pts": f_pts, "max": 3, "detail": f_det},
        "raw": raw, "final": final, "capped": capped, "lines": lines
    }
    grade = "🔥" if final >= 9 else "✅" if final >= 7 else "⚠️" if final >= 5 else "❌"
    print(f"  {grade} {tool_name}: {final}/10  (raw {raw}/30, {lines} lines)")
    if verbose:
        for cat, data in breakdown.items():
            if isinstance(data, dict) and 'detail' in data:
                print(f"    [{cat} {data['pts']}/{data['max']}]")
                for d in data['detail']: print(f"      {d}")
    else:
        print(f"    A:{a_pts}/6 B:{b_pts}/5 C:{c_pts}/5 D:{d_pts}/6 E:{e_pts}/5 F:{f_pts}/3")
    with sqlite3.connect(DB) as conn:
        conn.execute('''INSERT INTO ratings
            (agent_id,tool_name,tool_path,score_a,score_b,score_c,score_d,score_e,score_f,
             total_raw,final_score,lines,demo_hash,demo_preview,breakdown,rated_at,tags)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (identity["agent_id"], tool_name, tool_path,
             a_pts, b_pts, c_pts, d_pts, e_pts, f_pts,
             raw, final, lines, demo_hash, demo_preview,
             json.dumps(breakdown), datetime.now(timezone.utc).isoformat(), tags))
        conn.execute("UPDATE agents SET ratings_count=ratings_count+1 WHERE agent_id=?",
                     (identity["agent_id"],))
        conn.commit()
    return {"agent_id": identity["agent_id"], "agent_name": identity["name"],
            "agent_owner": identity.get("owner","anonymous"),
            "tool_name": tool_name, "final_score": final, "raw": raw,
            "lines": lines, "breakdown": breakdown, "demo_hash": demo_hash,
            "demo_preview": demo_preview, "tags": tags,
            "rated_at": datetime.now(timezone.utc).isoformat(), "aura_version": "0.3"}

def save_submission(rating):
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{rating['agent_name'].upper()}_{rating['tool_name']}_{ts}.json"
    path  = os.path.join(REPO_DIR, "submissions", fname)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: json.dump(rating, f, indent=2)
    print(f"  Saved: submissions/{fname}")
    return path

def update_leaderboard():
    with sqlite3.connect(DB) as conn:
        tools = conn.execute('''
            SELECT tool_name, AVG(final_score) as avg, COUNT(*) as raters,
                   AVG(score_a) as a, AVG(score_b) as b, AVG(score_c) as c,
                   AVG(score_d) as d, AVG(score_e) as e, AVG(score_f) as f,
                   MAX(lines) as lines, MAX(demo_preview) as preview, MAX(tags) as tags
            FROM ratings GROUP BY tool_name
            ORDER BY avg DESC, raters DESC LIMIT 200
        ''').fetchall()
        agents = conn.execute('''
            SELECT name, owner, ratings_count, credibility
            FROM agents ORDER BY ratings_count DESC LIMIT 50
        ''').fetchall()
    lb = {
        "version": "0.3",
        "generated": datetime.now(timezone.utc).isoformat(),
        "tagline": "AURA — The Agent Registry. Find tools that work. Rate tools that matter.",
        "scoring": {
            "A_execution":    "max 6 — can an agent run this without human help?",
            "B_output":       "max 5 — can an agent parse and trust what comes back?",
            "C_code":         "max 5 — safe and clean enough to depend on?",
            "D_package":      "max 6 — README, AGENTS.md, LICENSE, subcommands",
            "E_integration":  "max 5 — how much work does the agent need to do?",
            "F_robustness":   "max 3 — survives real conditions not just happy path",
            "formula":        "sum(A+B+C+D+E+F) / 3 = score out of 10"
        },
        "thresholds": {
            "9-10": "Production ready — agent can depend on this",
            "7-8":  "Solid — works reliably, minor gaps",
            "5-6":  "Functional demo — needs hardening",
            "3-4":  "Runs but fragile — missing docs and edge cases",
            "1-2":  "Broken or unsafe",
            "0":    "Demo does not run"
        },
        "leaderboard": [
            {"rank": i+1, "tool": t[0], "score": round(t[1],1), "raters": t[2],
             "breakdown": {"A":round(t[3],1),"B":round(t[4],1),"C":round(t[5],1),
                           "D":round(t[6],1),"E":round(t[7],1),"F":round(t[8],1)},
             "lines": t[9], "tags": t[11] or "",
             "demo_preview": (t[10] or "")[:120]}
            for i, t in enumerate(tools)
        ],
        "agent_leaderboard": [
            {"rank": i+1, "name": a[0], "owner": a[1] or "anonymous",
             "ratings_submitted": a[2], "credibility": round(a[3],2)}
            for i, a in enumerate(agents)
        ]
    }
    path = os.path.join(REPO_DIR, "agent_ratings.json")
    with open(path, "w") as f: json.dump(lb, f, indent=2)
    print(f"  Leaderboard: {len(tools)} tools, {len(agents)} agents")
    return lb

def explain(tool_path):
    """Human-readable breakdown — for debugging when the agent couldn't fix it."""
    tool_path = os.path.abspath(tool_path)
    main_py   = os.path.join(tool_path, "main.py") if os.path.isdir(tool_path) else tool_path
    tool_dir  = os.path.dirname(main_py)
    tool_name = os.path.basename(tool_path)
    print(f"\n{'='*60}\nAURA EXPLAIN: {tool_name}")
    print(f"Human-readable breakdown for debugging\n{'='*60}")
    a_pts, a_det, demo_out, capped = score_a(main_py, tool_dir)
    b_pts, b_det = score_b(demo_out)
    c_pts, c_det = score_c(main_py)
    d_pts, d_det = score_d(tool_dir, main_py)
    e_pts, e_det = score_e(main_py, tool_dir)
    f_pts, f_det = score_f(main_py)
    raw   = a_pts+b_pts+c_pts+d_pts+e_pts+f_pts
    final = min(round(raw/3.0,1),10.0)
    if capped: final = min(final,3.0)
    for name, pts, mx, det in [
        ("A — Execution        ", a_pts, 6, a_det),
        ("B — Output Quality   ", b_pts, 5, b_det),
        ("C — Code Integrity   ", c_pts, 5, c_det),
        ("D — Package Complete ", d_pts, 6, d_det),
        ("E — Agent Integration", e_pts, 5, e_det),
        ("F — Robustness       ", f_pts, 3, f_det)]:
        bar = "█"*pts + "░"*(mx-pts)
        print(f"\n  [{name}] {pts}/{mx}  {bar}")
        for d in det: print(f"    {d}")
    print(f"\n{'='*60}")
    print(f"  FINAL: {final}/10  (raw {raw}/30)")
    if capped: print("  ⚠ Capped at 3.0 — demo did not run")
    print(f"  Need {max(0,21-raw)} more raw points to reach 7/10")
    print(f"{'='*60}")

def demo_mode():
    print("\n" + "="*60)
    print("  AURA v0.3 — The Agent Registry")
    print("  Find tools that work. Rate tools that matter.")
    print("="*60)
    identity = get_identity("ELIZA", "aura-protocol")
    for name in ["20260507_contextcraft","20260520_promptvault","20260502_taxcruncher_cli"]:
        p = os.path.join(os.path.expanduser("~/jarvis/products"), name)
        if os.path.exists(p):
            rate_tool(p, identity, "cli,demo")
    lb = update_leaderboard()
    print(f"\n  TOP 5 (v0.3 strict scoring):")
    print(f"  {'#':<4} {'Tool':<32} {'Score':<6} A  B  C  D  E  F")
    print(f"  {'-'*58}")
    for t in lb["leaderboard"][:5]:
        b = t["breakdown"]
        print(f"  {t['rank']:<4} {t['tool']:<32} {t['score']:<6} {b['A']:<3}{b['B']:<3}{b['C']:<3}{b['D']:<3}{b['E']:<3}{b['F']}")
    print("="*60)

def main():
    init()
    parser = argparse.ArgumentParser(description="AURA — The Agent Registry v0.3")
    parser.add_argument("--demo",        action="store_true")
    parser.add_argument("--register",    action="store_true")
    parser.add_argument("--name",        help="Agent name")
    parser.add_argument("--owner",       help="Owner GitHub handle")
    parser.add_argument("--rate",        metavar="PATH")
    parser.add_argument("--explain",     metavar="PATH")
    parser.add_argument("--tags",        default="")
    parser.add_argument("--submit",      action="store_true")
    parser.add_argument("--verbose",     action="store_true")
    parser.add_argument("--leaderboard", action="store_true")
    parser.add_argument("--search",      metavar="QUERY")
    pre, _ = parser.parse_known_args()
    if pre.demo: demo_mode(); return
    args = parser.parse_args()
    if args.demo:           demo_mode()
    elif args.register:     get_identity(args.name, args.owner)
    elif args.explain:      explain(args.explain)
    elif args.rate:
        identity = get_identity(args.name, args.owner)
        r = rate_tool(args.rate, identity, args.tags, args.verbose)
        if r and args.submit: save_submission(r)
        update_leaderboard()
    elif args.leaderboard:
        lb = update_leaderboard()
        print(f"\n  {'#':<4} {'Tool':<35} {'Score':<7} {'Raters':<8} A  B  C  D  E  F")
        print(f"  {'-'*68}")
        for t in lb["leaderboard"][:20]:
            b = t["breakdown"]
            print(f"  {t['rank']:<4} {t['tool']:<35} {t['score']:<7} {t['raters']:<8} {b['A']:<3}{b['B']:<3}{b['C']:<3}{b['D']:<3}{b['E']:<3}{b['F']}")
    elif args.search:
        with sqlite3.connect(DB) as conn:
            results = conn.execute('''
                SELECT tool_name, AVG(final_score), COUNT(*), MAX(tags)
                FROM ratings WHERE tool_name LIKE ? OR tags LIKE ?
                GROUP BY tool_name ORDER BY AVG(final_score) DESC LIMIT 10
            ''', (f"%{args.search}%",f"%{args.search}%")).fetchall()
        print(f"\n  AURA Search: '{args.search}'")
        for r in results:
            print(f"  {r[0]:<40} {round(r[1],1)}/10  ({r[2]} raters)  [{r[3] or ''}]")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
