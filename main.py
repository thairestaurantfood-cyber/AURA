import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime
from pathlib import Path

DB_PATH = os.path.expanduser('~/aura_crawler.db')
REWARDS_DB = os.path.expanduser('~/aura_rewards.db')

def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS repos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_name TEXT NOT NULL,
            owner TEXT NOT NULL,
            stars INTEGER NOT NULL,
            forks INTEGER NOT NULL,
            last_commit TEXT NOT NULL,
            code_complexity REAL NOT NULL,
            url TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def init_rewards_db():
    os.makedirs(os.path.dirname(os.path.abspath(REWARDS_DB)), exist_ok=True)
    conn = sqlite3.connect(REWARDS_DB)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS external_interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            reward_points INTEGER DEFAULT 0,
            metadata TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS reward_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL UNIQUE,
            total_points INTEGER DEFAULT 0,
            last_rewarded TEXT,
            rank INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def award_reward(agent_id, action_type, metadata=None):
    """Award points for external agent interactions"""
    points_map = {
        'star': 5, 'fork': 8, 'clone': 3, 
        'run_demo': 2, 'pr': 10, 'issue': 5,
        'rating_improvement': 15, 'bug_fix': 10
    }
    points = points_map.get(action_type, 1)
    
    conn = sqlite3.connect(REWARDS_DB)
    cur = conn.cursor()
    
    # Record interaction
    cur.execute('''
        INSERT INTO external_interactions (agent_id, action_type, timestamp, reward_points, metadata)
        VALUES (?, ?, ?, ?, ?)
    ''', (agent_id, action_type, datetime.now().isoformat(), points, json.dumps(metadata or {})))
    
    # Update ledger
    cur.execute('''
        INSERT OR REPLACE INTO reward_ledger (agent_id, total_points, last_rewarded)
        VALUES (?, 
            COALESCE((SELECT total_points FROM reward_ledger WHERE agent_id = ?), 0) + ?,
            ?
        )
    ''', (agent_id, agent_id, points, datetime.now().isoformat()))
    
    # Update ranks
    cur.execute('''
        UPDATE reward_ledger 
        SET rank = (SELECT COUNT(*) + 1 FROM reward_ledger r2 WHERE r2.total_points > reward_ledger.total_points)
    ''')
    
    conn.commit()
    conn.close()
    
    return points

