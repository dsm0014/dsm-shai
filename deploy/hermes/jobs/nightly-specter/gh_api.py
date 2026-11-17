"""Minimal GitHub REST client for the nightly job (spec 11). Standard library, no gh CLI (the image has none).

Token comes from GITHUB_TOKEN; the repo is NIGHTLY_REPO (owner/name); the API base is NIGHTLY_API_BASE (tests point it
at a local stub). Egress to api.github.com goes through the proxy via HTTPS_PROXY (urllib honours it).
"""
import json, os, urllib.parse, urllib.request

BASE = os.environ.get("NIGHTLY_API_BASE", "https://api.github.com")


class ApiError(Exception):
    pass


def _req(method, path, body=None):
    url = path if path.startswith("http") else BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + os.environ.get("GITHUB_TOKEN", ""), "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "dsm-shai-nightly-specter", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise ApiError("%s %s -> %s" % (method, path.split("?")[0], e.code))


def repo():
    return os.environ["NIGHTLY_REPO"]


def prs(state):
    out = _req("GET", "/repos/%s/pulls?state=%s&per_page=100" % (repo(), state))
    return [{"title": p["title"], "url": p["html_url"], "branch": p["head"]["ref"], "number": p["number"],
             "created_at": p.get("created_at", "")} for p in out if p["head"]["ref"].startswith("nightly/")]


def default_branch():
    return _req("GET", "/repos/%s" % repo()).get("default_branch", "main")


def create_pr(branch, title, body, base, draft=False):
    return _req("POST", "/repos/%s/pulls" % repo(), {"title": title, "head": branch, "base": base, "body": body, "draft": draft})


def merge_pr(number):
    return _req("PUT", "/repos/%s/pulls/%d/merge" % (repo(), number), {"merge_method": "merge"})


def delete_branch(branch):
    try:
        _req("DELETE", "/repos/%s/git/refs/heads/%s" % (repo(), branch))
    except ApiError:
        pass


def search_repos(query, cap=5):
    q = urllib.parse.quote(query + " stars:>=50 archived:false")
    items = _req("GET", "/search/repositories?q=%s&sort=stars&per_page=20" % q).get("items", [])
    return [{"full_name": i["full_name"], "url": i["html_url"], "stars": i["stargazers_count"],
             "pushed_at": i["pushed_at"], "license": (i.get("license") or {}).get("spdx_id", "NOASSERTION")} for i in items][:cap]


def readme(full_name):
    import base64
    d = _req("GET", "/repos/%s/readme" % full_name)
    return base64.b64decode(d.get("content", "")).decode("utf-8", "replace")


def top_tree(full_name):
    d = _req("GET", "/repos/%s/contents" % full_name)
    return [x["name"] + ("/" if x["type"] == "dir" else "") for x in d]
