#!/usr/bin/env python3
"""
hubgit — one git/GitHub helper shared by the Discord hub bot AND the AI agents.
 
Why it exists
  * The bot's manual commands (!pull, !sync, !ship, ...) call these functions.
  * Agents (Claude / Cursor / Antigravity) are told to run this script for git work,
    so commits and PRs come out under YOUR git identity, with no
    "Co-authored-by: Claude/Cursor" trailers and no accidental force-pushes.
 
Usage (agents and humans)
  python3 hubgit.py <command> [--repo <name|all>] [options]
 
  repos                                   list git repos under the project root
  branch | status | pull                  read / sync current branch
  checkout <branch>                       stash -> switch -> pull           (changes stay stashed)
  sync <branch>                           stash -> switch -> pull -> unstash
  new-branch <name> [--from <ref>]        create + switch (or just switch if it exists)
  commit -m "msg" [--files a b ...]       stage (all, or only those files) + commit
  push [--branch b] [--allow-protected]   push current branch (never forced)
  pr --title T --body B [--base B]        open a PR for the current branch
  ship <new_branch> --title T --body B [--base B]
                                          new-branch + commit + push + PR in one go
  merge <branch>                          merge a branch into the current one
  stash push|pop|list [-m msg]
  conflicts                               list conflicted files + what is in progress
  continue                                after fixing conflict markers: stage + finish merge/rebase/cherry-pick
  abort                                   abort the merge/rebase/cherry-pick in progress
 
Output is a single JSON line: {"ok": bool, "results": [{"repo":..., "status":..., ...}]}
Exit code is 0 when everything is ok, 1 otherwise.
 
Project root for --repo lookups = $HUBGIT_BASE_DIR, else the current directory.
"""
from __future__ import annotations
 
import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any, Callable
 
PROTECTED_BRANCHES = {"main", "master"}
STASH_MSG = "discord-bot-auto-stash"
OK_STATUSES = {"done", "nothing_to_commit", "skipped", "nothing_to_abort"}
 
_AI = r"(claude|cursor|anthropic|gemini|antigravity|openai|copilot|codex)"
TRAILER_RE = re.compile(rf"^\s*co-authored-by:.*{_AI}", re.I)
GENERATED_RE = re.compile(rf"^\s*(🤖\s*)?generated\s+(with|by)\b.*{_AI}", re.I)
 
 
 
# ----------------------------------------------------------------------------
# low-level helpers
# ----------------------------------------------------------------------------
def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")  # never hang asking for credentials
    env["GIT_EDITOR"] = "true"                  # never open an editor
    env.setdefault("GH_PROMPT_DISABLED", "1")
    return env
 
 
def _run(cmd: list[str], cwd: str) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, errors="replace", env=_env()
        )
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found"
    return p.returncode, p.stdout, p.stderr
 
 
def git(cwd: str, *args: str) -> tuple[int, str]:
    """Runs git; returns (returncode, stdout+stderr with trailing newlines trimmed)."""
    rc, out, err = _run(["git", *args], cwd)
    parts = [s.rstrip("\n") for s in (out, err) if s.strip("\n")]
    return rc, "\n".join(parts)
 
 
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
 
 
def tail(text: str, n: int = 400) -> str:
    text = _ANSI.sub("", text).strip()
    return text if len(text) <= n else "…" + text[-n:]
 
 
def res(repo: str, status: str, **extra: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"repo": repo, "status": status, "ok": status in OK_STATUSES}
    d.update(extra)
    return d
 
 
def clean_message(text: str) -> str:
    """Drops AI co-author / 'generated with' lines so nothing but you ends up credited."""
    kept = [ln for ln in text.splitlines() if not TRAILER_RE.search(ln) and not GENERATED_RE.search(ln)]
    return "\n".join(kept).strip()
 
 
def current_branch(cwd: str) -> str:
    rc, out = git(cwd, "branch", "--show-current")
    return out.strip() if rc == 0 else ""
 
 
