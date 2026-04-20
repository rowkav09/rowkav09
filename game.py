import argparse
import json
import os
import re
from copy import deepcopy
from typing import List, Optional, Tuple
from urllib.parse import quote, urlencode


START_MARKER = "<!-- TICTACTOE_START -->"
END_MARKER = "<!-- TICTACTOE_END -->"


def default_state() -> dict:
    return {
        "board": [["", "", ""], ["", "", ""], ["", "", ""]],
        "current_turn": "X",
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
        "update_samples": 0,
        "total_update_seconds": 0,
        "avg_update_seconds": 0,
        "player_stats": {},
        "current_game_contributors": [],
        "users_moved": [],
    }


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return default_state()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    defaults = default_state()
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
    return data


def save_state(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def winner(board: List[List[str]]) -> Optional[str]:
    lines = []
    lines.extend(board)
    lines.extend([[board[r][c] for r in range(3)] for c in range(3)])
    lines.append([board[i][i] for i in range(3)])
    lines.append([board[i][2 - i] for i in range(3)])
    for line in lines:
        if line[0] and line[0] == line[1] == line[2]:
            return line[0]
    return None


def board_full(board: List[List[str]]) -> bool:
    return all(cell != "" for row in board for cell in row)


def evaluate_status(state: dict) -> None:
    win = winner(state["board"])
    if win == "X":
        state["game_status"] = "x_won"
        state["winner"] = "X"
        state["current_turn"] = ""
        return
    if win == "O":
        state["game_status"] = "o_won"
        state["winner"] = "O"
        state["current_turn"] = ""
        return
    if board_full(state["board"]):
        state["game_status"] = "draw"
        state["winner"] = None
        state["current_turn"] = ""
        return
    state["game_status"] = "ongoing"
    state["winner"] = None


def available_moves(board: List[List[str]]) -> List[Tuple[int, int]]:
    return [(r, c) for r in range(3) for c in range(3) if board[r][c] == ""]


def minimax(board: List[List[str]], is_o_turn: bool, depth: int) -> int:
    win = winner(board)
    if win == "O":
        return 10 - depth
    if win == "X":
        return depth - 10
    if board_full(board):
        return 0

    moves = available_moves(board)
    if is_o_turn:
        best = -10**9
        for r, c in moves:
            board[r][c] = "O"
            score = minimax(board, False, depth + 1)
            board[r][c] = ""
            best = max(best, score)
        return best

    best = 10**9
    for r, c in moves:
        board[r][c] = "X"
        score = minimax(board, True, depth + 1)
        board[r][c] = ""
        best = min(best, score)
    return best


def choose_ai_move(board: List[List[str]]) -> Tuple[int, int]:
    best_score = -10**9
    best_move = (-1, -1)
    for r, c in available_moves(board):
        test_board = deepcopy(board)
        test_board[r][c] = "O"
        score = minimax(test_board, False, 0)
        if score > best_score:
            best_score = score
            best_move = (r, c)
    return best_move


def parse_action(issue_title: str, issue_body: str) -> Tuple[str, Optional[Tuple[int, int]]]:
    title = (issue_title or "").strip()
    body = (issue_body or "").strip()

    move_match = re.search(r"move\s*:\s*([1-3])\s*,\s*([1-3])", title, re.IGNORECASE)
    if not move_match:
        move_match = re.search(r"move\s*:\s*([1-3])\s*,\s*([1-3])", body, re.IGNORECASE)
    if not move_match:
        move_match = re.search(r"\b([1-3])\s*,\s*([1-3])\b", body)

    if move_match:
        row = int(move_match.group(1)) - 1
        col = int(move_match.group(2)) - 1
        return "move", (row, col)

    return "invalid", None


def issue_url(repo: str, title: str, labels: str, body: str = "") -> str:
    params = {"title": title, "labels": labels, "template": "move.yml"}
    if body:
        params["body"] = body
    return f"https://github.com/{repo}/issues/new?{urlencode(params)}"


def default_move_issue_body() -> str:
    return (
        "Thanks for playing Tic Tac Toe.\n\n"
        "What happens next:\n"
        "1. Submit this issue with title format move:ROW,COL.\n"
        "2. The action validates your move and opens a PR.\n"
        "3. Repo owner merges that PR to approve and publish your move.\n"
        "4. You get a follow-up comment with your credited stats.\n\n"
        "Typical update time after issue creation: 1-3 minutes (depends on approval speed)."
    )


def badge(label: str, value: str, color: str) -> str:
    label_enc = quote(label, safe="")
    value_enc = quote(str(value), safe="")
    return f"![{label}: {value}](https://img.shields.io/badge/{label_enc}-{value_enc}-{color}?style=plastic)"


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
        f"moves={stats.get('moves_placed', 0)}, "
        f"games={stats.get('games_played', 0)}, "
        f"win_contributions={stats.get('wins_contributed', 0)}"
    )


