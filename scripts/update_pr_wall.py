#!/usr/bin/env python3
"""自动更新 README 中的开源贡献 PR 墙（<!-- PR-WALL:START/END --> 区块之间）。

筛选与排序机制（防止无限膨胀，突出最佳成果）：
  1. 只收录外部仓库（非本人拥有）的 open / merged PR；已关闭未合并的一律不展示
  2. open 且超过 STALE_OPEN_DAYS 天无任何活动的 PR 视为"石沉大海"，自动隐藏
  3. 排序：merged PR 永远排在 open 之前（成果 > 在途），各自组内按仓库 star 数降序，
     最多展示 MAX_ROWS 条
  4. Merged / Open 徽章统计的是全部外部 PR（不只展示的子集）

用法：
  GH_TOKEN=<token> python3 scripts/update_pr_wall.py
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

# ---- 可调参数 -------------------------------------------------------------
GITHUB_USER = "ProgrammerPlus1998"
MAX_ROWS = 20            # PR 墙最多展示的条数
STALE_OPEN_DAYS = 180    # open PR 超过 N 天无活动则隐藏
README_PATH = os.path.join(os.path.dirname(__file__), "..", "README.md")
# ---------------------------------------------------------------------------

QUERY = """
query($qAll: String!, $qMerged: String!, $qOpen: String!) {
  prs: search(query: $qAll, type: ISSUE, first: 100) {
    nodes {
      ... on PullRequest {
        number
        title
        url
        state
        updatedAt
        repository {
          nameWithOwner
          stargazerCount
          isArchived
        }
      }
    }
  }
  merged: search(query: $qMerged, type: ISSUE, first: 1) { issueCount }
  open: search(query: $qOpen, type: ISSUE, first: 1) { issueCount }
}
"""


def graphql(token, query, variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise RuntimeError(f"GitHub GraphQL error: {payload['errors']}")
    return payload["data"]


def fmt_stars(stars):
    return f"{stars:,}"


def build_wall(prs, merged_total, open_total):
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=STALE_OPEN_DAYS)

    rows = []
    for pr in prs:
        repo = pr["repository"]
        if repo["isArchived"]:
            continue  # 仓库已归档，不展示
        state = pr["state"]
        updated = datetime.fromisoformat(pr["updatedAt"].replace("Z", "+00:00"))
        if state == "OPEN" and updated < stale_cutoff:
            continue  # 石沉大海的 open PR，不展示
        if state not in ("OPEN", "MERGED"):
            continue  # 关闭未合并，不展示
        stars = repo["stargazerCount"]
        # 第一排序键：merged=0 排在 open=1 之前（成果优先于在途）
        tier = 0 if state == "MERGED" else 1
        rows.append((tier, stars, updated, pr, repo, state))

    # merged 优先，组内按仓库 star 数降序
    rows.sort(key=lambda r: (r[0], -r[1]))
    rows = rows[:MAX_ROWS]

    lines = [
        f"| Project | Stars | PR | Status |",
        f"|---------|-------|----|--------|",
    ]
    for _, _, _, pr, repo, state in rows:
        name = repo["nameWithOwner"]
        title = pr["title"].replace("|", "\\|")
        status = "✅ merged" if state == "MERGED" else "🔄 open"
        lines.append(
            f"| [{name}](https://github.com/{name}) "
            f"| ![stars](https://img.shields.io/github/stars/{name}?style=flat&color=gold) "
            f"| [#{pr['number']} {title}]({pr['url']}) "
            f"| {status} |"
        )

    table = "\n".join(lines)
    badges = f"""<div align="center">
  <img src="https://img.shields.io/badge/Merged%20PRs-{merged_total}-brightgreen?style=for-the-badge&logo=github"/>
  <img src="https://img.shields.io/badge/Open%20PRs-{open_total}-blue?style=for-the-badge&logo=github"/>
  <img src="https://img.shields.io/badge/Focus-MCP%20%C2%B7%20Agent%20%C2%B7%20Memory-FF6F00?style=for-the-badge&logo=probot&logoColor=white"/>
</div>"""

    return f"""<!-- PR-WALL:START -->
<!-- 🤖 此区块由 scripts/update_pr_wall.py + GitHub Actions 自动生成，请勿手改 -->
<!-- 机制：merged 优先 / 仓库 star 排序 / 上限 {MAX_ROWS} 条 / open 超 {STALE_OPEN_DAYS} 天无响应自动隐藏 -->

{table}

{badges}
<!-- PR-WALL:END -->"""


def main():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("需要 GH_TOKEN 或 GITHUB_TOKEN 环境变量")

    base = f"type:pr author:{GITHUB_USER} -user:{GITHUB_USER} draft:false"
    data = graphql(
        token,
        QUERY,
        {
            "qAll": base,
            "qMerged": f"{base} is:merged",
            "qOpen": f"{base} is:open",
        },
    )

    wall = build_wall(
        data["prs"]["nodes"],
        data["merged"]["issueCount"],
        data["open"]["issueCount"],
    )

    readme_path = os.path.abspath(README_PATH)
    with open(readme_path, encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(r"<!-- PR-WALL:START -->.*?<!-- PR-WALL:END -->", re.S)
    if not pattern.search(content):
        sys.exit("README.md 中找不到 <!-- PR-WALL:START/END --> 标记")
    content = pattern.sub(wall, content)

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"PR 墙已更新：merged={data['merged']['issueCount']} open={data['open']['issueCount']}")


if __name__ == "__main__":
    main()