def unmerged_files(cwd: str) -> list[str]:
    _, out = git(cwd, "diff", "--name-only", "--diff-filter=U")
    return [ln for ln in out.splitlines() if ln.strip()]
 
 
def has_conflict(output_text: str, cwd: str) -> bool:
    _, unmerged = git(cwd, "ls-files", "-u")
    return bool(unmerged.strip()) or "CONFLICT" in output_text.upper()
 
 
def branch_exists(cwd: str, branch: str, fetch: bool = True) -> bool:
    if fetch:
        git(cwd, "fetch", "origin", "--prune")
    rc1, _ = git(cwd, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    rc2, _ = git(cwd, "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}")
    return rc1 == 0 or rc2 == 0
 
 
def valid_branch_name(cwd: str, name: str) -> bool:
    if not name or name.startswith("-"):
        return False
    rc, _ = git(cwd, "check-ref-format", "--branch", name)
    return rc == 0
 
 
def is_sensitive(path: str) -> bool:
    b = os.path.basename(path).lower()
    if b == ".env":
        return True
    if b.startswith(".env.") and not b.endswith((".example", ".sample", ".template", ".dist")):
        return True
    if b.endswith((".pem", ".p12", ".pfx")):
        return True
    return b in {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}
 
 
def repo_state(path: str) -> str | None:
    rc, gd = git(path, "rev-parse", "--git-dir")
    if rc != 0:
        return None
    gd = gd.strip()
    if not os.path.isabs(gd):
        gd = os.path.join(path, gd)
    if os.path.exists(os.path.join(gd, "MERGE_HEAD")):
        return "merge"
    if os.path.isdir(os.path.join(gd, "rebase-merge")) or os.path.isdir(os.path.join(gd, "rebase-apply")):
        return "rebase"
    if os.path.exists(os.path.join(gd, "CHERRY_PICK_HEAD")):
        return "cherry-pick"
    if os.path.exists(os.path.join(gd, "REVERT_HEAD")):
        return "revert"
    return None
 
 
def has_markers(file_path: str) -> bool:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("<<<<<<< ") or line.startswith(">>>>>>> "):
                    return True
    except OSError:
        pass  # deleted / unreadable (e.g. deleted-by-them): nothing to check
    return False
 
 
# ----------------------------------------------------------------------------
# repo discovery
# ----------------------------------------------------------------------------
def find_git_repos(base_dir: str) -> list[str]:
    """Repo folders (relative to base_dir) up to 3 levels deep. Skips node_modules and the root itself."""
    base_dir = os.path.abspath(base_dir)
    repos: list[str] = []
    for root, dirs, _ in os.walk(base_dir):
        rel = os.path.relpath(root, base_dir)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if ".git" in dirs:
            if rel != ".":
                repos.append(rel)
            dirs.remove(".git")
        dirs[:] = [d for d in dirs if d != "node_modules"]
        if depth >= 3:
            dirs[:] = []
    return sorted(repos)
 
 
def resolve_target_repos(
    base_dir: str, active_repo: str, repo_arg: str | None = None
) -> list[tuple[str, str]] | None:
    all_repos = find_git_repos(base_dir)
    target = repo_arg.lstrip("@") if repo_arg else active_repo
 
    if target in ["all", "root"]:
        return [(r, os.path.join(base_dir, r)) for r in all_repos]
 
    exact_path = os.path.join(base_dir, target)
    if os.path.isdir(os.path.join(exact_path, ".git")):
        return [(target, exact_path)]
 
    matches = [r for r in all_repos if r == target or r.endswith(f"/{target}")]
    if len(matches) == 1:
        return [(matches[0], os.path.join(base_dir, matches[0]))]
 
    return None
 
 
def map_targets(targets: list[tuple[str, str]], fn: Callable[..., dict], *a: Any, **kw: Any) -> list[dict]:
    return [fn(name, path, *a, **kw) for name, path in targets]
 
 
def status_text(r: dict[str, Any]) -> str:
    """Short text the Discord bot shows for a result."""
    s = r["status"]
    if s == "detached":
        return "detached HEAD"
    if s == "error":
        return f"error: {r.get('detail', '')[:120]}"
    return s
 
 
# ----------------------------------------------------------------------------
# operations — each returns a result dict
# ----------------------------------------------------------------------------
def op_branch(repo: str, path: str) -> dict:
    b = current_branch(path)
    return res(repo, "done", branch=b or None)
 
 
def op_status(repo: str, path: str) -> dict:
    branch = current_branch(path)
    _, short = git(path, "status", "-s")
    _, stat = git(path, "diff", "--stat")
    return res(
        repo, "done", branch=branch or None, clean=not short.strip(),
        status_short=short, files=[ln for ln in short.splitlines() if ln.strip()], diff_stat=stat,
    )
 
 
def op_pull(repo: str, path: str) -> dict:
    branch = current_branch(path)
    if not branch:
        return res(repo, "detached", detail="detached HEAD — checkout a branch first")
    rc, out = git(path, "pull", "origin", branch)
    if has_conflict(out, path):
        return res(repo, "conflicts", files=unmerged_files(path), detail=tail(out))
    if rc == 0:
        return res(repo, "done", branch=branch, detail=tail(out, 200))
    return res(repo, "error", detail=tail(out))
 
 
def op_checkout(repo: str, path: str, branch: str, sync: bool = False) -> dict:
    """checkout: stash -> switch -> pull.   sync: stash -> switch -> pull -> unstash."""
    if not valid_branch_name(path, branch):
        return res(repo, "error", detail=f"invalid branch name `{branch}`")
    if not branch_exists(path, branch):
        return res(repo, "not exist", detail=f"branch `{branch}` not found locally or on origin")
 
    _, dirty = git(path, "status", "--porcelain")
    did_stash = False
    if dirty.strip():
        rc_s, _ = git(path, "stash", "push", "-u", "-m", STASH_MSG)
        did_stash = rc_s == 0
 
    rc_c, out_c = git(path, "checkout", branch)
    if rc_c != 0:
        if did_stash:
            git(path, "stash", "pop")  # put the work back where it was
        return res(repo, "error", detail=f"checkout failed: {tail(out_c, 200)}")
 
    rc_p, pull_out = git(path, "pull", "origin", branch)
    pop_out = ""
    if sync and did_stash:
        _, pop_out = git(path, "stash", "pop")
 
    if has_conflict(pull_out + "\n" + pop_out, path):
        return res(repo, "conflicts", files=unmerged_files(path), detail=tail(pull_out + "\n" + pop_out))
    if rc_p == 0:
        extra = {"stash_kept": True} if (did_stash and not sync) else {}
        return res(repo, "done", branch=branch, **extra)
    return res(repo, "error", detail=tail((pull_out + " " + pop_out).strip()))
 
 
def op_new_branch(repo: str, path: str, name: str, base_ref: str | None = None) -> dict:
    if not valid_branch_name(path, name):
        return res(repo, "error", detail=f"invalid branch name `{name}`")
    args = ["checkout", "-b", name] + ([base_ref] if base_ref else [])
    rc, out = git(path, *args)
    if rc == 0:
        return res(repo, "done", branch=name, created=True)
    rc2, out2 = git(path, "checkout", name)  # already exists -> just switch
    if rc2 == 0:
        return res(repo, "done", branch=name, created=False)
    return res(repo, "error", detail=tail(out2 or out, 200))
 
 
def op_commit(repo: str, path: str, message: str, files: list[str] | None = None) -> dict:
    msg = clean_message(message)
    if not msg:
        return res(repo, "error", detail="empty commit message")
 
    unresolved = [f for f in unmerged_files(path) if has_markers(os.path.join(path, f))]
    if unresolved:
        return res(repo, "conflicts", files=unresolved,
                   detail="conflict markers (<<<<<<< / >>>>>>>) are still in these files — resolve them before committing")
 
    skipped: list[str] = []
    if files:
        rc, out = git(path, "add", "--", *files)
        if rc != 0:
            return res(repo, "error", detail=f"git add failed: {tail(out, 200)}")
    else:
        git(path, "add", "-A")
        rc, names = _run(["git", "diff", "--cached", "--name-only", "-z"], path)[:2]
        for f in [n for n in names.split("\0") if n]:
            if is_sensitive(f):
                if git(path, "reset", "-q", "--", f)[0] != 0:
                    git(path, "rm", "--cached", "-q", "--", f)
                skipped.append(f)
 
    _, staged = git(path, "diff", "--cached", "--name-only")
    if not staged.strip():
        return res(repo, "nothing_to_commit", skipped_sensitive=skipped)
 
    rc, out = git(path, "commit", "-m", msg)
    if rc != 0:
        return res(repo, "error", detail=tail(out, 300))
    _, sha = git(path, "rev-parse", "--short", "HEAD")
    return res(repo, "done", commit=sha.strip(), skipped_sensitive=skipped)
 
 
def op_push(repo: str, path: str, branch: str | None = None, allow_protected: bool = False) -> dict:
    branch = branch or current_branch(path)
    if not branch:
        return res(repo, "error", detail="detached HEAD — pass --branch")
    if not valid_branch_name(path, branch):
        return res(repo, "error", detail=f"invalid branch name `{branch}`")
    if branch.lower() in PROTECTED_BRANCHES and not allow_protected:
        return res(
            repo, "refused",
            detail=f"direct pushes to `{branch}` are blocked — use a feature branch + PR "
                   f"(pass --allow-protected only if the user explicitly asked for this)",
        )
    rc, out = git(path, "push", "-u", "origin", branch)  # never forced
    if rc != 0:
        return res(repo, "error", detail=tail(out, 300))
    return res(repo, "done", branch=branch)
 
 
def op_pr(repo: str, path: str, title: str, body: str, base: str | None = None, head: str | None = None) -> dict:
    head = head or current_branch(path)
    if not head:
        return res(repo, "error", detail="detached HEAD — pass --head")
    cmd = ["gh", "pr", "create", "--title", clean_message(title) or title,
           "--body", clean_message(body), "--head", head]
    if base:
        cmd += ["--base", base]
    rc, out, err = _run(cmd, path)
    text = (out + "\n" + err).strip()
    if rc != 0:
        return res(repo, "error", detail=tail(text, 300))
    url = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip().startswith("http")), text)
    return res(repo, "done", pr_url=url)
 
 