def cell_render(state: dict, repo: str, r: int, c: int) -> str:
    cell = state["board"][r][c]
    if cell == "X":
        return "X"
    if cell == "O":
        return "O"
    if state["game_status"] == "ongoing" and state["current_turn"] == "X":
        link = issue_url(repo, f"move:{r + 1},{c + 1}", "tic-tac-toe,move", default_move_issue_body())
        return f"[⬜]({link})"
    return "⬜"


def render_section(state: dict, repo: str) -> str:
    rows = []
    rows.append("## Tic Tac Toe (Interactive)")
    rows.append("")
    rows.append("Play by clicking a cell button below. Each click opens a pre-filled issue that the action processes.")
    rows.append("")

    rows.append("### Stats Badges")
    rows.append(
        " ".join(
            [
                badge("Human Wins", state.get("human_wins", 0), "2ea44f"),
                badge("AI Wins", state.get("ai_wins", 0), "d73a49"),
                badge("Draws", state.get("draws", 0), "6f42c1"),
                badge("Games Played", state.get("total_games", 0), "0366d6"),
                badge("Human Moves", state.get("total_human_moves", 0), "0e8a16"),
                badge("Avg Update", f"{state.get('avg_update_seconds', 0)}s", "fb8500"),
            ]
        )
    )
    rows.append("")

    player_stats = state.get("player_stats", {})
    if player_stats:
        rows.append("### Contributor Badges")
        sorted_players = sorted(
            player_stats.items(),
            key=lambda item: (
                item[1].get("wins_contributed", 0),
                item[1].get("moves_placed", 0),
                item[1].get("games_played", 0),
            ),
            reverse=True,
        )
        for username, stats in sorted_players[:8]:
            rows.append(
                " ".join(
                    [
                        f"- @{username}",
                        badge("Moves", stats.get("moves_placed", 0), "1f6feb"),
                        badge("Games", stats.get("games_played", 0), "8250df"),
                        badge("Win Contributions", stats.get("wins_contributed", 0), "2ea44f"),
                    ]
                )
            )
        rows.append("")

    rows.append("|   | 1 | 2 | 3 |")
    rows.append("|---|---|---|---|")
    for r in range(3):
        line = [str(r + 1)]
        for c in range(3):
            line.append(cell_render(state, repo, r, c))
        rows.append(f"| {' | '.join(line)} |")
    rows.append("")

    status_text = "Ongoing"
    turn_text = state["current_turn"] if state["current_turn"] else "X"
    rows.append(f"- Current turn: {turn_text}{' (you)' if turn_text == 'X' else ''}")
    rows.append(f"- Status: {status_text}")
    rows.append("- AI: O (minimax)")
    rows.append(f"- Last result: {state.get('last_result', 'No finished games yet')}")
    winners = state.get("last_winners", [])
    if winners:
        winners_text = ", ".join([f"@{w}" if w != "AI" else "AI" for w in winners])
    else:
        winners_text = "None yet"
    rows.append(f"- Last round winners: {winners_text}")
    rows.append("")
    rows.append("Game auto-resets after each finished round and always stays playable.")

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


def finalize_and_roll_to_next_game(state: dict) -> str:
    contributors = list(dict.fromkeys(state.get("current_game_contributors", [])))
    for username in contributors:
        player = ensure_player_stats(state, username)
        player["games_played"] = player.get("games_played", 0) + 1

    if state["game_status"] == "x_won":
        state["human_wins"] = state.get("human_wins", 0) + 1
        state["last_winner"] = "X"
        state["last_result"] = "Human (X) won"
        state["last_winners"] = contributors[:]
        for username in contributors:
            player = ensure_player_stats(state, username)
            player["wins_contributed"] = player.get("wins_contributed", 0) + 1
            player["human_wins"] = player.get("human_wins", 0) + 1
    elif state["game_status"] == "o_won":
        state["ai_wins"] = state.get("ai_wins", 0) + 1
        state["last_winner"] = "O"
        state["last_result"] = "AI (O) won"
        state["last_winners"] = ["AI"]
    elif state["game_status"] == "draw":
        state["draws"] = state.get("draws", 0) + 1
        state["last_winner"] = None
        state["last_result"] = "Draw"
        state["last_winners"] = []
        for username in contributors:
            player = ensure_player_stats(state, username)
            player["draws"] = player.get("draws", 0) + 1
    else:
        return ""

    state["total_games"] = state.get("total_games", 0) + 1

    # Start a fresh game immediately while keeping accumulated stats.
    state["board"] = [["", "", ""], ["", "", ""], ["", "", ""]]
    state["current_turn"] = "X"
    state["game_status"] = "ongoing"
    state["winner"] = None
    state["current_game_contributors"] = []
    state["users_moved"] = []

    return state["last_result"]


