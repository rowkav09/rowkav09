import argparse
import hashlib
import json
import os
import random
import re
import time
from collections import deque
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import quote, urlencode


START_MARKER = "<!-- TICTACTOE_START -->"
END_MARKER = "<!-- TICTACTOE_END -->"
BOARD_SIZE = 5
MINE_COUNT = 5
SAFE_TILE_COUNT = BOARD_SIZE * BOARD_SIZE - MINE_COUNT


Coordinate = Tuple[int, int]


def blank_board() -> List[List[str]]:
    return [["" for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]


def blank_revealed() -> List[List[bool]]:
    return [[False for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]


def blank_counts() -> List[List[int]]:
    return [[0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]



def default_state() -> dict:
    return {
        "board": blank_board(),
        "revealed": blank_revealed(),
        "mines": [],
        "adjacent_counts": blank_counts(),
        "board_ready": False,
        "current_turn": "Reveal",
        "game_status": "ongoing",
        "winner": None,
        "last_winner": None,
        "last_result": "No finished games yet",
        "last_winners": [],
        "human_wins": 0,
        "ai_wins": 0,
        "draws": 0,
        "total_games": 0,
        "total_human_moves": 0,
        "total_ai_moves": 0,
        "update_samples": 0,
        "total_update_ms": 0,
        "avg_update_ms": 0,
        "total_update_seconds": 0,
        "avg_update_seconds": 0,
        "player_stats": {},
        "current_game_contributors": [],
        "users_moved": [],
        "mine_count": MINE_COUNT,
        "last_triggered_mine": None,
    }



def reset_board_state(state: dict) -> None:
    state["board"] = blank_board()
    state["revealed"] = blank_revealed()
    state["mines"] = []
    state["adjacent_counts"] = blank_counts()
    state["board_ready"] = False
    state["current_turn"] = "Reveal"
    state["game_status"] = "ongoing"
    state["winner"] = None
    state["last_triggered_mine"] = None
    state["current_game_contributors"] = []
    state["users_moved"] = []
    state["mine_count"] = MINE_COUNT



def migrate_state(data: dict) -> dict:
    defaults = default_state()
    for key, value in defaults.items():
        if key not in data:
            data[key] = value

    board = data.get("board")
    needs_reset = (
        not isinstance(board, list)
        or len(board) != BOARD_SIZE
        or any(not isinstance(row, list) or len(row) != BOARD_SIZE for row in board)
        or "revealed" not in data
        or "mines" not in data
        or "adjacent_counts" not in data
        or data.get("mine_count") != MINE_COUNT
    )

    stale_last_results = {"", "Draw", "Human (X) won", "AI (O) won", "No finished games yet"}

    if needs_reset:
        reset_board_state(data)
        old_last_result = str(data.get("last_result", "")).strip()
        if old_last_result in stale_last_results:
            data["last_result"] = "New Minesweeper board ready"
            data["last_winners"] = []
            data["last_winner"] = None
    else:
        if len(data.get("revealed", [])) != BOARD_SIZE or any(len(row) != BOARD_SIZE for row in data.get("revealed", [])):
            data["revealed"] = blank_revealed()
        if len(data.get("adjacent_counts", [])) != BOARD_SIZE or any(len(row) != BOARD_SIZE for row in data.get("adjacent_counts", [])):
            data["adjacent_counts"] = blank_counts()

    if (
        str(data.get("last_result", "")).strip() in stale_last_results
        and not data.get("board_ready")
        and revealed_safe_tiles(data) == 0
    ):
        data["last_result"] = "New Minesweeper board ready"
        data["last_winners"] = []
        data["last_winner"] = None

    return data



def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return default_state()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return migrate_state(data)



def save_state(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")



def neighbors(r: int, c: int) -> List[Coordinate]:
    cells = []
    for rr in range(max(0, r - 1), min(BOARD_SIZE, r + 2)):
        for cc in range(max(0, c - 1), min(BOARD_SIZE, c + 2)):
            if (rr, cc) != (r, c):
                cells.append((rr, cc))
    return cells



def mine_set(state: dict) -> set[Coordinate]:
    return {tuple(cell) for cell in state.get("mines", [])}



def compute_adjacent_counts(mines: set[Coordinate]) -> List[List[int]]:
    counts = blank_counts()
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if (r, c) in mines:
                continue
            counts[r][c] = sum((rr, cc) in mines for rr, cc in neighbors(r, c))
    return counts



def initialize_board(state: dict, safe_cell: Coordinate, seed_text: str) -> None:
    forbidden = {safe_cell, *neighbors(*safe_cell)}
    all_cells = [(r, c) for r in range(BOARD_SIZE) for c in range(BOARD_SIZE)]
    candidates = [cell for cell in all_cells if cell not in forbidden]
    if len(candidates) < MINE_COUNT:
        candidates = [cell for cell in all_cells if cell != safe_cell]

    seed_value = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest(), 16)
    rng = random.Random(seed_value)
    mines = set(rng.sample(candidates, MINE_COUNT))

    state["mines"] = [[r, c] for r, c in sorted(mines)]
    state["adjacent_counts"] = compute_adjacent_counts(mines)
    state["board_ready"] = True



def revealed_safe_tiles(state: dict) -> int:
    mines = mine_set(state)
    total = 0
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if state["revealed"][r][c] and (r, c) not in mines:
                total += 1
    return total



def safe_tiles_left(state: dict) -> int:
    return max(0, SAFE_TILE_COUNT - revealed_safe_tiles(state))



def sync_visible_board(state: dict) -> None:
    mines = mine_set(state)
    board = blank_board()
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if not state["revealed"][r][c]:
                board[r][c] = ""
            elif (r, c) in mines:
                board[r][c] = "M"
            else:
                board[r][c] = str(state["adjacent_counts"][r][c])
    state["board"] = board



def reveal_tiles(state: dict, start: Coordinate) -> int:
    mines = mine_set(state)
    queue: deque[Coordinate] = deque([start])
    seen: set[Coordinate] = set()
    opened = 0

    while queue:
        r, c = queue.popleft()
        if (r, c) in seen:
            continue
        seen.add((r, c))
        if state["revealed"][r][c] or (r, c) in mines:
            continue

        state["revealed"][r][c] = True
        opened += 1
        if state["adjacent_counts"][r][c] == 0:
            for rr, cc in neighbors(r, c):
                if (rr, cc) not in seen and not state["revealed"][rr][cc]:
                    queue.append((rr, cc))

    sync_visible_board(state)
    return opened



def parse_action(issue_title: str, issue_body: str) -> Tuple[str, Optional[Coordinate]]:
    title = (issue_title or "").strip()
    body = (issue_body or "").strip()

    pattern = r"(?:reveal|move)\s*:\s*([1-5])\s*,\s*([1-5])"
    match = re.search(pattern, title, re.IGNORECASE)
    if not match:
        match = re.search(pattern, body, re.IGNORECASE)
    if not match:
        match = re.search(r"\b([1-5])\s*,\s*([1-5])\b", body)

    if match:
        row = int(match.group(1)) - 1
        col = int(match.group(2)) - 1
        return "reveal", (row, col)

    return "invalid", None



def issue_url(repo: str, title: str, labels: str, body: str = "") -> str:
    params = {"title": title, "labels": labels, "template": "move.yml"}
    if body:
        params["body"] = body
    return f"https://github.com/{repo}/issues/new?{urlencode(params)}"



def default_move_issue_body() -> str:
    return (
        "Thanks for playing Minesweeper.\n\n"
        "What happens next:\n"
        "1. Submit this issue with title format reveal:ROW,COL.\n"
        "2. The action reveals that tile on the 5x5 board.\n"
        "3. If you hit a mine, the round ends and a fresh board starts.\n"
        "4. If all safe tiles are cleared, the round is won and a fresh board starts.\n"
        "5. After merge, you get a follow-up comment with credited stats and timing.\n\n"
        "Typical update time after issue creation: 1-3 minutes (depends on approval speed)."
    )



def badge(label: str, value: str, color: str) -> str:
    label_enc = quote(label, safe="")
    value_enc = quote(str(value), safe="")
    return f"![{label}: {value}](https://img.shields.io/badge/{label_enc}-{value_enc}-{color}?style=plastic)"



def tile_badge(value: str, color: str, alt_text: str) -> str:
    value_enc = quote(str(value), safe="")
    return f"![{alt_text}](https://img.shields.io/badge/{value_enc}-{color}?style=flat-square)"



def format_duration_ms(duration_ms: int) -> str:
    duration_ms = max(0, int(duration_ms))
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    seconds = duration_ms / 1000
    if seconds >= 10:
        return f"{seconds:.1f}s"
    return f"{seconds:.2f}s"



def ensure_player_stats(state: dict, username: str) -> dict:
    stats = state.setdefault("player_stats", {})
    if username not in stats:
        stats[username] = {
            "moves_placed": 0,
            "games_played": 0,
            "wins_contributed": 0,
            "human_wins": 0,
            "draws": 0,
        }
    return stats[username]



def user_stats_summary(state: dict, username: str) -> str:
    stats = state.get("player_stats", {}).get(username, {})
    return (
        f"reveals={stats.get('moves_placed', 0)}, "
        f"games={stats.get('games_played', 0)}, "
        f"board_clears={stats.get('wins_contributed', 0)}"
    )



def format_move(move: Optional[Coordinate]) -> str:
    if not move:
        return "-"
    r, c = move
    return f"{r + 1},{c + 1}"



def tile_color_for_count(count: int) -> str:
    colors = {
        0: "9ca3af",
        1: "1d4ed8",
        2: "15803d",
        3: "b91c1c",
        4: "7c3aed",
        5: "c2410c",
        6: "0f766e",
        7: "374151",
        8: "111827",
    }
    return colors.get(count, "6b7280")



def cell_render(state: dict, repo: str, r: int, c: int) -> str:
    mines = mine_set(state)
    if not state["revealed"][r][c]:
        if state["game_status"] == "ongoing":
            link = issue_url(repo, f"reveal:{r + 1},{c + 1}", "minesweeper,reveal", default_move_issue_body())
            return f"[{tile_badge('■', '1f6feb', 'Hidden tile')}]({link})"
        return tile_badge("■", "1f6feb", "Hidden tile")

    if (r, c) in mines:
        return tile_badge("✹", "d73a49", "Mine")

    count = state["adjacent_counts"][r][c]
    if count == 0:
        return tile_badge("·", "9ca3af", "Empty tile")
    return tile_badge(str(count), tile_color_for_count(count), f"{count} adjacent mines")



def render_section(state: dict, repo: str) -> str:
    rows = []
    avg_update_ms = state.get("avg_update_ms")
    if avg_update_ms is None:
        avg_update_ms = int(state.get("avg_update_seconds", 0)) * 1000
    avg_update_text = format_duration_ms(avg_update_ms)

    rows.append("## Minesweeper (Interactive)")
    rows.append("")
    rows.append("Click a hidden tile image below to open a pre-filled issue that reveals that tile on a **5x5 Minesweeper board**.")
    rows.append("The first reveal is guaranteed safe, and each finished round auto-resets to a fresh board.")
    rows.append("")
    rows.append("### Stats Badges")
    rows.append(
        " ".join(
            [
                badge("Boards Cleared", state.get("human_wins", 0), "2ea44f"),
                badge("Mine Hits", state.get("ai_wins", 0), "d73a49"),
                badge("Boards Played", state.get("total_games", 0), "6f42c1"),
                badge("Reveal Actions", state.get("total_human_moves", 0), "0366d6"),
                badge("Mines Per Board", state.get("mine_count", MINE_COUNT), "b60205"),
                badge("Average Action Time", avg_update_text, "fb8500"),
            ]
        )
    )
    rows.append("")

    rows.append("### Board")
    rows.append("|   | 1 | 2 | 3 | 4 | 5 |")
    rows.append("|---|---|---|---|---|---|")
    for r in range(BOARD_SIZE):
        line = [str(r + 1)]
        for c in range(BOARD_SIZE):
            line.append(cell_render(state, repo, r, c))
        rows.append(f"| {' | '.join(line)} |")
    rows.append("")

    rows.append(f"- Status: {'Ongoing' if state.get('game_status') == 'ongoing' else state.get('game_status', 'ongoing').title()}")
    rows.append(f"- Safe tiles left this round: {safe_tiles_left(state)}")
    rows.append(f"- Reveal progress: {revealed_safe_tiles(state)}/{SAFE_TILE_COUNT} safe tiles opened")
    rows.append(f"- Last result: {state.get('last_result', 'No finished games yet')}")
    winners = state.get("last_winners", [])
    winners_text = ", ".join([f"@{w}" for w in winners]) if winners else "None yet"
    rows.append(f"- Last round winners: {winners_text}")
    rows.append("")

    player_stats = state.get("player_stats", {})
    if player_stats:
        rows.append("### Leaderboard")
        rows.append("| Rank | Player | Reveal Actions | Games | Board Clears |")
        rows.append("|---:|---|---:|---:|---:|")
        leaderboard = []
        for username, stats in player_stats.items():
            leaderboard.append(
                {
                    "name": username,
                    "moves": int(stats.get("moves_placed", 0)),
                    "games": int(stats.get("games_played", 0)),
                    "wins": int(stats.get("wins_contributed", 0)),
                }
            )
        sorted_leaderboard = sorted(
            leaderboard,
            key=lambda item: (item["wins"], item["games"], item["moves"], item["name"].lower()),
            reverse=True,
        )
        for index, entry in enumerate(sorted_leaderboard[:10], start=1):
            player_link = f"[@{entry['name']}](https://github.com/{entry['name']})"
            rows.append(
                f"| {index} | {player_link} | {entry['moves']} | {entry['games']} | {entry['wins']} |"
            )
        rows.append("")

    rows.append("Hidden tiles are clickable images linked to issue creation. Revealed numbers show adjacent mine counts.")
    rows.append("Game stats continue across rounds while the board itself resets after each win or mine hit.")
    return "\n".join(rows)



def update_readme(readme_path: str, section: str) -> bool:
    with open(readme_path, "r", encoding="utf-8") as f:
        readme = f.read()

    block = f"{START_MARKER}\n{section}\n{END_MARKER}"
    pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)
    if pattern.search(readme):
        new_readme = pattern.sub(block, readme)
    else:
        suffix = "\n\n" if not readme.endswith("\n") else "\n"
        new_readme = readme + suffix + block + "\n"

    if new_readme == readme:
        return False

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_readme)
    return True



def set_output(name: str, value: str) -> None:
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        return
    with open(output_file, "a", encoding="utf-8") as f:
        f.write(f"{name}<<EOF\n{value}\nEOF\n")



def finalize_and_roll_to_next_game(state: dict, outcome: str) -> str:
    contributors = list(dict.fromkeys(state.get("current_game_contributors", [])))
    for username in contributors:
        player = ensure_player_stats(state, username)
        player["games_played"] = player.get("games_played", 0) + 1

    if outcome == "cleared":
        state["human_wins"] = state.get("human_wins", 0) + 1
        state["last_winner"] = "Players"
        state["winner"] = None
        state["last_result"] = "Board cleared"
        state["last_winners"] = contributors[:]
        for username in contributors:
            player = ensure_player_stats(state, username)
            player["wins_contributed"] = player.get("wins_contributed", 0) + 1
            player["human_wins"] = player.get("human_wins", 0) + 1
    elif outcome == "mine":
        state["ai_wins"] = state.get("ai_wins", 0) + 1
        state["last_winner"] = None
        state["winner"] = None
        state["last_result"] = "Mine triggered"
        state["last_winners"] = []
    else:
        return ""

    state["total_games"] = state.get("total_games", 0) + 1
    result_text = state["last_result"]
    reset_board_state(state)
    return result_text



def handle_reveal(state: dict, move: Coordinate, issue_user: str, issue_number: str) -> Tuple[dict, str, bool, dict]:
    r, c = move
    details = {"human_move": format_move((r, c)), "move_result": "-"}

    if state.get("game_status") != "ongoing":
        reset_board_state(state)

    if state["revealed"][r][c]:
        details["move_result"] = "Tile already revealed"
        return state, "That tile is already revealed. Choose another one.", False, details

    if not state.get("board_ready"):
        seed_text = f"{issue_user}:{issue_number}:{state.get('total_games', 0)}:{r}:{c}"
        initialize_board(state, (r, c), seed_text)

    player = ensure_player_stats(state, issue_user)
    player["moves_placed"] = player.get("moves_placed", 0) + 1
    state["total_human_moves"] = state.get("total_human_moves", 0) + 1
    state.setdefault("current_game_contributors", []).append(issue_user)

    mines = mine_set(state)
    if (r, c) in mines:
        state["revealed"][r][c] = True
        state["last_triggered_mine"] = [r, c]
        sync_visible_board(state)
        result_text = finalize_and_roll_to_next_game(state, "mine")
        details["move_result"] = "Mine hit"
        return (
            state,
            f"Reveal accepted at {r + 1},{c + 1}. You hit a mine. Round finished: {result_text}. New board started.",
            True,
            details,
        )

    opened = reveal_tiles(state, (r, c))
    adjacent = state["adjacent_counts"][r][c]
    remaining = safe_tiles_left(state)
    details["move_result"] = f"Opened {opened} tile(s)"

    if remaining == 0:
        result_text = finalize_and_roll_to_next_game(state, "cleared")
        details["move_result"] = f"Opened {opened} tile(s) and cleared the board"
        return (
            state,
            f"Reveal accepted at {r + 1},{c + 1}. Opened {opened} tile(s). Board cleared. Round finished: {result_text}. New board started.",
            True,
            details,
        )

    return (
        state,
        f"Reveal accepted at {r + 1},{c + 1}. Opened {opened} tile(s). Adjacent mines here: {adjacent}. Safe tiles left: {remaining}.",
        True,
        details,
    )



def process_issue(args: argparse.Namespace) -> int:
    start = time.perf_counter()
    state_path = args.state
    readme_path = args.readme
    repo = args.repo

    state = load_state(state_path)
    action, move = parse_action(args.issue_title, args.issue_body)

    state_changed = False
    move_details = {"human_move": "-", "move_result": "-"}
    if action == "reveal" and move is not None:
        state, message, state_changed, move_details = handle_reveal(state, move, args.issue_user, args.issue_number)
    else:
        message = "Invalid issue format. Use title like reveal:ROW,COL with values 1-5."

    if state_changed:
        save_state(state_path, state)

    readme_changed = update_readme(readme_path, render_section(state, repo))
    should_commit = state_changed or readme_changed

    issue_user = args.issue_user
    last_winners = state.get("last_winners", [])
    credited_win = issue_user in last_winners
    stats_summary = user_stats_summary(state, issue_user)
    user_stats = state.get("player_stats", {}).get(issue_user, {})
    stat_moves = int(user_stats.get("moves_placed", 0))
    stat_games = int(user_stats.get("games_played", 0))
    stat_win_contrib = int(user_stats.get("wins_contributed", 0))
    stats_badges = " ".join(
        [
            badge("Reveal Actions", stat_moves, "1f6feb"),
            badge("Games", stat_games, "8250df"),
            badge("Board Clears", stat_win_contrib, "2ea44f"),
        ]
    )
    processing_ms = int(round((time.perf_counter() - start) * 1000))

    action_latency_seconds = None
    issue_created_at = (args.issue_created_at or "").strip()
    if issue_created_at:
        try:
            created = datetime.fromisoformat(issue_created_at.replace("Z", "+00:00"))
            action_latency_seconds = max(0, int(round(time.time() - created.timestamp())))
        except ValueError:
            action_latency_seconds = None

    if state_changed:
        state["update_samples"] = state.get("update_samples", 0) + 1
        state["total_update_ms"] = state.get("total_update_ms", 0) + processing_ms
        samples = state.get("update_samples", 0)
        total_ms = state.get("total_update_ms", 0)
        state["avg_update_ms"] = int(round(total_ms / samples)) if samples else 0
        state["total_update_seconds"] = int(round(total_ms / 1000))
        state["avg_update_seconds"] = int(round(state["avg_update_ms"] / 1000)) if samples else 0
        save_state(state_path, state)
        readme_changed = update_readme(readme_path, render_section(state, repo))
        should_commit = state_changed or readme_changed

    set_output("comment", message)
    set_output("should_close", "true")
    set_output("should_commit", "true" if should_commit else "false")
    set_output("issue_user", issue_user)
    set_output("player_stats", stats_summary)
    set_output("player_stats_badges", stats_badges)
    set_output("stat_moves", str(stat_moves))
    set_output("stat_games", str(stat_games))
    set_output("stat_win_contributions", str(stat_win_contrib))
    set_output("credited_win", "true" if credited_win else "false")
    set_output("last_result", state.get("last_result", "No finished games yet"))
    set_output("human_move", move_details.get("human_move", "-"))
    set_output("move_result", move_details.get("move_result", "-"))
    set_output("ai_move", move_details.get("move_result", "-"))
    set_output("move_processing_ms", str(processing_ms))
    if action_latency_seconds is not None:
        set_output("action_latency_seconds", str(action_latency_seconds))
    return 0



def initialize(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    if not os.path.exists(args.state):
        save_state(args.state, state)
    else:
        save_state(args.state, state)
    update_readme(args.readme, render_section(state, args.repo))
    return 0



def record_update_time(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    elapsed_ms = max(0, int(args.seconds)) * 1000

    state["update_samples"] = state.get("update_samples", 0) + 1
    state["total_update_ms"] = state.get("total_update_ms", 0) + elapsed_ms
    samples = state.get("update_samples", 0)
    total_ms = state.get("total_update_ms", 0)
    state["avg_update_ms"] = int(round(total_ms / samples)) if samples else 0
    state["total_update_seconds"] = int(round(total_ms / 1000))
    state["avg_update_seconds"] = int(round(state["avg_update_ms"] / 1000)) if samples else 0

    save_state(args.state, state)
    update_readme(args.readme, render_section(state, args.repo))

    set_output("avg_update_seconds", str(state["avg_update_seconds"]))
    set_output("avg_update_ms", str(state["avg_update_ms"]))
    set_output("update_samples", str(state["update_samples"]))
    return 0



def main() -> int:
    parser = argparse.ArgumentParser(description="README Minesweeper backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state", default="game_state.json")
    common.add_argument("--readme", default="README.md")
    common.add_argument("--repo", required=True)

    p_init = subparsers.add_parser("init", parents=[common])
    p_init.set_defaults(func=initialize)

    p_process = subparsers.add_parser("process-issue", parents=[common])
    p_process.add_argument("--issue-title", required=True)
    p_process.add_argument("--issue-body", default="")
    p_process.add_argument("--issue-user", default="unknown")
    p_process.add_argument("--issue-number", default="0")
    p_process.add_argument("--issue-created-at", default="")
    p_process.set_defaults(func=process_issue)

    p_record = subparsers.add_parser("record-update-time", parents=[common])
    p_record.add_argument("--seconds", required=True)
    p_record.set_defaults(func=record_update_time)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