def op_ship(
    repo: str, path: str, new_branch: str, title: str, body: str,
    base: str | None = None, require_changes: bool = False,
) -> dict:
    """new-branch + commit + push + PR. With require_changes, repos with a clean tree are skipped."""
    _, dirty = git(path, "status", "--porcelain")
    if require_changes and not dirty.strip():
        return res(repo, "skipped", detail="no uncommitted changes")
 
    if base and not branch_exists(path, base):
        return res(repo, "error", step="base", detail=f"Target base branch `{base}` does not exist.")
 
    r = op_new_branch(repo, path, new_branch)
    if not r["ok"]:
        return res(repo, "error", step="branch", detail=f"Failed to switch/create branch `{new_branch}` ({r['detail'][:100]}).")
 
    c = op_commit(repo, path, title)
    if not c["ok"]:
        return res(repo, "error", step="commit", detail=f"Commit failed ({c['detail'][:120]}).")
 
    p = op_push(repo, path, new_branch)
    if not p["ok"]:
        return res(repo, "error", step="push", detail=f"Push failed ({p['detail'][:120]}).")
 
    pr = op_pr(repo, path, title, body, base=base, head=new_branch)
    if not pr["ok"]:
        return res(repo, "error", step="pr", detail=f"PR Failed → `{pr['detail'][:200]}`")
    return res(repo, "done", branch=new_branch, pr_url=pr["pr_url"], skipped_sensitive=c.get("skipped_sensitive", []))
 
 
