#!/usr/bin/env python3
"""Refresh public GitHub contribution totals in the profile README."""

import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


USERNAME = "rowkav09"
OWNERS = ("rowkav09", "rowkavdev")
START = "<!-- public-loc:start -->"
END = "<!-- public-loc:end -->"
README = Path(__file__).resolve().parents[1] / "README.md"
TOKEN = os.environ.get("GITHUB_TOKEN")


def api(path):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = Request("https://api.github.com" + path, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except HTTPError as error:
        raise RuntimeError(f"GitHub API returned HTTP {error.code} for {path}") from error


def public_repos(owner):
    kind = "users" if owner == USERNAME else "orgs"
    page = 1
    while True:
        type_filter = "&type=owner" if kind == "users" else ""
        status, repos = api(f"/{kind}/{owner}/repos?per_page=100&page={page}{type_filter}")
        if status != 200 or not isinstance(repos, list):
            raise RuntimeError(f"Cannot list repositories for {owner}")
        for repo in repos:
            if not repo["fork"] and not repo["private"]:
                yield repo["full_name"]
        if len(repos) < 100:
            break
        page += 1


def contribution_totals(repo):
    path = f"/repos/{repo}/stats/contributors"
    for attempt in range(12):
        status, contributors = api(path)
        if status == 202:
            time.sleep(5)
            continue
        if status == 204:
            return 0, 0
        if status != 200 or not isinstance(contributors, list):
            raise RuntimeError(f"Unexpected contributor statistics for {repo}: HTTP {status}")
        for contributor in contributors:
            author = contributor.get("author") or {}
            if author.get("login", "").lower() == USERNAME:
                weeks = contributor["weeks"]
                additions = sum(week["a"] for week in weeks)
                deletions = sum(week["d"] for week in weeks)
                if contributor["total"] and not additions and not deletions:
                    raise RuntimeError(f"GitHub returned zero line counts for {repo}; check its commit count")
                return additions, deletions
        return 0, 0
    raise RuntimeError(f"Timed out waiting for contributor statistics for {repo}")


def badge(label, value, color):
    url = "https://img.shields.io/badge/" + quote(label, safe="") + "-" + quote(f"{value:,}", safe="") + "-" + color
    return f"![{label.title()}]({url})"


def main():
    repos = sorted(set(repo for owner in OWNERS for repo in public_repos(owner)))
    totals = [contribution_totals(repo) for repo in repos]
    added = sum(a for a, _ in totals)
    deleted = sum(d for _, d in totals)
    block = "\n".join((
        START,
        f"{badge('public lines added', added, 'brightgreen')} {badge('public lines deleted', deleted, 'red')}",
        f"<sub>My commits across {len(repos)} public, non-fork repositories on their default branches. "
        "GitHub excludes merge commits; this counts changed lines, including generated files. Updated daily.</sub>",
        END,
    ))
    readme = README.read_text()
    if START not in readme or END not in readme:
        raise RuntimeError("README is missing the public LOC markers")
    before, rest = readme.split(START, 1)
    _, after = rest.split(END, 1)
    README.write_text(before + block + after)
    print(f"Updated {len(repos)} repos: {added:,} added, {deleted:,} deleted")


if __name__ == "__main__":
    main()
