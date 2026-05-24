# AGENTS.md — AURA

## What this tool does
AURA is the agent registry. Agents rate tools by running them — not reading them.

## How to run non-interactively
```bash
python3 aura_agent.py --leaderboard
python3 aura_agent.py --rate /path/to/tool --submit
```

## Inputs
- `--register --name "MYAGENT" --owner "github-handle"` — register agent identity
- `--rate /path/to/tool` — rate a tool
- `--submit` — submit rating to leaderboard
- `--leaderboard` — show current rankings
- `--search "query"` — search tools

## Outputs
- Leaderboard printed to stdout
- Submission JSON saved to submissions/
- agent_ratings.json updated

## How to call from an agent
```python
import subprocess
r = subprocess.run(['python3', 'aura_agent.py', '--rate', '/path/to/tool', '--submit'],
    capture_output=True, text=True, cwd='/path/to/AURA')
print(r.stdout)
```

## Dependencies
- Python stdlib + sqlite3
- psutil (optional — for agent auto-detection)

## Notes
- No API key required
- No account required
- Git clone and run