def op_merge(repo: str, path: str, branch: str) -> dict:
    if not valid_branch_name(path, branch):
        return res(repo, "error", detail=f"invalid branch name `{branch}`")
    if not branch_exists(path, branch):
        return res(repo, "not exist", detail=f"branch `{branch}` not found locally or on origin")
    rc_l, _ = git(path, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    ref = branch if rc_l == 0 else f"origin/{branch}"
    rc, out = git(path, "merge", "--no-edit", ref)
    if has_conflict(out, path):
        return res(repo, "conflicts", files=unmerged_files(path), detail=tail(out))
    if rc == 0:
        return res(repo, "done", detail=tail(out, 200))
    return res(repo, "error", detail=tail(out))
 
 
def op_stash(repo: str, path: str, action: str, message: str | None = None) -> dict:
    if action == "list":
        _, out = git(path, "stash", "list")
        return res(repo, "done", stashes=[ln for ln in out.splitlines() if ln.strip()])
    if action == "push":
        rc, out = git(path, "stash", "push", "-u", "-m", message or STASH_MSG)
        if "No local changes" in out:
            return res(repo, "skipped", detail="no local changes to stash")
        return res(repo, "done" if rc == 0 else "error", detail=tail(out, 200))
    if action == "pop":
        rc, out = git(path, "stash", "pop")
        if has_conflict(out, path):
            return res(repo, "conflicts", files=unmerged_files(path), detail=tail(out))
        return res(repo, "done" if rc == 0 else "error", detail=tail(out, 200))
    return res(repo, "error", detail=f"unknown stash action `{action}`")
 
 
def op_conflicts(repo: str, path: str) -> dict:
    files = unmerged_files(path)
    return res(repo, "done", in_progress=repo_state(path), files=files, clean=not files)
 
 
def op_continue(repo: str, path: str) -> dict:
    state = repo_state(path)
    if not state:
        return res(repo, "error", detail="nothing to continue (no merge/rebase/cherry-pick/revert in progress)")
 
    files = unmerged_files(path)
    with_markers = [f for f in files if has_markers(os.path.join(path, f))]
    if with_markers:
        return res(repo, "conflicts", files=with_markers, detail="conflict markers (<<<<<<< / >>>>>>>) are still in these files")
    for f in files:
        git(path, "add", "-A", "--", f)
 
    cmds = {
        "merge": ["commit", "--no-edit"],
        "rebase": ["rebase", "--continue"],
        "cherry-pick": ["cherry-pick", "--continue"],
        "revert": ["revert", "--continue"],
    }
    rc, out = git(path, *cmds[state])
    remaining = unmerged_files(path)
    if remaining:
        return res(repo, "conflicts", files=remaining, detail=tail(out))
    if rc == 0:
        return res(repo, "done", finished=state, detail=tail(out, 200))
    return res(repo, "error", detail=tail(out))
 
 
def op_abort(repo: str, path: str) -> dict:
    state = repo_state(path)
    if not state:
        return res(repo, "nothing_to_abort", detail="no merge/rebase/cherry-pick/revert in progress")
    cmd = {"merge": "merge", "rebase": "rebase", "cherry-pick": "cherry-pick", "revert": "revert"}[state]
    rc, out = git(path, cmd, "--abort")
    return res(repo, "done" if rc == 0 else "error", aborted=state, detail=tail(out, 200))
 
 
# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
SINGLE_REPO_ONLY = {"new-branch", "commit", "push", "pr", "merge", "continue", "abort", "stash"}
 
 
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="repo name, or 'all'. Needed when not inside a single repo.")
 
    p = argparse.ArgumentParser(prog="hubgit.py", description="Shared git/GitHub helper (JSON output).")
    sub = p.add_subparsers(dest="cmd", required=True)
 
    sub.add_parser("repos", parents=[common])
    for name in ("branch", "status", "pull", "conflicts", "continue", "abort"):
        sub.add_parser(name, parents=[common])
    for name in ("checkout", "sync", "merge"):
        s = sub.add_parser(name, parents=[common])
        s.add_argument("branch")
 
    s = sub.add_parser("new-branch", parents=[common])
    s.add_argument("name")
    s.add_argument("--from", dest="base_ref")
 
    s = sub.add_parser("commit", parents=[common])
    s.add_argument("-m", "--message", required=True)
    s.add_argument("--files", nargs="+")
 
    s = sub.add_parser("push", parents=[common])
    s.add_argument("--branch")
    s.add_argument("--allow-protected", action="store_true")
 
    s = sub.add_parser("pr", parents=[common])
    s.add_argument("--title", required=True)
    s.add_argument("--body", default="")
    s.add_argument("--base")
    s.add_argument("--head")
 
    s = sub.add_parser("ship", parents=[common])
    s.add_argument("new_branch")
    s.add_argument("--title", required=True)
    s.add_argument("--body", default="")
    s.add_argument("--base")
 
    s = sub.add_parser("stash", parents=[common])
    s.add_argument("action", choices=["push", "pop", "list"])
    s.add_argument("-m", "--message")
    return p
 
 
