---
name: repo-review
description: "Review the dsm-shai repository status with fixed checks: open pull requests, recent merges, tasklist counts and recent swarm results. Use for 'review the repo', 'how did we do', or any repo status question."
version: 1.0.0
metadata:
  hermes:
    tags: [repo, status, review, github, tasklist]
    category: custom
---

# Repo review

Use this skill for any request to review the repository or report how the work went. Run the checks below in order with the terminal tool. Do not use web search for GitHub. Do not print the token.

Set `REPO=dsm0014/dsm-shai`. The token is in the `GITHUB_TOKEN` environment variable.

## Checks

1. **Open pull requests.** One request, then list number, title and head branch.

   ```
   curl -s -H "Authorization: Bearer $GITHUB_TOKEN" "https://api.github.com/repos/$REPO/pulls?state=open&per_page=50" | python3 -c 'import json,sys; [print(p["number"], p["title"][:90], p["head"]["ref"]) for p in json.load(sys.stdin)]'
   ```

2. **Recent merges.** Ten closed pull requests, keeping those with a `merged_at` value.

   ```
   curl -s -H "Authorization: Bearer $GITHUB_TOKEN" "https://api.github.com/repos/$REPO/pulls?state=closed&sort=updated&direction=desc&per_page=10" | python3 -c 'import json,sys; [print(p["number"], p["merged_at"], p["title"][:90]) for p in json.load(sys.stdin) if p.get("merged_at")]'
   ```

3. **Tasklist counts.** Read the file from `main` and count the open items by marker.

   ```
   curl -s -H "Authorization: Bearer $GITHUB_TOKEN" "https://raw.githubusercontent.com/$REPO/main/.specter/tasklist.md" | python3 -c 'import sys,re; t=sys.stdin.read().splitlines(); print("open", sum(l.startswith("- [ ]") for l in t), "started", sum(l.startswith("- [~]") for l in t), "swarm", sum("[swarm]" in l for l in t), "needs-owner", sum("[needs-owner]" in l for l in t))'
   ```

4. **Recent swarm results.** The last ten lines of the local digest, which the swarm writes.

   ```
   tail -n 10 /opt/data/swarm/digest.log
   ```

## Report

Give one short report, in this order:

- The open pull requests, with any that have been open for more than two days flagged.
- The merges in the last week.
- The tasklist counts, with the number of open swarm items.
- Failures in the last ten swarm lines, grouped by message, with the count.

Say what you verified and what you could not check. Do not guess at anything the checks did not return.
