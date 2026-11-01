import discord
import os
import json
import asyncio
import subprocess
import re
import shlex
import sys
import time
from typing import Any
 
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hubgit  # shared git/GitHub logic (also used directly by the AI agents)
from hubgit import find_git_repos, resolve_target_repos
 

# ==========================================
# PASTE YOUR 4 NOTEPAD VALUES HERE
# ==========================================
BOT_TOKEN = "MTc"
ALLOWED_USER_ID = 8       # Your Discord User ID (number, no quotes)

PROJECT_MAP = {
    11283: "/home/my_website",  # Your #personal Channel ID (no quotes)
    1588: "/home/erp", 
}
 

# Default model per engine. Claude accepts aliases (sonnet / opus / haiku)
# or full model names (e.g. claude-opus-5-5).
DEFAULT_MODELS = {
    "claude": "claude-opus-5-5",
    "cursor": "grok-4.7-high-fast",
    "antigravity": "gemini-3.8-flash",
}
# ==========================================
 
# Shown when the live Claude model list can't be fetched (no API key, offline, etc.)
CLAUDE_FALLBACK_MODELS = [
    "opus", "sonnet", "haiku",
    "claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5",
]
CLAUDE_ALIASES = ["opus", "sonnet", "haiku"]
 
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200d\u2060\ufeff]")
MODEL_LIST_TTL = 300  # seconds; numbering stays stable while cached
_models_cache: dict[str, dict[str, Any]] = {}
 
 
def parse_cli_models(engine: str, text: str) -> list[tuple[str, str]]:
    """Parses `agent models` ("id - Label") and `agy models` ("id   Label") output."""
    models: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = ZERO_WIDTH_RE.sub("", ANSI_RE.sub("", raw)).strip()
        if engine == "cursor":
            m = re.match(r"^(\S+)\s+-\s+(.+)$", line)
        else:
            m = re.match(r"^(\S+)\s{2,}(.+)$", line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            models.append((m.group(1), m.group(2).strip()))
    return models
 
 
async def run_models_cmd(cmd: list[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return stdout.decode()
 
 
def _fetch_claude_models_blocking(api_key: str) -> list[str]:
    import urllib.request
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/models?limit=100",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.load(resp)
    return [m["id"] for m in payload.get("data", []) if m.get("id")]
 
 
async def get_models(engine: str) -> tuple[list[tuple[str, str]], str]:
    """Returns ([(id, label)], source). Empty list means the list couldn't be fetched.
    Cached for 5 minutes per engine."""
    cached = _models_cache.get(engine)
    if cached and time.time() - cached["ts"] < MODEL_LIST_TTL:
        return cached["models"], cached["source"]
 
    models: list[tuple[str, str]] = []
    source = "unavailable"
    try:
        if engine == "claude":
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if api_key:
                ids = await asyncio.to_thread(_fetch_claude_models_blocking, api_key)
                if ids:
                    models = [(m, "") for m in CLAUDE_ALIASES + sorted(ids)]
                    source = "live from API"
            if not models:
                models = [(m, "") for m in CLAUDE_FALLBACK_MODELS]
                source = "built-in list; set ANTHROPIC_API_KEY for a live list"
        elif engine == "cursor":
            models = parse_cli_models("cursor", await run_models_cmd(["agent", "models"]))
            source = "from `agent models`"
        else:
            models = parse_cli_models("antigravity", await run_models_cmd(["agy", "models"]))
            source = "from `agy models`"
    except Exception as e:
        print(f"⚠️ Could not fetch {engine} model list: {e}")
        if engine == "claude":
            models = [(m, "") for m in CLAUDE_FALLBACK_MODELS]
            source = "built-in list (API fetch failed)"
 
    if models:
        _models_cache[engine] = {"ts": time.time(), "models": models, "source": source}
    return models, source
 
 
def resolve_model(engine: str, user_input: str, models: list[tuple[str, str]]) -> str | None:
    """Accepts a list number or an exact id (case-insensitive). Claude also accepts the id
    without the 'claude-' prefix. Cursor also accepts overrides like id[effort=high,fast=false]."""
    ids = [m for m, _ in models]
    s = user_input.strip()
    if s.isdigit():
        i = int(s)
        return ids[i - 1] if 1 <= i <= len(ids) else None
    lowered = {m.lower(): m for m in ids}
    if s.lower() in lowered:
        return lowered[s.lower()]
    if engine == "claude" and f"claude-{s.lower()}" in lowered:
        return lowered[f"claude-{s.lower()}"]
    if engine == "cursor" and "[" in s and s.endswith("]"):
        base = s.split("[", 1)[0].lower()
        if base in lowered:
            return lowered[base] + s[s.index("["):]
    return None
 
 
EFFORT_LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
DEFAULT_CLAUDE_EFFORT = "high"
LEVEL_RE = re.compile(
    r"^(?P<prefix>.*?)-(?P<level>none|minimal|low|medium|high|xhigh|extra-high|max)"
    r"(?P<suffix>(?:-thinking)?(?:-fast)?)$"
)
 
 
def split_effort(model_id: str) -> tuple[str, str, str] | None:
    """'claude-opus-5-5-high-fast' -> ('claude-opus-5-5', 'high', '-fast'). None if no level in id."""
    m = LEVEL_RE.match(model_id)
    return (m["prefix"], m["level"], m["suffix"]) if m else None
 
 
def swap_effort(model_id: str, level: str, models: list[tuple[str, str]]) -> tuple[str | None, list[str]]:
    """Finds the same model family at another effort level.
    Returns (new_id or None, levels available for this family)."""
    parts = split_effort(model_id)
    if parts is None:
        return None, []
    prefix, _, suffix = parts
    ids = {m for m, _ in models}
    available: list[str] = []
    for mid in ids:
        p = split_effort(mid)
        if p and p[0] == prefix and p[2] == suffix:
            available.append(p[1])
    available.sort(key=lambda lv: EFFORT_LEVELS.index("xhigh" if lv == "extra-high" else lv))
    wanted = [level] + (["extra-high"] if level == "xhigh" else ["xhigh"] if level == "extra-high" else [])
    for lv in wanted:
        cand = f"{prefix}-{lv}{suffix}"
        if cand in ids:
            return cand, available
    return None, available
 
 
async def send_chunked(message: discord.Message, header: str, lines: list[str], limit: int = 1900) -> None:
    chunk = header
    for line in lines:
        if len(chunk) + len(line) + 1 > limit:
            await safe_reply(message, chunk)
            chunk = ""
        chunk += ("\n" if chunk else "") + line
    if chunk:
        await safe_reply(message, chunk)
 
 
SESSIONS_FILE = "/home/karan/scripts/sessions.json"
STATE_FILE = "/home/karan/scripts/channel_state.json"
 
SESSION_LOCKS: dict[str, asyncio.Lock] = {}
ACTIVE_PROCESSES: dict[str, asyncio.subprocess.Process] = {}
FILE_LOCK = asyncio.Lock()
 
 
def load_json(path: str) -> dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}
 
 
def save_json(path: str, data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
 
 
async def safe_reply(message: discord.Message, text: str) -> discord.Message:
    """Replies directly; falls back to channel.send if message is a system/starter message."""
    try:
        return await message.reply(text)
    except discord.HTTPException as e:
        if e.code == 50035:
            return await message.channel.send(text)
        raise e
 
 
HUBGIT_PATH = os.path.abspath(hubgit.__file__)
GIT_NOTE = (
    "[Git Rules — these apply ONLY when I ask you to do something with git/GitHub "
    "(branch, pull, checkout, stash, commit, push, PR, merge, resolve conflicts, ...).\n"
    f"1. FIRST check whether the helper script can do it: `python3 {HUBGIT_PATH} <command>` "
    "(prints JSON: {\"ok\": bool, \"results\": [...]}). Commands: repos | branch | status | pull | checkout <b> | sync <b> | "
    "new-branch <name> [--from ref] | commit -m \"msg\" [--files a b] | push | pr --title T --body B [--base B] | "
    "ship <new_branch> --title T --body B [--base B] | merge <branch> | stash push|pop|list | conflicts | continue | abort. "
    "Add `--repo <name|all>` when you are not inside a single repo. If the script can do it, use it and do not run raw git for that step.\n"
    "2. If the script cannot do it, or it fails and its own commands can't fix it, STOP. Do NOT run raw git commands yet. "
    "Tell me what the script couldn't do, the exact git commands you would run instead, and why — then wait for my reply.\n"
    "3. Only if I explicitly say yes, run exactly the commands I approved with raw git. "
    "That approval covers only those commands, not anything later.\n"
    "Exception: resolving merge/rebase conflict markers by editing the files needs no approval; finish with the script's `continue` (or `abort`).\n"
    "Always: never add Co-authored-by or 'Generated with' lines to commits or PRs, never force-push, "
    "and never push straight to main/master unless I explicitly say so.]"
)
 
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
 
 
@client.event
async def on_ready() -> None:
    print(f"✅ Online as {client.user} | Multi-Repo Parallel Hub Ready")
 
 
@client.event
async def on_message(message: discord.Message) -> None:
    if message.author == client.user or message.author.id != ALLOWED_USER_ID:
        return
 
    parent_id = getattr(message.channel, "parent_id", None)
    root_channel_id = parent_id if isinstance(parent_id, int) and parent_id in PROJECT_MAP else message.channel.id
 
    if root_channel_id not in PROJECT_MAP:
        return
 
    base_dir = PROJECT_MAP[root_channel_id]
    content = message.content.strip()
    ch_key = str(message.channel.id)
 
    state = load_json(STATE_FILE)
    ch_state: dict[str, str] = state.get(ch_key, {
        "engine": "antigravity",
        "cursor_model": DEFAULT_MODELS["cursor"],
        "antigravity_model": DEFAULT_MODELS["antigravity"],
        "claude_model": DEFAULT_MODELS["claude"],
        "claude_effort": DEFAULT_CLAUDE_EFFORT,
        "thinking_level": "high",
        "active_repo": "root"
    })
 
    def get_model(eng: str) -> str:
        """Current model for an engine, falling back to the default
        (also covers channels saved before claude_model existed)."""
        return ch_state.get(f"{eng}_model") or DEFAULT_MODELS[eng]
 
    # 1. LIST REPOS
    if content == "!repos":
        repos = await asyncio.to_thread(find_git_repos, base_dir)
        lines = ["• `@root` *(All repos / ecosystem root)*"] + [f"• `@{r}`" for r in repos]
        await safe_reply(
            message,
            f"📁 **Git Repositories in `{base_dir}`:**\n" + "\n".join(lines) +
            f"\n\n📌 **Currently sticky on:** `@{ch_state['active_repo']}` (`{ch_state['engine'].upper()}`)"
        )
        return
 
    # 2. SWITCH ENGINE (!use claude | cursor | antigravity)
    if content == "!use" or content.startswith("!use "):
        parts = content.split()
        if len(parts) < 2 or parts[1].lower() not in ["claude", "cursor", "antigravity"]:
            await safe_reply(message, "Usage: `!use claude`, `!use cursor`, or `!use antigravity`")
            return
        ch_state["engine"] = parts[1].lower()
        state[ch_key] = ch_state
        save_json(STATE_FILE, state)
        await safe_reply(
            message,
            f"⚙️ Switched engine to **{ch_state['engine'].upper()}** (model: `{get_model(ch_state['engine'])}`)."
        )
        return
 
    # 3. SWITCH MODEL
    #    !model                  → current model (+ full list if short)
    #    !model search <terms>   → filter the list (e.g. !model search opus high)
    #    !model <number|id>      → select
    if content == "!model" or content.startswith("!model "):
        parts = content.split()
        engine = ch_state["engine"]
        current = get_model(engine)
        models, source = await get_models(engine)
 
        def fmt(i: int, mid: str, label: str) -> str:
            mark = "  ← current" if mid == current else ""
            return f"{i}. `{mid}`" + (f" — {label}" if label else "") + mark
 
        arg = parts[1] if len(parts) > 1 else None
 
        if arg is None:
            if not models:
                await safe_reply(
                    message,
                    f"Current `{engine.upper()}` model: `{current}`\n"
                    f"⚠️ Couldn't fetch the model list. You can still set one with `!model <id>` (unchecked)."
                )
            elif len(models) <= 30:
                header = f"🧠 **{engine.upper()}** — current: `{current}` ({source})\nPick with `!model <number|id>`:"
                await send_chunked(message, header, [fmt(i, m, l) for i, (m, l) in enumerate(models, 1)])
            else:
                await safe_reply(
                    message,
                    f"🧠 **{engine.upper()}** — current: `{current}`\n"
                    f"{len(models)} models available ({source}).\n"
                    f"Find one: `!model search <terms>` (e.g. `!model search opus 5-5 high`)\n"
                    f"Select: `!model <number|id>`"
                )
            return
 
        if arg.lower() in ("search", "list", "find"):
            if not models:
                await safe_reply(message, "⚠️ Couldn't fetch the model list for this engine.")
                return
            terms = [t.lower() for t in parts[2:]]
            matches = [
                (i, m, l) for i, (m, l) in enumerate(models, 1)
                if all(t in m.lower() or t in l.lower() for t in terms)
            ]
            if not matches:
                await safe_reply(message, f"❌ No `{engine.upper()}` models match `{' '.join(terms)}`.")
                return
            shown = matches[:40]
            header = f"🔎 **{len(matches)} match(es)** for `{' '.join(terms) or 'all'}` — select with `!model <number|id>`:"
            lines = [fmt(i, m, l) for i, m, l in shown]
            if len(matches) > len(shown):
                lines.append(f"…and {len(matches) - len(shown)} more. Add more terms to narrow it down.")
            await send_chunked(message, header, lines)
            return
 
        if models:
            chosen = resolve_model(engine, arg, models)
            if chosen is None:
                await safe_reply(
                    message,
                    f"❌ `{arg}` isn't a valid `{engine.upper()}` model. "
                    f"Use `!model search <terms>` to find one."
                )
                return
            note = ""
        else:
            chosen = arg
            note = "\n⚠️ Couldn't fetch the model list, so this wasn't validated."
 
        ch_state[f"{engine}_model"] = chosen
        state[ch_key] = ch_state
        save_json(STATE_FILE, state)
        await safe_reply(message, f"🧠 `{engine.upper()}` model set to **`{chosen}`**.{note}")
        return
 
    # 3b. SET REASONING EFFORT (!effort [level])
    #     cursor: level lives in the model id -> swap the id
    #     claude: --effort flag            antigravity: --effort flag (+ id suffix kept in sync)
    if content == "!effort" or content.startswith("!effort "):
        parts = content.split()
        engine = ch_state["engine"]
        model_id = get_model(engine)
        id_parts = split_effort(model_id)
        if engine == "claude":
            current_effort = ch_state.get("claude_effort") or DEFAULT_CLAUDE_EFFORT
        elif engine == "antigravity":
            current_effort = ch_state.get("thinking_level") or "high"
        else:
            current_effort = id_parts[1] if id_parts else "n/a (model has no effort variants)"
 
        if len(parts) < 2:
            await safe_reply(
                message,
                f"🎚️ **{engine.upper()}** effort: `{current_effort}` (model `{model_id}`)\n"
                f"Set with `!effort <{'|'.join(EFFORT_LEVELS[2:])}>`"
            )
            return
 
        level = parts[1].lower().replace("extra-high", "xhigh")
        if level not in EFFORT_LEVELS:
            await safe_reply(message, f"❌ Unknown level `{parts[1]}`. Use one of: {', '.join(f'`{l}`' for l in EFFORT_LEVELS)}.")
            return
 
        notes: list[str] = []
        if engine == "claude":
            ch_state["claude_effort"] = level
        else:
            models, _ = await get_models(engine)
            if engine == "antigravity":
                ch_state["thinking_level"] = level
            if models and id_parts:
                new_id, available = swap_effort(model_id, level, models)
                if new_id:
                    ch_state[f"{engine}_model"] = new_id
                    notes.append(f"model → `{new_id}`")
                elif engine == "cursor":
                    shown = ", ".join(f"`{l}`" for l in available) or "none"
                    await safe_reply(
                        message,
                        f"❌ `{model_id}` has no `{level}` variant. Levels for this model: {shown}."
                    )
                    return
            elif engine == "cursor":
                await safe_reply(
                    message,
                    f"❌ `{model_id}` has no effort variants. Pick another with `!model search <terms>`."
                )
                return
 
        state[ch_key] = ch_state
        save_json(STATE_FILE, state)
        extra = f" ({'; '.join(notes)})" if notes else ""
        await safe_reply(message, f"🎚️ `{engine.upper()}` effort set to **`{level}`**{extra}.")
        return
 
    # 4. REPO TAGGING (@repo_name)
    if content.startswith("@"):
        parts = content.split(" ", 1)
        candidate = parts[0][1:]
        candidate_dir = base_dir if candidate == "root" else os.path.join(base_dir, candidate)
        if os.path.isdir(candidate_dir):
            ch_state["active_repo"] = candidate
            state[ch_key] = ch_state
            save_json(STATE_FILE, state)
            if len(parts) == 1:
                await safe_reply(message, f"📌 Switched active repo to **`@{candidate}`**.")
                return
            content = parts[1].strip()
        else:
            await safe_reply(message, f"❌ Folder `{candidate}` not found. Type `!repos` to see valid paths.")
            return
 
    repo_name = ch_state["active_repo"]
    target_cwd = base_dir if repo_name == "root" else os.path.join(base_dir, repo_name)
    engine = ch_state["engine"]
    context_key = f"{engine}:{ch_key}:{repo_name}"
 
    # 5. STOP RUNNING PROCESS (!stop / !cancel)
    if content in ["!stop", "!cancel"]:
        proc = ACTIVE_PROCESSES.get(context_key)
        if proc is not None:
            try:
                proc.kill()
                await safe_reply(message, f"🛑 Terminated `{engine.upper()}` task for **`@{repo_name}`**.")
            except ProcessLookupError:
                await safe_reply(message, "⚠️ Task had already finished or exited.")
        else:
            await safe_reply(message, f"ℹ️ No active task currently running for **`@{repo_name}`**.")
        return
 
    # ==========================================
    # 6. SESSIONS: !sessions / !info / !reset [n|sessions|all]
    # ==========================================
    def channel_sessions(all_sessions: dict[str, Any]) -> list[tuple[str, str, str, str]]:
        """[(key, engine, repo, session_id)] saved for THIS channel, in a stable order
        so the numbers shown by !sessions match !reset <number>."""
        rows: list[tuple[str, str, str, str]] = []
        for key, sid in all_sessions.items():
            p = key.split(":", 2)
            if len(p) == 3 and p[1] == ch_key:
                rows.append((key, p[0], p[2], str(sid)))
        return sorted(rows, key=lambda r: (r[1], r[2]))
 
    # 6.1 LIST SAVED SESSIONS (!sessions)
    if content == "!sessions":
        rows = channel_sessions(load_json(SESSIONS_FILE))
        if not rows:
            await safe_reply(message, "🗂️ No saved sessions in this channel yet.")
            return
        lines = []
        for i, (key, eng, repo, sid) in enumerate(rows, 1):
            tags = ""
            if key == context_key:
                tags += "  ← active"
            if key in ACTIVE_PROCESSES:
                tags += "  ⏳ running"
            lines.append(f"{i}. `{eng.upper()}` · `@{repo}` · `{sid[:8]}…`{tags}")
        lines += [
            "",
            "Remove one: `!reset <number>` · all in this channel: `!reset sessions` · everything incl. settings: `!reset all`",
        ]
        await send_chunked(message, "🗂️ **Saved sessions in this channel:**", lines)
        return
 
    # 6.2 CHANNEL INFO (!info)
    if content == "!info":
        sessions = load_json(SESSIONS_FILE)
        sid = sessions.get(context_key)
        if engine == "claude":
            effort_txt = f" · effort `{ch_state.get('claude_effort') or DEFAULT_CLAUDE_EFFORT}`"
        elif engine == "antigravity":
            effort_txt = f" · effort `{ch_state.get('thinking_level') or 'high'}`"
        else:
            id_parts = split_effort(get_model(engine))
            effort_txt = f" · effort `{id_parts[1]}` (from model id)" if id_parts else ""
        lines = [
            "ℹ️ **Channel info**",
            f"• Engine: `{engine.upper()}`",
            f"• Model: `{get_model(engine)}`{effort_txt}",
            f"• Active repo: `@{repo_name}` (`{target_cwd}`)",
            "• Session (this engine + repo): "
            + (f"`{str(sid)[:8]}…`" if sid else "none — next message starts a fresh conversation"),
            "• Task: " + ("⏳ running (`!stop` to kill)" if context_key in ACTIVE_PROCESSES else "idle"),
            f"• Saved sessions in this channel: {len(channel_sessions(sessions))}",
            f"• Models: claude `{get_model('claude')}` · cursor `{get_model('cursor')}` · antigravity `{get_model('antigravity')}`",
        ]
        await safe_reply(message, "\n".join(lines))
        return
 
    # 6.3 RESET / REMOVE SESSIONS
    #     !reset            → this engine + repo
    #     !reset <number>   → one session from the !sessions list
    #     !reset sessions   → every saved session in this channel (settings kept)
    #     !reset all        → every session in this channel AND channel settings back to defaults
    if content == "!reset" or content.startswith("!reset "):
        arg = content[len("!reset"):].strip().lower()
        async with FILE_LOCK:
            sessions = load_json(SESSIONS_FILE)
            rows = channel_sessions(sessions)
 
            if arg == "":
                keys = [context_key]
                done_msg = f"♻️ Cleared the `{engine.upper()}` session for **`@{repo_name}`** — next message starts fresh (settings kept)."
                none_msg = f"ℹ️ No saved `{engine.upper()}` session for **`@{repo_name}`** — it's already fresh."
            elif arg in ("sessions", "all"):
                keys = [r[0] for r in rows]
                done_msg = (
                    f"♻️ Cleared {len(keys)} session(s) in this channel and restored channel defaults "
                    f"(engine, models, effort, active repo)."
                    if arg == "all" else
                    f"♻️ Cleared {len(keys)} session(s) in this channel (settings kept)."
                )
                none_msg = "ℹ️ No saved sessions in this channel."
            elif arg.isdigit():
                i = int(arg)
                if not 1 <= i <= len(rows):
                    await safe_reply(message, f"❌ No session #{i}. Run `!sessions` to see the list.")
                    return
                keys = [rows[i - 1][0]]
                done_msg = f"♻️ Removed session #{i} (`{rows[i - 1][1].upper()}` · `@{rows[i - 1][2]}`)."
                none_msg = done_msg
            else:
                await safe_reply(message, "Usage: `!reset` · `!reset <number>` · `!reset sessions` · `!reset all`")
                return
 
            running = [k for k in keys if k in ACTIVE_PROCESSES]
            if running:
                await safe_reply(
                    message,
                    f"⚠️ {len(running)} of these sessions has a task running. Send `!stop` first, then reset."
                )
                return
 
            removed = [k for k in keys if sessions.pop(k, None) is not None]
            if removed:
                save_json(SESSIONS_FILE, sessions)
 
            if arg == "all":
                state = load_json(STATE_FILE)
                state.pop(ch_key, None)
                save_json(STATE_FILE, state)
                await safe_reply(message, done_msg)
                return
 
        await safe_reply(message, done_msg if removed else none_msg)
        return
 
    # ==========================================
    # 7. HELP MENUS
    # ==========================================
 
    # 7.1a GENERAL HELP (!help / !commands) — everything except Git/GitHub
    if content in ["!help", "!commands"]:
        lines = [
            "",
            "**🤖 AI**",
            "• Any normal message → sent to the active engine in the active repo",
            "• `!use <claude|cursor|antigravity>` — switch engine",
            "• `!model` — current model (+ list if short)",
            "• `!model search <terms>` — filter the model list (e.g. `!model search opus high`)",
            "• `!model <number|id>` — select a model for the current engine",
            "• `!effort [low|medium|high|xhigh|max]` — show/set reasoning effort for the current engine",
            "• `!stop` / `!cancel` — kill the running task for this engine + repo",
            "",
            "**🗂️ Sessions & settings**",
            "• `!info` — engine, model, effort, repo, session id, running/idle",
            "• `!sessions` — list saved sessions in this channel (numbered)",
            "• `!reset` — clear the session for the current engine + repo",
            "• `!reset <number>` — remove one session from the `!sessions` list",
            "• `!reset sessions` — remove ALL saved sessions in this channel (settings kept)",
            "• `!reset all` — remove all sessions AND restore channel defaults",
            "",
            "**📁 Repos**",
            "• `!repos` — list repos and show the active one",
            "• `@<repo>` — make a repo active (sticky)",
            "• `@<repo> <message>` — switch repo and send the message in one go",
            "• `@root` — work on the whole folder",
            "",
            "**❓ Help**",
            "• `!help` / `!commands` — this list",
            "• `!githelp` — all Git & GitHub commands",
        ]
        await send_chunked(
            message,
            f"📖 **Commands** — `{engine.upper()}` · `{get_model(engine)}` · `@{repo_name}`",
            lines,
        )
        return
 
    # 7.1b GIT & GITHUB HELP (!githelp / !ghhelp)
    if content in ["!githelp", "!ghhelp"]:
        lines = [
            "*Tip: on `@root`, pass `<repo>` or `all` as the first argument. `[repo|all]` is optional on a specific repo.*",
            "",
            "**`!branch [repo|all]`**",
            "• Shows which branch the repo (or all repos) is on.",
            "",
            "**`!status [repo|all]`**",
            "• Shows modified, staged and untracked files plus diff stats, without committing.",
            "",
            "**`!pull [repo|all]`**",
            "• Pulls the current branch. Returns `done`, `conflicts`, or `detached HEAD`.",
            "",
            "**`!sync [repo|all] <branch>`**",
            "• Stashes local changes → switches to `<branch>` → pulls → **unstashes** your changes.",
            "• Returns `done`, `conflicts`, or `not exist`.",
            "",
            "**`!checkout [repo|all] <branch>`**",
            "• Stashes local changes → switches to `<branch>` → pulls *(does NOT unstash)*.",
            "• Returns `done`, `conflicts`, or `not exist`.",
            "",
            "**`!ship [repo|all] <new_branch> \"<pr_title>\" \"<description>\" [base_branch]`**",
            "• Creates/switches to `<new_branch>`, stages and commits everything with `<pr_title>`, pushes, opens a PR.",
            "• If `[base_branch]` is omitted, the PR targets the default branch.",
            "",
            "**🤖 Via the agent:** just ask in plain language (\"create branch x, commit, push and open a PR\"). "
            "Agents try `hubgit.py` first (same logic as the commands above). If it can't do the job, they tell you "
            "which raw git commands they want to run and wait for your yes.",
            "",
            "**❓ Other help:** `!help` — all non-Git commands",
        ]
        await send_chunked(message, f"🐙 **Git & GitHub commands** — active repo `@{repo_name}`", lines)
        return
 
    # 7.2 CHECK CURRENT BRANCH (!branch [repo|all])
    if content == "!branch" or content.startswith("!branch "):
        parts = content.split()
        repo_arg = parts[1] if len(parts) > 1 else None
        targets = await asyncio.to_thread(resolve_target_repos, base_dir, repo_name, repo_arg)
        if not targets:
            await safe_reply(message, f"❌ Repo `{repo_arg}` not found. Run `!repos` to see valid names.")
            return
 
        results = await asyncio.to_thread(hubgit.map_targets, targets, hubgit.op_branch)
        lines = [f"• **`@{r['repo']}`**: `{r.get('branch') or 'detached/unknown'}`" for r in results]
        await safe_reply(message, "🌿 **Current Branch Status:**\n" + "\n".join(lines))
        return
 
    # 7.3 CHECK UNCOMMITTED CHANGES (!status [repo|all])
    if content == "!status" or content.startswith("!status "):
        parts = content.split()
        repo_arg = parts[1] if len(parts) > 1 else None
        targets = await asyncio.to_thread(resolve_target_repos, base_dir, repo_name, repo_arg)
        if not targets:
            await safe_reply(message, f"❌ Repo `{repo_arg}` not found. Run `!repos` to see valid names.")
            return
 
        results = await asyncio.to_thread(hubgit.map_targets, targets, hubgit.op_status)
        reports = []
        for r in results:
            branch_label = r.get("branch") or "detached"
            if r["clean"]:
                if len(targets) == 1:
                    reports.append(f"✅ **`@{r['repo']}`** (`{branch_label}`) — Clean (no uncommitted changes).")
            else:
                block = f"📝 **`@{r['repo']}`** (`{branch_label}`):\n```\n{r['status_short']}"
                if r["diff_stat"]:
                    block += f"\n---\n{r['diff_stat']}"
                block += "\n```"
                reports.append(block)
 
        if not reports:
            await safe_reply(message, "✅ **All repositories are clean** (no uncommitted changes).")
        else:
            full_msg = "\n".join(reports)
            for chunk in [full_msg[i:i+1900] for i in range(0, len(full_msg), 1900)]:
                await safe_reply(message, chunk)
        return
 
    # 7.4 PULL ON SAME BRANCH (!pull [repo|all])
    if content == "!pull" or content.startswith("!pull "):
        parts = content.split()
        repo_arg = parts[1] if len(parts) > 1 else None
        targets = await asyncio.to_thread(resolve_target_repos, base_dir, repo_name, repo_arg)
        if not targets:
            await safe_reply(message, f"❌ Repo `{repo_arg}` not found. Run `!repos` to see valid names.")
            return
 
        results = await asyncio.to_thread(hubgit.map_targets, targets, hubgit.op_pull)
        if len(results) == 1:
            await safe_reply(message, hubgit.status_text(results[0]))
        else:
            await safe_reply(message, "\n".join(f"**`@{r['repo']}`**: {hubgit.status_text(r)}" for r in results))
        return
 
    # 7.5 (!sync [repo|all] <branch> AND !checkout [repo|all] <branch>)
    if content.startswith("!sync ") or content.startswith("!checkout "):
        is_sync = content.startswith("!sync ")
        parts = content.split()
        if len(parts) < 2:
            cmd_name = "!sync" if is_sync else "!checkout"
            await safe_reply(message, f"Usage: `{cmd_name} [repo|all] <branch>`")
            return
 
        if len(parts) >= 3:
            repo_arg, branch = parts[1], parts[2]
        elif repo_name == "root":
            cmd_name = "!sync" if is_sync else "!checkout"
            await safe_reply(message, f"⚠️ You are on `@root`. Specify a repo or `all`: `{cmd_name} <repo|all> <branch>`")
            return
        else:
            repo_arg, branch = None, parts[1]
 
        targets = await asyncio.to_thread(resolve_target_repos, base_dir, repo_name, repo_arg)
        if not targets:
            await safe_reply(message, f"❌ Repo `{repo_arg}` not found. Run `!repos` to see valid names.")
            return
 
        results = await asyncio.to_thread(hubgit.map_targets, targets, hubgit.op_checkout, branch, sync=is_sync)
        if len(results) == 1:
            await safe_reply(message, hubgit.status_text(results[0]))
        else:
            await safe_reply(message, "\n".join(f"**`@{r['repo']}`**: {hubgit.status_text(r)}" for r in results))
        return
 
    # 7.6 CREATE BRANCH, COMMIT, PUSH & CREATE PR (!ship)
    if content.startswith("!ship"):
        try:
            args = shlex.split(content)[1:]
        except ValueError as e:
            await safe_reply(message, f"❌ Quote parsing error: `{e}`\nUsage: `!ship [repo|all] <new_branch> \"<title>\" \"<description>\" [base_branch]`")
            return
 
        if len(args) < 3:
            await safe_reply(message, 'Usage: `!ship [repo|all] <new_branch> "<pr_title>" "<description>" [base_branch]`')
            return
 
        potential_targets = await asyncio.to_thread(resolve_target_repos, base_dir, repo_name, args[0])
        if potential_targets is not None and (args[0] in ["all", "root"] or len(args) >= 4):
            targets: list[tuple[str, str]] | None = potential_targets
            rem_args = args[1:]
        elif repo_name == "root":
            await safe_reply(message, '⚠️ You are on `@root`. Please specify the repo (or `all`) first:\n`!ship <repo|all> <new_branch> "<pr_title>" "<description>" [base_branch]`')
            return
        else:
            targets = await asyncio.to_thread(resolve_target_repos, base_dir, repo_name, None)
            rem_args = args
 
        if not targets:
            await safe_reply(message, f"❌ Target repo `{repo_name}` is not a valid Git repository. Run `!repos` to check.")
            return
 
        if len(rem_args) < 3:
            await safe_reply(message, 'Usage: `!ship [repo|all] <new_branch> "<pr_title>" "<description>" [base_branch]`')
            return
 
        new_branch, pr_title, pr_desc = rem_args[0], rem_args[1], rem_args[2]
        base_branch = rem_args[3] if len(rem_args) >= 4 else None
 
        results = await asyncio.to_thread(
            hubgit.map_targets, targets, hubgit.op_ship, new_branch, pr_title, pr_desc,
            base=base_branch, require_changes=len(targets) > 1,
        )
        ship_reports: list[str] = []
        for r in results:
            if r["status"] == "skipped":  # clean repo in a multi-repo ship
                continue
            if r["status"] == "done":
                note = f" (left out sensitive files: {', '.join(r['skipped_sensitive'])})" if r.get("skipped_sensitive") else ""
                ship_reports.append(f"🚀 **`@{r['repo']}`**: PR Created → {r['pr_url']}{note}")
            else:
                ship_reports.append(f"❌ **`@{r['repo']}`**: {r.get('detail', r['status'])}")
 
        if not ship_reports:
            await safe_reply(message, "ℹ️ No repositories had uncommitted changes to ship.")
        else:
            await safe_reply(message, "\n".join(ship_reports))
        return
 
    # ==========================================
    # 8. PARALLEL AI EXECUTION
    # ==========================================
    if context_key not in SESSION_LOCKS:
        SESSION_LOCKS[context_key] = asyncio.Lock()
 
    async with SESSION_LOCKS[context_key]:
        async with message.channel.typing():
            if message.attachments:
                if not content:
                    content = "Analyze the attached image."
                for att in message.attachments:
                    img_path = f"/tmp/{message.id}_{att.filename}"
                    await att.save(img_path)
                    content += f"\n(Attached image saved at: {img_path})"
 
            if not content:
                return
 
            sessions = load_json(SESSIONS_FILE)
 
            # Auto-detect Tailscale IP
            def _tailscale_ip() -> str:
                try:
                    return subprocess.run(
                        ["tailscale", "ip", "-4"], capture_output=True, text=True
                    ).stdout.strip() or "localhost"
                except FileNotFoundError:
                    return "localhost"
 
            ts_ip = await asyncio.to_thread(_tailscale_ip)
 
            dev_server_rule = (
                f"\n\n[System Note: ONLY if asked to start/run/restart/stop dev servers: "
                f"1. Reserved ports: 8000-8010 for backends, 3000-3010 for Next.js/React frontends, and 5173-5183 for Vite frontends (check `pm2 list` or `ss -tulpn` first to pick free ports). "
                f"2. Bind all servers to 0.0.0.0 (`--host 0.0.0.0`). "
                f"3. Point frontend API env variables to `http://{ts_ip}:<backend_port>` and ensure backend CORS allows `http://{ts_ip}:<frontend_port>`. "
                f"4. ALWAYS launch and manage servers via PM2 (`pm2 start \"<cmd>\" --name <app_name>`) so the CLI subprocess exits cleanly without hanging. "
                f"5. Reply with the exact clickable mobile URLs: `http://{ts_ip}:<port>`.]"
            )
            full_prompt = GIT_NOTE + "\n\n" + content + dev_server_rule
 
            if engine == "claude":
                cmd = [
                    "claude", "--dangerously-skip-permissions",
                    "--model", get_model("claude"),
                    "--effort", ch_state.get("claude_effort") or DEFAULT_CLAUDE_EFFORT,
                    "--add-dir", base_dir,
                    "--output-format", "json",
                    "-p", full_prompt
                ]
            elif engine == "cursor":
                cmd = [
                    "agent", "--force", "--trust",
                    "--model", get_model("cursor"),
                    "--workspace", base_dir,
                    "--output-format", "json",
                    "-p", full_prompt
                ]
            else:  # antigravity
                cmd = [
                    "agy", "--dangerously-skip-permissions",
                    "--model", get_model("antigravity"),
                    "--effort", ch_state.get("thinking_level", "high"),
                    "--add-dir", base_dir,
                    "--output-format", "json",
                    "-p", full_prompt
                ]
 
            if context_key in sessions:
                resume_flag = "--conversation" if engine == "antigravity" else "--resume"
                cmd.extend([resume_flag, str(sessions[context_key])])
 
            print(f"🚀 [STARTED] Executing {engine.upper()} ({get_model(engine)}) for @{repo_name}...")
 
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=target_cwd,
                env={**os.environ, "HUBGIT_BASE_DIR": base_dir},
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            ACTIVE_PROCESSES[context_key] = proc
            try:
                stdout, stderr = await proc.communicate()
            finally:
                ACTIVE_PROCESSES.pop(context_key, None)
 
            # If terminated via !stop / !cancel, exit cleanly without outputting errors
            if proc.returncode in [-9, 137]:
                print(f"🛑 [ABORTED] {engine.upper()} process killed for @{repo_name}.")
                return
 
            raw_out = stdout.decode().strip()
            print(f"🏁 [FINISHED] {engine.upper()} returned {len(raw_out)} bytes (exit code: {proc.returncode}).")
 
            try:
                data = json.loads(raw_out)
                reply_text = str(data.get("result") or data.get("response") or raw_out)
                session_id = (
                    data.get("session_id")
                    or data.get("chatId")
                    or data.get("conversation_id")
                    or data.get("conversationId")
                    or data.get("id")
                )
                if session_id:
                    async with FILE_LOCK:
                        sessions = load_json(SESSIONS_FILE)
                        sessions[context_key] = str(session_id)
                        save_json(SESSIONS_FILE, sessions)
            except Exception:
                reply_text = raw_out or stderr.decode().strip() or "Completed with no output."
 
            reply_text = reply_text.strip() or stderr.decode().strip() or "Completed with no output."
            reply_text = reply_text.replace("```", "ʼʼʼ")  # don't break the Discord code block
 
            if engine == "antigravity":
                engine_label = f"ANTIGRAVITY ({get_model('antigravity')} - {ch_state.get('thinking_level', 'high')})"
            elif engine == "cursor":
                engine_label = f"CURSOR ({get_model('cursor')})"
            else:
                engine_label = f"CLAUDE ({get_model('claude')} - {ch_state.get('claude_effort') or DEFAULT_CLAUDE_EFFORT})"
 
            header = f"**[{engine_label} | @{repo_name}]**\n"
            for chunk in [reply_text[i:i+1850] for i in range(0, len(reply_text), 1850)]:
                await safe_reply(message, f"{header}```\n{chunk}\n```")
                header = ""
 
 
client.run(BOT_TOKEN)