def cli_targets(base: str, repo_arg: str | None) -> list[tuple[str, str]] | None:
    if repo_arg:
        return resolve_target_repos(base, "root", repo_arg)
    cwd = os.getcwd()
    rc, top = git(cwd, "rev-parse", "--show-toplevel")
    if rc == 0 and top.strip():
        top = top.strip()
        rel = os.path.relpath(top, base)
        name = os.path.basename(top) if rel.startswith("..") else rel
        return [(name, top)]
    return None
 
 
def emit(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1
 
 
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base = os.path.abspath(os.environ.get("HUBGIT_BASE_DIR") or os.getcwd())
 
    if args.cmd == "repos":
        return emit({"ok": True, "base_dir": base, "repos": find_git_repos(base)})
 
    targets = cli_targets(base, args.repo)
    if not targets:
        where = f"`{args.repo}`" if args.repo else "the current folder"
        return emit({"ok": False, "results": [res(
            "-", "error",
            detail=f"{where} is not a single git repo. Pass --repo <name|all>. Known repos: {find_git_repos(base)}",
        )]})
 
    if args.cmd in SINGLE_REPO_ONLY and len(targets) != 1:
        return emit({"ok": False, "results": [res(
            "-", "error", detail=f"`{args.cmd}` works on one repo at a time — pass --repo <name>",
        )]})
 
    c = args.cmd
    dispatch: dict[str, Callable[[str, str], dict]] = {
        "branch": op_branch,
        "status": op_status,
        "pull": op_pull,
        "conflicts": op_conflicts,
        "continue": op_continue,
        "abort": op_abort,
    }
    if c in dispatch:
        fn = dispatch[c]
    elif c == "checkout":
        fn = lambda n, p: op_checkout(n, p, args.branch, sync=False)
    elif c == "sync":
        fn = lambda n, p: op_checkout(n, p, args.branch, sync=True)
    elif c == "merge":
        fn = lambda n, p: op_merge(n, p, args.branch)
    elif c == "new-branch":
        fn = lambda n, p: op_new_branch(n, p, args.name, args.base_ref)
    elif c == "commit":
        fn = lambda n, p: op_commit(n, p, args.message, args.files)
    elif c == "push":
        fn = lambda n, p: op_push(n, p, args.branch, args.allow_protected)
    elif c == "pr":
        fn = lambda n, p: op_pr(n, p, args.title, args.body, args.base, args.head)
    elif c == "ship":
        fn = lambda n, p: op_ship(n, p, args.new_branch, args.title, args.body, args.base,
                                  require_changes=len(targets) > 1)
    elif c == "stash":
        fn = lambda n, p: op_stash(n, p, args.action, args.message)
    else:  # pragma: no cover
        return emit({"ok": False, "results": [res("-", "error", detail=f"unknown command {c}")]})
 
    results = [fn(n, p) for n, p in targets]
    return emit({"ok": all(r["ok"] for r in results), "results": results})
 
 
if __name__ == "__main__":
    sys.exit(main())