def handle_move(state: dict, move: Tuple[int, int], issue_user: str) -> Tuple[dict, str, bool]:
    r, c = move

    if state["current_turn"] != "X":
        return state, "It is not X turn right now. Please try again shortly.", False

    if issue_user in state.get("users_moved", []):
        return state, "You already made a move in this round. Wait for the next round.", False

    if state["board"][r][c] != "":
        return state, "That cell is already occupied. Choose another one.", False

    state["board"][r][c] = "X"
    player = ensure_player_stats(state, issue_user)
    player["moves_placed"] = player.get("moves_placed", 0) + 1
    state["total_human_moves"] = state.get("total_human_moves", 0) + 1
    state.setdefault("users_moved", []).append(issue_user)
    state.setdefault("current_game_contributors", []).append(issue_user)
    evaluate_status(state)
    if state["game_status"] != "ongoing":
        result_text = finalize_and_roll_to_next_game(state)
        return state, f"Move accepted at {r + 1},{c + 1}. Round finished: {result_text}. New round started.", True

    state["current_turn"] = "O"
    ai_r, ai_c = choose_ai_move(state["board"])
    if ai_r >= 0:
        state["board"][ai_r][ai_c] = "O"
    evaluate_status(state)
    if state["game_status"] == "ongoing":
        state["current_turn"] = "X"
        return state, f"Move accepted at {r + 1},{c + 1}. AI played {ai_r + 1},{ai_c + 1}.", True

    result_text = finalize_and_roll_to_next_game(state)
    return state, f"Move accepted at {r + 1},{c + 1}. AI played {ai_r + 1},{ai_c + 1}. Round finished: {result_text}. New round started.", True


def process_issue(args: argparse.Namespace) -> int:
    state_path = args.state
    readme_path = args.readme
    repo = args.repo

    state = load_state(state_path)
    action, move = parse_action(args.issue_title, args.issue_body)

    state_changed = False
    if action == "move" and move is not None:
        state, message, state_changed = handle_move(state, move, args.issue_user)
    else:
        message = "Invalid issue format. Use title like move:ROW,COL with values 1-3."

    if state_changed:
        save_state(state_path, state)

    readme_changed = update_readme(readme_path, render_section(state, repo))
    should_commit = state_changed or readme_changed

    issue_user = args.issue_user
    last_winners = state.get("last_winners", [])
    credited_win = issue_user in [w for w in last_winners if w != "AI"]
    stats_summary = user_stats_summary(state, issue_user)

    set_output("comment", message)
    set_output("should_close", "true")
    set_output("should_commit", "true" if should_commit else "false")
    set_output("issue_user", issue_user)
    set_output("player_stats", stats_summary)
    set_output("credited_win", "true" if credited_win else "false")
    set_output("last_result", state.get("last_result", "No finished games yet"))
    return 0


def initialize(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    if not os.path.exists(args.state):
        save_state(args.state, state)
    update_readme(args.readme, render_section(state, args.repo))
    return 0


def record_update_time(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    elapsed = max(0, int(args.seconds))

    state["update_samples"] = state.get("update_samples", 0) + 1
    state["total_update_seconds"] = state.get("total_update_seconds", 0) + elapsed
    samples = state.get("update_samples", 0)
    total = state.get("total_update_seconds", 0)
    state["avg_update_seconds"] = int(round(total / samples)) if samples else 0

    save_state(args.state, state)
    update_readme(args.readme, render_section(state, args.repo))

    set_output("avg_update_seconds", str(state["avg_update_seconds"]))
    set_output("update_samples", str(state["update_samples"]))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Tic Tac Toe README game backend")
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
    p_process.set_defaults(func=process_issue)

    p_record = subparsers.add_parser("record-update-time", parents=[common])
    p_record.add_argument("--seconds", required=True)
    p_record.set_defaults(func=record_update_time)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())