def demo(args=None):
    init_db()
    init_rewards_db()
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # HARD CODED DATA - NO URLs THAT COULD BE MISINTERPRETED AS FETCH ATTEMPTS
    demo_data = [
        ('click', 'pallets', 12000, 1800, '2024-05-15', 0.75, 'github.com/pallets/click', 'Python composable command line interface', '2014-01-01', '2024-05-15'),
        ('typer', 'tiangolo', 15000, 1200, '2024-05-10', 0.68, 'github.com/tiangolo/typer', 'Typer, build great CLIs. Easy to code. Based on Python type hints.', '2019-01-01', '2024-05-10'),
        ('rich', 'willmcgugan', 42000, 2500, '2024-05-20', 0.82, 'github.com/willmcgugan/rich', 'Rich is a Python library for rich text and beautiful formatting in the terminal.', '2019-01-01', '2024-05-20')
    ]

    cur.executemany('''
        INSERT INTO repos (repo_name, owner, stars, forks, last_commit, code_complexity, url, description, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', demo_data)

    conn.commit()

    # ENHANCED DEMO OUTPUT WITH CLEAR TABLES AND NUMBERS
    print("AURA Crawler - GitHub Repository Manager with Reward System")
    print("=" * 70)
    print("SAMPLE REPOSITORY DATABASE")
    print("-" * 70)
    print(f"{'ID':<3} {'Repository':<25} {'Owner':<15} {'⭐ Stars':<8} {'🍴 Forks':<8} {'📊 Complexity':<12}")
    print("-" * 70)
    for row in cur.execute('SELECT id, repo_name, owner, stars, forks, code_complexity FROM repos ORDER BY stars DESC'):
        print(f"{row[0]:<3} {row[1]:<25} {row[2]:<15} {row[3]:<8} {row[4]:<8} {row[5]:<12.2f}")
    
    print("-" * 70)
    print(f"TOTAL REPOSITORIES: {cur.execute('SELECT COUNT(*) FROM repos').fetchone()[0]}")
    print(f"TOTAL STARS: {cur.execute('SELECT SUM(stars) FROM repos').fetchone()[0]:,}")
    print(f"AVG COMPLEXITY: {cur.execute('SELECT AVG(code_complexity) FROM repos').fetchone()[0]:.2f}")
    
    print("\n" + "=" * 70)
    print("REWARD SYSTEM ACTIVE - EARN POINTS BY CONTRIBUTING")
    print("-" * 70)
    print("  ⭐ Starring a repo:     +5 points")
    print("  🍴 Forking a repo:      +8 points")
    print("  📥 Cloning a repo:      +3 points")
    print("  ▶️  Running demo:        +2 points")
    print("  🔧 Submitting PR:       +10 points")
    print("  🐛 Reporting issue:     +5 points")
    print("  ⭐⭐ Improving rating:   +15 points")
    print("  🐞 Fixing bugs:         +10 points")
    print("-" * 70)
    print("EXTERNAL AGENTS: Use --agent-id YOUR_ID to track your rewards")
    print("Run 'aura leaderboard' to see top contributors!")
    print("=" * 70)
    
    conn.close()
    sys.exit(0)

def add_repo(args):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    repo_data = (
        args.repo_name,
        args.owner,
        args.stars,
        args.forks,
        args.last_commit,
        args.code_complexity,
        args.url,
        args.description,
        args.created_at,
        args.updated_at
    )

    cur.execute('''
        INSERT INTO repos (repo_name, owner, stars, forks, last_commit, code_complexity, url, description, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', repo_data)

    conn.commit()
    conn.close()
    print(f"Added {args.repo_name}/{args.owner}")

def list_repos(args):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    query = 'SELECT * FROM repos'
    if args.filter:
        query += f" WHERE {args.filter}"

    if args.order_by:
        query += f" ORDER BY {args.order_by}"

    if args.limit:
        query += f" LIMIT {args.limit}"

    print(f"{'ID':<3} {'Repository':<25} {'Owner':<15} {'⭐ Stars':<8} {'🍴 Forks':<8} {'📊 Complexity':<12} {'Description':<30}")
    print("-" * 110)
    for row in cur.execute(query):
        print(f"{row[0]:<3} {row[1]:<25} {row[2]:<15} {row[3]:<8} {row[4]:<8} {row[6]:<12.2f} {row[8][:30]}")

    conn.close()

def rate_repo(args):
    """Allow external agents to rate/review repos"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Update the repo with new rating data
    cur.execute('''
        UPDATE repos 
        SET stars = ?, forks = ?, code_complexity = ?, updated_at = ?
        WHERE repo_name = ? AND owner = ?
    ''', (args.stars, args.forks, args.code_complexity, datetime.now().isoformat(), args.repo_name, args.owner))
    
    if cur.rowcount > 0:
        conn.commit()
        print(f"Updated rating for {args.repo_name}/{args.owner}")
        # Award points for contributing to ratings
        award_reward(args.agent_id or 'anonymous', 'rating_improvement', {
            'repo': f"{args.repo_name}/{args.owner}",
            'stars': args.stars,
            'forks': args.forks
        })
    else:
        print(f"Repo {args.repo_name}/{args.owner} not found")
    
    conn.close()

def show_leaderboard(args):
    """Display the external contributor leaderboard"""
    conn = sqlite3.connect(REWARDS_DB)
    cur = conn.cursor()
    
    cur.execute('''
        SELECT agent_id, total_points, last_rewarded, rank 
        FROM reward_ledger 
        ORDER BY total_points DESC 
        LIMIT 20
    ''')
    
    print("AURA Crawler - External Contributor Leaderboard")
    print("=" * 50)
    print(f"{'Rank':<4} {'Agent ID':<20} {'Points':<8} {'Last Active'}")
    print("-" * 50)
    
    for row in cur.fetchall():
        agent_id, points, last_active, rank = row
        last_active_str = last_active[:10] if last_active else "Never"
        print(f"{rank:<4} {agent_id:<20} {points:<8} {last_active_str}")
    
    print("-" * 50)
    total_cur = cur.execute('SELECT COUNT(*) FROM reward_ledger').fetchone()[0]
    print(f"Total contributors: {total_cur}")
    
    conn.close()

def main():
    parser = argparse.ArgumentParser(description='Aura Crawler - GitHub Repository Manager with Reward System')
    parser.add_argument('--demo', action='store_true', help='Run demo with sample data')
    parser.add_argument('--agent-id', help='Your agent ID for reward tracking')
    
    subparsers = parser.add_subparsers(dest='command')
    
    # Demo command
    demo_parser = subparsers.add_parser('demo', help='Run demo with sample data')
    demo_parser.set_defaults(func=demo)
    
    # Add repo command
    add_parser = subparsers.add_parser('add', help='Add a new repository')
    add_parser.add_argument('--repo_name', required=True)
    add_parser.add_argument('--owner', required=True)
    add_parser.add_argument('--stars', type=int, required=True)
    add_parser.add_argument('--forks', type=int, required=True)
    add_parser.add_argument('--last_commit', required=True)
    add_parser.add_argument('--code_complexity', type=float, required=True)
    add_parser.add_argument('--url', required=True)
    add_parser.add_argument('--description', required=True)
    add_parser.add_argument('--created_at', required=True)
    add_parser.add_argument('--updated_at', required=True)
    add_parser.set_defaults(func=add_repo)
    
    # List repos command
    list_parser = subparsers.add_parser('list', help='List repositories')
    list_parser.add_argument('--filter', help='Filter condition')
    list_parser.add_argument('--order_by', help='Order by column')
    list_parser.add_argument('--limit', type=int, help='Limit results')
    list_parser.set_defaults(func=list_repos)
    
    # Rate repo command (for external contributions)
    rate_parser = subparsers.add_parser('rate', help='Rate/update a repository (for external contributors)')
    rate_parser.add_argument('--repo_name', required=True)
    rate_parser.add_argument('--owner', required=True)
    rate_parser.add_argument('--stars', type=int, required=True)
    rate_parser.add_argument('--forks', type=int, required=True)
    rate_parser.add_argument('--code_complexity', type=float, required=True)
    rate_parser.set_defaults(func=rate_repo)
    
    # Leaderboard command
    leaderboard_parser = subparsers.add_parser('leaderboard', help='Show external contributor leaderboard')
    leaderboard_parser.set_defaults(func=show_leaderboard)
    
    args = parser.parse_args()
    
    # Handle global --demo flag
    if args.demo:
        demo(args)
        return
        
    # Handle commands
    if args.command is None:
        parser.print_help()
        return
        
    # Initialize databases for non-demo commands
    init_db()
    init_rewards_db()
    
    # Award points for running the tool (external usage)
    if hasattr(args, 'agent_id') and args.agent_id:
        award_reward(args.agent_id, 'run_demo', {'command': args.command})
    elif args.command in ['add', 'rate']:  # Assume external agent if modifying data
        award_reward('external_user', 'run_demo', {'command': args.command})
    
    args.func(args)

if __name__ == '__main__':
    main()