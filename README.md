# Discord AI Coding Hub

Control your local AI coding agents (**Claude Code**, **Cursor Agent**, **Antigravity**) from Discord. Run Git & GitHub workflows across many repos, work on several projects in parallel, test your apps on your phone and download files from your PC, from anywhere, as long as your computer is on.

Each Discord channel is linked to a folder on your machine. Anything you type there is sent to the AI agent you picked, running **on your computer** inside that folder. Messages starting with `!` control the bot itself (engine, model, sessions, Git).

> [!CAUTION]
> **Read the [Security & Safety Warnings](#security--safety-warnings) before you start.** This bot runs AI agents with their permission prompts turned off. Whoever can message the bot can make your computer run commands.

---

## Table of Contents

1. [Why this project exists](#why-this-project-exists)
2. [How it works](#how-it-works)
3. [What is in the repo](#what-is-in-the-repo)
4. [Security & Safety Warnings](#security--safety-warnings)
5. [Setup guide](#setup-guide)
   - [Step 1: Prerequisites](#step-1-prerequisites)
   - [Step 2: Connect GitHub CLI](#step-2-connect-github-cli)
   - [Step 3: Set up Tailscale](#step-3-set-up-tailscale)
   - [Step 4: Create your Discord bot](#step-4-create-your-discord-bot)
   - [Step 5: Set up folders and get the code](#step-5-set-up-folders-and-get-the-code)
   - [Step 6: Configure the bot](#step-6-configure-the-bot)
   - [Step 7: Run and persist with PM2](#step-7-run-and-persist-with-pm2)
   - [Step 8: Set up FileBrowser](#step-8-set-up-filebrowser)
   - [Step 9: Create your channels and threads](#step-9-create-your-channels-and-threads)
6. [Working with threads: one repo, many repos, parallel agents](#working-with-threads-one-repo-many-repos-parallel-agents)
7. [Running and testing apps from your phone](#running-and-testing-apps-from-your-phone)
8. [Command cheat sheet](#command-cheat-sheet)
9. [How Git works (bot commands vs. agents)](#how-git-works-bot-commands-vs-agents)
10. [`hubgit.py` reference](#hubgitpy-reference)
11. [Troubleshooting](#troubleshooting)
12. [Known limitations](#known-limitations)
13. [Updating, stopping and uninstalling](#updating-stopping-and-uninstalling)
14. [Disclaimer](#disclaimer)

---

## Why this project exists

The goal: **one familiar tool (Discord) to manage everything**, instead of a different terminal, IDE, phone app and remote-desktop session for each task.

- **One interface for all your AI agents.** Claude Code, Cursor Agent and Antigravity are driven from the same chat. Switch engine, model and reasoning effort with a command, and pick a different one per thread.
- **Git and GitHub from chat.** Branch, pull, sync, commit, push and open a PR with a single command, on one repo or on all of them at once, without opening a terminal.
- **Many projects in parallel.** Every channel and thread is its own workspace with its own agent, model, repo and conversation. Work on several repos at the same time without them getting in each other's way.
- **No babysitting servers.** Agents are told to start dev servers through PM2 on reserved ports, so they never hang a task, never clash on ports, and keep running after the agent exits.
- **Work from anywhere.** The bot runs on your PC or laptop and only makes outbound connections to Discord. Leave the machine on, and you can send tasks from your phone or any other device. No port forwarding, no remote desktop.
- **Test on your phone, not at your desk.** With Tailscale, agents hand you a clickable `http://<tailscale-ip>:<port>` link to the app they just started, and it opens on your phone.
- **Reach your files when you need them.** FileBrowser (over Tailscale) lets you download reports, exports and build output from your PC to your phone, or upload files to it.
- **Automate the boring parts.** `hubgit.py` is a shared Git helper used by both the bot commands and the agents, so the same safe, repeatable logic runs no matter who triggers it.
- **Your name only on your contributions.** Commits and PRs made through `hubgit.py` and `!ship` have AI `Co-authored-by: Claude/Cursor/...` and "Generated with ..." lines stripped, so GitHub shows **you** as the only contributor, under your own Git identity.

---

## How it works

```
 Phone / laptop (Discord app)
          │  message
          ▼
   Discord servers  ◄──────────  outbound connection only (no open ports)
          │
          ▼
 ┌────────────────────────── Your PC / laptop (Linux or WSL2) ───────────────────────────┐
 │  dev_discord_hub.py  (kept alive by PM2)                                              │
 │    1. Ignore anyone except ALLOWED_USER_ID                                            │
 │    2. Find the channel (or the thread's parent channel) in PROJECT_MAP → project folder│
 │    3. Load this channel/thread's saved state: engine, model, effort, active repo       │
 │    4a. "!command"  → handled by the bot (settings, sessions, Git via hubgit.py)       │
 │    4b. normal text → build prompt and start the agent CLI inside the active repo      │
 │                      (claude / agent / agy), resuming the saved session              │
 │    5. Wait for the agent to finish → save its session id → post the reply in Discord  │
 │                                                                                       │
 │  hubgit.py           shared Git/GitHub logic (used by the bot AND by the agents)      │
 │  PM2                 runs the bot, the dev servers agents start, and FileBrowser     │
 │  Tailscale           private network so your phone can reach dev servers + files     │
 └───────────────────────────────────────────────────────────────────────────────────────┘
```

**What gets added to each prompt.** Before your message reaches the agent, the bot prepends:

1. **Git Rules**: use `hubgit.py` first for any Git work, ask for your approval before running raw Git, never force-push, never push to `main`/`master`, never add AI co-author lines.
2. **Dev-server rules** (applied only if you ask to start, stop or restart servers): reserved ports, bind to `0.0.0.0`, point frontend API URLs and CORS at your Tailscale IP, launch everything through PM2, reply with clickable phone URLs.

**Routing: where does a message go?**

| You type                 | What happens                                                                             |
| ------------------------ | ---------------------------------------------------------------------------------------- |
| `!something`           | The bot handles it itself (engine/model/sessions/Git). No agent is started.              |
| `@repo_name`           | Makes that repo the thread's active repo.                                                |
| `@repo_name <message>` | Switches repo, then sends the message to the agent.                                      |
| Anything else            | Sent to the agent, running in the active repo, using that channel/thread's engine + model. |

**Where state lives.** `channel_state.json` stores, per channel **and per thread**: engine, model per engine, effort and active repo. `sessions.json` stores the agent's conversation id per `engine : channel/thread : repo`, which is how a follow-up message continues the same conversation.

**Parallelism.** A task is locked per *engine + channel/thread + repo*. Different threads, different repos or different engines run at the same time. Messages for the same combination queue up.

---

## What is in the repo

```
~/scripts/
├── dev_discord_hub.py    # the Discord bot
├── hubgit.py             # shared Git/GitHub helper (used by the bot AND by the AI agents)
├── README.md             # this guide
├── sessions.json         # auto-created: saved agent session ids
└── channel_state.json    # auto-created: per-channel / per-thread engine, model, effort, active repo
```

- **`hubgit.py` must sit in the same folder as `dev_discord_hub.py`.** The bot imports it, and the agents are told to run it.
- `sessions.json` and `channel_state.json` are created automatically. Do not commit them (see the `.gitignore` in Step 5).
- The only Python package you need to install is `discord.py`. `hubgit.py` uses the standard library only.
- **Tailscale and FileBrowser are separate tools**, not part of this repo. [Step 3](#step-3-set-up-tailscale) and [Step 8](#step-8-set-up-filebrowser) set them up. FileBrowser creates a database file. Keep it outside this repo, and if it ever ends up here, **never commit `filebrowser.db`** (it holds user accounts and password hashes).

---

## Security & Safety Warnings

Please read all of this. The bot is powerful by design, and that is exactly why it is risky.

> [!WARNING]
> **The agents run with permission prompts disabled.** The bot starts them with `claude --dangerously-skip-permissions`, `agent --force --trust` and `agy --dangerously-skip-permissions`. An agent can read, edit and delete files and run shell commands as **your user account**, without asking. A bad prompt, a mistake or a prompt-injection hidden in a file or web page can cause real damage.

> [!WARNING]
> **Anyone who controls your Discord account or your bot token can run commands on your computer.** The bot only answers the single `ALLOWED_USER_ID`, but if your Discord account is compromised or your token leaks, that is remote code execution on your machine.
>
> - Turn on **2FA** for your Discord account.
> - Use a **private server** and **private channels** that only you can see. The bot posts agent output (code, file contents, errors) into the channel.
> - Consider running the bot on a **dedicated machine, VM or low-privilege user account**, not on a machine that holds secrets you cannot afford to lose.

> [!WARNING]
> **Never commit or share your bot token.** The setup below puts the token inside `dev_discord_hub.py`. If you fork this repo or push your own copy to GitHub, **do not push the file with your token in it**. If a token is ever exposed (pasted in a chat, committed, screenshotted), go to the Discord Developer Portal → your app → **Bot → Reset Token** immediately, then update your config.

> [!WARNING]
> **Proprietary / employer code.** Agents send your code and prompts to their providers (Anthropic, Cursor, Google, etc.). The bot itself runs locally, but connecting a work repository means that code leaves your machine through the agent. Check your employer's policy and each provider's terms and data-retention settings before linking proprietary repos.

> [!WARNING]
> **Don't link folders you can't afford to lose.** `--add-dir` gives an agent access to the folder, but it does not stop it from touching other paths your user can reach. Keep secrets, SSH keys, password files and unrelated projects outside the mapped folders, and keep backups / use Git so changes can be reverted.

> [!WARNING]
> **FileBrowser ([Step 8](#step-8-set-up-filebrowser)) exposes your files.** A file manager that can browse your home folder and Windows drives from your phone is convenient, and it is also a way for anyone who gets a login to read, change or delete those files. Read the warnings in Step 8 before setting it up.

> [!NOTE]
> **Usage and cost.** Every message starts a real agent run on your account. High or max reasoning effort on the largest models is slow and uses your plan's quota quickly. Start with `medium` for routine work. Check each provider's terms for your plan regarding automated or remote use.

### Git-specific warnings

- **`!ship` stages everything** (`git add -A`), commits, pushes and opens a PR. Review `!status` first. Files that look like secrets (`.env`, `.env.*` except `.env.example`, `*.pem`, `*.p12`, `*.pfx`, SSH private keys) are **left out automatically**, and the reply tells you which, but this is a safety net, not a replacement for a proper `.gitignore`.
- **The bot and `hubgit.py` never force-push**, and **refuse to push straight to `main` / `master`** unless `--allow-protected` is passed explicitly (agents are told never to, unless you say so).
- **A commit is refused while conflict markers (`<<<<<<<` / `>>>>>>>`) are still in the files**, so you never accidentally commit a broken merge.
- Commits are made under **your** Git identity (`git config user.name` / `user.email`). Make sure those are set.
- **AI "co-author" lines.** Commits and PRs created through `hubgit.py` / `!ship` never include `Co-authored-by: Claude/Cursor/...` or "Generated with ..." lines. If an agent runs **raw `git commit` itself** (only after your approval, see below), the tool may add such a line on its own. Check your agent's own settings for this (for Claude Code, look for its attribution / co-author setting for commits and PRs) and review commits before pushing.
- Nothing here installs Git hooks or changes your repository settings.

### Other things to know

- **One engine at a time per repo.** Two agents editing the same repo at once (for example the bot and your IDE, or two threads pointing at the same repo) can overwrite each other's work.
- **There is no timeout.** A task runs until the agent finishes. Results are posted only when it finishes (nothing is streamed). Use `!stop` to kill a task.
- **`!reset` only makes the bot forget a session id.** The agent's own transcript files stay on your disk (for Claude Code, under `~/.claude/projects/`).
- Image attachments are saved to `/tmp` and the path is given to the agent.
- **Your PC must stay on and awake** for the bot to answer. Disable sleep/hibernate on the machine that runs it.

---

## Setup guide

Do the steps in order. Each one builds on the previous.

### Step 1: Prerequisites

Install on a **Linux or WSL2** machine (native Windows is not supported):

- **Python 3.10+** and `python3-venv`
- **Node.js & PM2:** `npm install -g pm2`
- **Git & GitHub CLI:** `sudo apt install git gh`
- **At least one AI agent CLI**, installed and **logged in** (run it once by hand to make sure it works):
  - `claude` (Claude Code)
  - `agent` (Cursor Agent CLI)
  - `agy` (Antigravity CLI)
- **A Tailscale account** (free), installed in [Step 3](#step-3-set-up-tailscale).

Quick check:

```bash
python3 --version      # 3.10 or newer
git --version
gh --version
pm2 --version
claude --version       # and/or: agent --version, agy --version
```

### Step 2: Connect GitHub CLI

So the bot (and the agents) can pull, push and open Pull Requests without asking for a password:

```bash
gh auth login
gh auth setup-git
```

Verify with `gh auth status`. Also make sure your Git identity is set. This is the name that will appear on every commit and PR the hub makes:

```bash
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"
```

### Step 3: Set up Tailscale

[Tailscale](https://tailscale.com) is a private network between your own devices. It is what lets your phone reach **dev servers** the agents start (for testing apps) and **FileBrowser** (for your files), with nothing exposed to the public internet. The bot detects your Tailscale IP automatically (`tailscale ip -4`) and gives it to agents so the links they send you open on your phone.

**On the PC / WSL machine (where the bot runs):**

1. Install Tailscale and start it:

   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```

   Open the login URL it prints and sign in.

   > **WSL users:** Tailscale's daemon needs systemd. If `sudo tailscale up` says it can't reach `tailscaled`, enable systemd by adding this to `/etc/wsl.conf`, then run `wsl --shutdown` from Windows and reopen WSL:
   >
   > ```ini
   > [boot]
   > systemd=true
   > ```
   >
   > Then run `sudo systemctl enable --now tailscaled` and `sudo tailscale up` again.

2. Check it works and note your IP:

   ```bash
   tailscale status
   tailscale ip -4        # e.g. 100.x.y.z, used below as <your-tailscale-ip>
   ```

**On your phone (and any other device you will use):**

1. Install the **Tailscale** app from your app store.
2. Sign in with the **same account** as the PC.
3. Keep the VPN toggle **on** whenever you want to open dev-server links or FileBrowser.

**Security:** keep everything tailnet-only. Never use router port-forwarding or Tailscale Funnel for this project, and use Tailscale ACLs so only the devices you trust can reach the machine. Anyone you *share* a device with can reach it too.

### Step 4: Create your Discord bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. Open the **Bot** tab:
   - Click **Reset Token**, then copy the token to a notepad. **Treat it like a password.**
   - Scroll to **Privileged Gateway Intents** and turn **ON "Message Content Intent"**. Save changes. (Without this the bot cannot read your messages.)
3. Open **OAuth2 → URL Generator**:
   - Scopes: tick **bot**.
   - Bot Permissions: **View Channels**, **Send Messages**, **Read Message History**, **Send Messages in Threads**, **Attach Files**.
   - Copy the generated URL, open it in your browser and invite the bot to **your private server**.
4. Get your IDs:
   - Discord **User Settings → Advanced → Developer Mode: ON**.
   - Right-click your own profile picture → **Copy User ID**.
   - Right-click each channel you want to link (e.g. `#work`, `#personal`) → **Copy Channel ID**.

Keep these in a notepad: **bot token**, **your user ID**, and **one channel ID per project folder**.

### Step 5: Set up folders and get the code

1. Create the scripts folder and your project folders:

   ```bash
   mkdir -p ~/scripts ~/work ~/my_website
   ```
2. Clone the repository into `~/scripts`:

   ```bash
   cd ~/scripts
   git clone <YOUR_GITHUB_REPO_URL> .
   ```
3. Create a virtual environment and install `discord.py`:

   ```bash
   python3 -m venv ~/scripts/bot_venv
   source ~/scripts/bot_venv/bin/activate
   pip install --upgrade pip discord.py
   deactivate
   ```
4. Add a `.gitignore` in `~/scripts` so runtime files never get committed:

   ```gitignore
   bot_venv/
   sessions.json
   channel_state.json
   filebrowser.db
   __pycache__/
   ```

### Step 6: Configure the bot

Open `~/scripts/dev_discord_hub.py` and edit the **configuration block at the top**:

| Setting             | What to put                                                                   |
| ------------------- | ----------------------------------------------------------------------------- |
| `BOT_TOKEN`       | Your Discord bot token (in quotes). **Never commit this.**                    |
| `ALLOWED_USER_ID` | Your Discord user ID (number, no quotes). Only this user can control the bot. |
| `PROJECT_MAP`     | One line per channel: `CHANNEL_ID: "/absolute/path/to/folder"`                |
| `DEFAULT_MODELS`  | Default model per engine. Change with `!model` later.                         |

Example:

```python
BOT_TOKEN = "your-token-here"
ALLOWED_USER_ID = 123456789012345678

PROJECT_MAP = {
    111111111111111111: "/home/you/work",        # #work channel
    222222222222222222: "/home/you/my_website",  # #personal channel
}
```

> [!IMPORTANT]
> Further down, `SESSIONS_FILE` and `STATE_FILE` are set to absolute paths (they default to `/home/karan/scripts/...`). **Change them to your own home folder**, for example `/home/you/scripts/sessions.json` and `/home/you/scripts/channel_state.json`, or the bot will fail when it tries to save state.

How channels, folders and repos relate:

- A mapped folder can contain **one repo or many repos** (up to 3 levels deep). `!repos` lists them.
- **Threads** created inside a mapped channel use the same folder but keep their **own** engine, model, effort, active repo and session. See [Working with threads](#working-with-threads-one-repo-many-repos-parallel-agents).
- Messages in channels that are **not** in `PROJECT_MAP` are ignored.
- New channels **and new threads** start on the **Antigravity** engine with `@root` as the active repo. Switch with `!use claude` or `!use cursor`.

**Live Claude model list.** `!model` for the Claude engine shows a built-in list by default. For a live list of the models your key can use, give the bot an API key in its environment:

```bash
ANTHROPIC_API_KEY="sk-ant-..." pm2 restart discord-hub --update-env
```

This key is **only** used to list model names. Keep it secret like any key.

### Step 7: Run and persist with PM2

PM2 keeps the bot running in the background and restarts it if it crashes. It also manages the dev servers agents start and FileBrowser.

1. Start the bot with the virtual environment's Python:

   ```bash
   pm2 start ~/scripts/bot_venv/bin/python --name discord-hub -- ~/scripts/dev_discord_hub.py
   ```
2. Save the process list:

   ```bash
   pm2 save
   ```
3. Auto-start on boot (run the command PM2 prints):

   ```bash
   pm2 startup
   ```

> **WSL users:** if WSL fully shuts down when you close Windows, run `pm2 resurrect` after opening your terminal to bring your saved processes back.

> **Heads up:** PM2 remembers the `PATH` it was started with. If `claude`, `agent`, `agy`, `gh`, `tailscale` or `node` were installed through a tool such as `nvm` and are not found after a reboot, restart the bot from a normal terminal where they work: `pm2 restart discord-hub --update-env`.

**Useful PM2 commands**

| Command                                               | What it does                     |
| ----------------------------------------------------- | -------------------------------- |
| `pm2 status`                                        | Is the bot running?              |
| `pm2 logs discord-hub --lines 35 --nostream`        | Recent logs                      |
| `pm2 restart discord-hub`                           | Restart after editing the script |
| `pm2 flush discord-hub`                             | Clear old log files              |
| `pm2 stop discord-hub` / `pm2 delete discord-hub`   | Stop / remove                    |

In the logs, `🚀 [STARTED]` means a task began and `🏁 [FINISHED]` means it ended. A `[STARTED]` with no `[FINISHED]` means it is still running.

### Step 8: Set up FileBrowser

The agents create files on your PC: reports, exports, build output, screenshots. [FileBrowser](https://github.com/filebrowser/filebrowser) is a small open-source web file manager. Run it next to the bot and, from anywhere, you can log in on your phone (over Tailscale from [Step 3](#step-3-set-up-tailscale)) and **download** (or upload) files from your computer.

This is separate from the bot, but it is part of the setup: it is how you get files out of the PC when you are away from it.

```
Phone (Tailscale app)  ──►  http://<your-tailscale-ip>:8090  ──►  FileBrowser (in WSL, kept alive by PM2)
                                                                       │
                                                                       ▼
                                                 a "master" folder full of symlinks to the folders you share
                                                 (for example your project folders and your Windows drives under /mnt/c)
```

> [!CAUTION]
> **FileBrowser gives whoever logs in the same access to your files that the WSL user has.**
>
> - If the master folder links to your **whole WSL home**, a login can reach `~/.ssh`, `~/.config/gh` (your GitHub token), `~/.claude`, `.env` files and `dev_discord_hub.py` (your **Discord bot token**).
> - If it links to **`/mnt/c`**, a login can reach your whole Windows drive.
> - With the default permissions a login can also **edit and delete** those files.
>
> The setup below works with broad links like these, but **prefer linking only the folders you really need**, and give your phone a restricted user (see "Lock it down").

**1. Install FileBrowser**

Install it inside WSL with the method in the [project's README](https://github.com/filebrowser/filebrowser) (it provides an install script and prebuilt binaries). Check it works:

```bash
filebrowser version
```

**2. Create the master folder**

FileBrowser serves one root folder. Fill it with **symlinks** to the places you want to reach:

```bash
mkdir -p ~/filebrowser-root

# Recommended: only the folders you need
ln -s ~/work                         ~/filebrowser-root/work
ln -s /mnt/c/Users/<you>/Documents   ~/filebrowser-root/windows-documents

# The broad version (convenient, but see the warning above)
# ln -s ~       ~/filebrowser-root/wsl-home
# ln -s /mnt/c  ~/filebrowser-root/c-drive
```

**3. Run it with PM2**

Keep the database **outside this repo** (a dedicated `~/filebrowser/` folder) and bind to your **Tailscale IP** instead of `0.0.0.0`, so it is reachable only through Tailscale:

```bash
mkdir -p ~/filebrowser
TS_IP=$(tailscale ip -4)

pm2 start "$(which filebrowser)" --name filebrowser --interpreter none -- \
  -a "$TS_IP" -p 8090 -r ~/filebrowser-root -d ~/filebrowser/filebrowser.db

pm2 save
```

Flag names can differ between versions. If it doesn't start, check `filebrowser --help` and `pm2 logs filebrowser`.

Port **8090** doesn't overlap the ports the bot reserves for agents' dev servers (8000–8010, 3000–3010, 5173–5183).

**4. First login and phone setup**

1. On your PC (or any device on your tailnet) open `http://<your-tailscale-ip>:8090`. Find the IP with `tailscale ip -4`.
2. The first run creates an admin user. **Check `pm2 logs filebrowser` for a generated password** (older versions used `admin` / `admin`). **Change the password immediately** under Settings.
3. On your phone: make sure the Tailscale app is connected, then open the same URL in the browser. Add it to your home screen for one-tap access.

**5. Lock it down**

- Use a **strong, unique password** for the admin account, and use that account only when you need to change settings.
- Create a **second, non-admin user for your phone**: Settings → User Management → New User. Give it a **scope** limited to the folders it needs, and untick what it doesn't need (create, rename, edit, delete, share, **execute commands**). A "download only" user can't damage anything if the phone is lost.
- **Never expose port 8090 to the public internet**: no router port-forwarding, no Tailscale Funnel. Keep it tailnet-only.
- Use Tailscale's access controls (ACLs) so only your phone and PC can reach the machine, and remember that anything you **share** a device with can reach it too.
- If your phone is lost or stolen: remove it from the Tailscale admin console and change your FileBrowser passwords.
- `filebrowser.db` stores user accounts and password hashes. **Don't commit it** to Git.
- Files seen through `/mnt/c` can be slow, and Windows/WSL permission quirks are normal.

### Step 9: Create your channels and threads

1. In your private Discord server, create one text channel per project folder (for example `#work`, `#personal`) and make sure only you (and the bot) can see them.
2. Put each channel's ID in `PROJECT_MAP` ([Step 6](#step-6-configure-the-bot)) and restart the bot: `pm2 restart discord-hub`.
3. In a channel, send `!help` (the bot should answer) and `!repos` (it should list the repos in that folder).
4. Create threads inside the channel for each task you want to run in parallel. The next section explains how.

---

## Working with threads: one repo, many repos, parallel agents

A **channel** is a project folder. A **thread** is a separate workspace inside that folder, with its own:

- **engine** (Claude / Cursor / Antigravity)
- **model** and **reasoning effort**
- **active repo** (`@repo` or `@root`)
- **conversation** (session), kept separately per engine and repo

Threads only need the **parent channel** to be in `PROJECT_MAP`. Nothing else to configure.

### How to create a thread

- **Desktop:** hover a message in the channel → **Create Thread** (or use the **Threads** icon in the channel header → **Create**).
- **Mobile:** long-press a message → **Create Thread**.

Give it a name that says what it is for, for example `api-claude`, `web-cursor` or `all-repos`. The bot answers inside the thread. The permission **Send Messages in Threads** (Step 4) is required.

### Set up a thread

A new thread starts on **Antigravity**, active repo **`@root`**. It does **not** inherit the channel's settings. So the first messages in a new thread are usually:

```
!use claude
!model search opus
!model 3
!effort medium
@api
```

Check it with `!info`.

### Use case 1: one repo, one tool per thread

Create a thread per repo and pin the repo and engine you want:

| Thread          | Setup                           | Then you type                                      |
| --------------- | ------------------------------- | -------------------------------------------------- |
| `api-claude`    | `!use claude` → `@api`          | "Add pagination to the users endpoint"             |
| `web-cursor`    | `!use cursor` → `@web`          | "Fix the broken mobile menu"                       |
| `docs-agy`      | `!use antigravity` → `@docs`    | "Update the install guide"                         |

All three run **at the same time**. Each keeps its own conversation, so a follow-up like "now add tests" continues where that thread left off.

### Use case 2: all repos at once

Create a thread on `@root` to act across the whole folder:

```
@root
!status all                       # uncommitted changes in every repo
!pull all                         # pull every repo
!sync all develop                 # stash → switch to develop → pull → re-apply changes, in every repo
!ship all feature/login "Add login" "Adds the login form"   # one PR per repo that has changes (clean repos are skipped)
```

For AI work across several repos ("rename this API field in the backend and the frontend"), stay on `@root`: the agent runs in the folder that contains all repos.

### Use case 3: same repo, different tools to compare

You can open two threads on the same repo with different engines, for example to compare answers on a read-only question. For **edits**, don't: two agents writing to the same repo at the same time can overwrite each other. Use one thread per repo for changes.

### Switching repos inside a thread

- `@web` makes `web` the active repo for the thread (sticky).
- `@web fix the header` switches and sends in one go.
- Each repo has its **own conversation per engine**, so switching back to a repo resumes where you left it.
- `!repos` lists the valid names and shows which one is active.

### Good to know

- **`!reset`, `!stop` and `!info` apply to the current thread only.** `!reset all` restores the defaults for this thread only.
- **`!sessions`** lists the saved sessions in this thread.
- **Archived threads keep their settings.** Discord archives idle threads. Post in one to wake it up, and the engine, model and repo are still set.
- **Everything runs on one machine.** Many parallel agents at once use your CPU, RAM and plan quota.

---

## Running and testing apps from your phone

Because your phone is on the same Tailscale network as the PC, you can test an app without sitting at the laptop. Just ask the agent in plain language:

> "Start the backend and the frontend for `@web` and send me the links."

When you ask to start, run, restart or stop dev servers, the bot adds these rules to the prompt:

1. **Reserved ports:** backends on `8000–8010`, Next.js/React frontends on `3000–3010`, Vite frontends on `5173–5183`. The agent checks `pm2 list` / `ss -tulpn` and picks free ones, so parallel projects don't clash.
2. **Bind to `0.0.0.0`** (`--host 0.0.0.0`) so the servers are reachable over Tailscale.
3. **Frontend API URLs and CORS** are pointed at `http://<your-tailscale-ip>:<port>`, so the frontend running on your phone can reach the backend.
4. **Everything is launched through PM2** (`pm2 start "<cmd>" --name <app_name>`). The agent's task then finishes cleanly while the servers keep running, with nothing hanging the task.
5. **The reply contains clickable URLs** like `http://100.x.y.z:3000`. Tap them on your phone (Tailscale connected).

Manage the servers later with PM2, or ask the agent: "stop the `web` server", "restart the backend", "what is running?". Use `pm2 status` on the PC to see everything.

> Port-based links only work while Tailscale is connected on the phone. See Troubleshooting if a link won't open.

---

## Command cheat sheet

Use these inside your linked Discord channels and threads. Type **`!help`** for the non-Git commands and **`!githelp`** for the Git commands at any time.

### Talking to the AI

| Command                              | What it does                                          |
| ------------------------------------ | ----------------------------------------------------- |
| *(any normal message)*             | Sent to the active engine, running in the active repo |
| `!use <claude\|cursor\|antigravity>` | Switch the active AI engine for this channel/thread   |
| `!stop` or `!cancel`             | Kill the running task for the current engine + repo   |
| Attach an image                      | Saved to `/tmp` and its path is passed to the agent   |

### Choosing the model

| Command                   | What it does                                                                |
| ------------------------- | --------------------------------------------------------------------------- |
| `!model`                | Show the current model (and the list if it is short)                        |
| `!model search <terms>` | Filter the model list, e.g. `!model search opus high`                     |
| `!model <number\|id>`    | Select a model for the **current** engine, by list number or exact id |

The list comes from the source of truth for each engine: the Anthropic API (or a built-in list) for Claude, `agent models` for Cursor, and `agy models` for Antigravity. Invalid names are rejected, so typos can't be saved. Model names in this guide are only examples; use `!model` to see what is available to **you**.

### Reasoning effort

| Command                                 | What it does                  |
| --------------------------------------- | ----------------------------- |
| `!effort`                             | Show the current effort       |
| `!effort <low\|medium\|high\|xhigh\|max>` | Set it for the current engine |

How it works per engine:

- **Claude:** passed as `--effort <level>` (default `high`). Which levels are accepted depends on the model and CLI version.
- **Cursor:** the level is part of the model id (e.g. `...-high`, `...-max`), so `!effort` swaps to the matching variant. If a model has no such variant, the bot lists the levels it does have.
- **Antigravity:** updates the `--effort` flag and swaps the model id suffix when one exists.

### Sessions and settings

| Command             | What it does                                                                                     |
| ------------------- | ------------------------------------------------------------------------------------------------ |
| `!info`           | Engine, model, effort, active repo, session id, running/idle                                     |
| `!sessions`       | List saved sessions in this channel/thread (numbered)                                            |
| `!reset`          | Forget the session for the current engine + repo (fresh conversation)                            |
| `!reset <number>` | Remove one session from the `!sessions` list                                                     |
| `!reset sessions` | Remove **all** saved sessions in this channel/thread (settings kept)                             |
| `!reset all`      | Remove all sessions **and** restore defaults (engine, models, effort, active repo)               |

A reset is refused while a task is running for that session. Send `!stop` first.

### Repos

| Command                  | What it does                                                        |
| ------------------------ | ------------------------------------------------------------------- |
| `!repos`               | List the Git repos in this channel's folder and show the active one |
| `@repo_name`           | Make a repo the active one (sticky)                                 |
| `@repo_name <message>` | Switch to that repo and send the message in one go                  |
| `@root`                | Work on the whole folder                                            |

### Git & GitHub (manual commands)

`[repo|all]` is optional when a single repo is active. On `@root`, pass a repo name or `all`.

| Command                                                                      | What it does                                                                  |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `!status [repo\|all]`                                                       | Modified, staged and untracked files plus diff stats (no commit)              |
| `!branch [repo\|all]`                                                       | Which branch each repo is on                                                  |
| `!pull [repo\|all]`                                                         | Pull the current branch. Replies `done`, `conflicts` or `detached HEAD`       |
| `!checkout [repo\|all] <branch>`                                            | Stash local changes → switch → pull. Changes **stay stashed**                 |
| `!sync [repo\|all] <branch>`                                                | Stash → switch → pull → **re-apply** your changes                             |
| `!ship [repo\|all] <new_branch> "<PR title>" "<description>" [base_branch]` | Create/switch to a branch, commit all changes, push, open a PR                |
| `!githelp` (alias `!ghhelp`)                                             | Git help inside Discord                                                       |

Notes:

- `!checkout` / `!sync` stop if the branch switch fails, and put your stashed changes back.
- With `all`, `!ship` skips repos that have no changes.
- Quote the PR title and description: `!ship my-app feature/login "Add login" "Adds the login form"`.

### Help

`!help` (alias `!commands`) and `!githelp` (alias `!ghhelp`).

---

## How Git works (bot commands vs. agents)

There are two ways to do Git, and both use the **same code** (`hubgit.py`):

1. **You type a command** (`!pull`, `!ship`, ...). The bot calls `hubgit.py` directly.
2. **You ask the agent in plain language** ("create a branch `fix/login`, commit, push and open a PR"). Every prompt the bot sends starts with a short *Git Rules* note telling the agent to:
   1. **Try `hubgit.py` first** for any Git action you request.
   2. If the script can't do it (or fails and its own commands can't fix it), **stop and tell you** which raw Git commands it wants to run and why. It must **wait for your approval**.
   3. Run raw Git **only after you explicitly say yes**, and only the commands you approved.
   4. Resolving merge/rebase conflict markers by editing files needs no approval. It then finishes with `hubgit.py continue` (or `abort`).
   5. Never add co-author / "Generated with" lines, never force-push, never push straight to `main`/`master` unless you say so.

When the agent asks for permission, its reply ends with a question and you answer **in the same channel or thread**. The session is resumed, so it remembers what it proposed. Don't send `!reset` between the question and your answer.

**Why this matters for your GitHub profile:** because everything goes through one script that strips AI co-author and "Generated with" lines and uses your own Git identity, your commits and PRs show **only you** as the contributor, not Claude, Cursor or Antigravity.

> [!NOTE]
> The Git Rules are an **instruction to the agent**, not a technical lock. The agents run with permissions disabled and could still ignore them. The guarantees listed under "Git-specific warnings" apply to everything that goes **through `hubgit.py`**.

---

## `hubgit.py` reference

You can also run it yourself in a terminal. It prints one JSON line: `{"ok": true|false, "results": [...]}`, and exits `0` on success, `1` otherwise.

```bash
export HUBGIT_BASE_DIR=~/work          # project root used for --repo lookups (defaults to the current folder)
python3 ~/scripts/hubgit.py repos
python3 ~/scripts/hubgit.py status --repo all
python3 ~/scripts/hubgit.py ship feature/login --title "Add login" --body "Adds the login form" --repo my-app
```

Inside a repo, `--repo` is optional. From a folder that is not a single repo, pass `--repo <name|all>`.

| Command                                             | Purpose                                                                                   |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `repos`                                           | List git repos under the project root                                                     |
| `branch`, `status`, `pull`                    | Read / sync the current branch                                                            |
| `checkout <branch>`                               | Stash → switch → pull (changes stay stashed)                                              |
| `sync <branch>`                                   | Stash → switch → pull → unstash                                                           |
| `new-branch <name> [--from <ref>]`                | Create and switch (or just switch if it exists)                                           |
| `commit -m "msg" [--files a b ...]`               | Stage everything (or only the listed files) and commit                                    |
| `push [--branch b] [--allow-protected]`           | Push the current branch (never forced)                                                    |
| `pr --title T --body B [--base B]`                | Open a PR for the current branch (needs `gh`)                                             |
| `ship <new_branch> --title T --body B [--base B]` | `new-branch` + `commit` + `push` + `pr` in one go                                         |
| `merge <branch>`                                  | Merge a branch into the current one                                                       |
| `stash push\|pop\|list [-m msg]`                    | Stash helpers                                                                             |
| `conflicts`                                       | List conflicted files and what is in progress                                             |
| `continue`                                        | After fixing conflict markers: stage and finish the merge / rebase / cherry-pick / revert |
| `abort`                                           | Abort the merge / rebase / cherry-pick / revert in progress                               |

Built-in guardrails:

- Never force-pushes. Refuses direct pushes to `main` / `master` unless `--allow-protected`.
- Strips AI `Co-authored-by` / "Generated with" lines from commit messages and PR text it creates.
- Leaves obvious secret files out when staging everything, and refuses to commit files that still contain conflict markers.
- Validates branch names. Commands that change things (`commit`, `push`, `pr`, `merge`, ...) work on **one repo at a time**; `ship` can run on `all` and skips clean repos.
- Never opens an editor or prompts for credentials.

---

## Troubleshooting

**The bot is offline / crashes on start**

- `pm2 logs discord-hub --lines 35 --nostream` shows the error.
- `NameError`, `ModuleNotFoundError: hubgit` → `hubgit.py` is missing or not in the same folder as `dev_discord_hub.py`.
- `discord.errors.LoginFailure` → wrong or reset token.
- `PrivilegedIntentsRequired` → turn on **Message Content Intent** in the Developer Portal.
- Errors about saving files → fix `SESSIONS_FILE` / `STATE_FILE` paths ([Step 6](#step-6-configure-the-bot)).

**The bot is online but ignores me**

- Your user ID doesn't match `ALLOWED_USER_ID`.
- The channel ID isn't in `PROJECT_MAP` (for threads, the **parent** channel must be).
- Message Content Intent is off.
- In a thread: the bot is missing the **Send Messages in Threads** permission.

**A new thread behaves differently from the channel**

- Normal. Threads don't inherit the channel's settings. They start on Antigravity and `@root`. Set them up with `!use`, `!model`, `!effort` and `@repo`, and check with `!info`.

**"CodeAgent is typing…" for a very long time**

- Normal for big tasks. The reply appears only when the agent finishes. Check it is alive: `pm2 logs discord-hub --lines 30 --nostream` (is there a `[STARTED]` without `[FINISHED]`?), and `ps -eo pid,etime,pcpu,cmd | grep -E "claude|agent|agy" | grep -v grep`.
- Low CPU is normal. The agent is mostly waiting on the network.
- Stuck for good? Send `!stop`. Then `!reset` and resend a smaller request: a long-running session has a big history, and every message re-reads it.
- Agents that start dev servers **outside PM2** can keep the run from ever finishing. The bot tells agents to use PM2 for servers.

**"There's an issue with the selected model…"**

- The name is wrong or your account/plan can't use it. Use `!model search <terms>` and pick from the list. Update the CLI (`claude update`, etc.) if the model is newer than your CLI.

**Git: "Repo not found"**

- Run `!repos` for valid names. On `@root`, pass a repo or `all`.

**`!ship` says PR failed**

- Run `gh auth status`. Check the branch pushed (look on GitHub) and that a PR for it doesn't already exist.

**A dev-server link from the agent won't open on my phone**

- The Tailscale app must be **connected** on the phone, signed into the same account as the PC.
- If the link says `http://localhost:...`, the PC's Tailscale isn't running. Check `tailscale status` and `tailscale ip -4` on the PC, then `pm2 restart discord-hub --update-env`.
- Check the server is up: `pm2 status`, and `ss -tulpn` to confirm it listens on `0.0.0.0` and not `127.0.0.1`.
- Frontend loads but data doesn't? The frontend's API URL or the backend's CORS isn't pointing at the Tailscale IP. Ask the agent to fix it.

**FileBrowser: the page won't open on my phone**

- Tailscale must be connected on **both** devices, signed into the same account.
- `pm2 status` should show `filebrowser` online. `pm2 logs filebrowser` shows startup errors.
- Use the current IP (`tailscale ip -4`) and the same port you started it with. If you bound to the Tailscale IP, `localhost:8090` won't work.

**FileBrowser: a symlinked folder is empty or errors out**

- Run `ls -l ~/filebrowser-root` and check each link points to a folder that exists and that your WSL user can read.

**Agent commands work in a terminal but not through the bot**

- PM2 may have a different `PATH`. Restart the bot from a terminal where the commands work: `pm2 restart discord-hub --update-env`.

**The bot stops answering when I'm away**

- The PC went to sleep, or WSL shut down. Disable sleep on the machine, and run `pm2 resurrect` if WSL restarted.

---

## Known limitations

- **Single user.** Only `ALLOWED_USER_ID` can use the bot.
- **No streaming, no timeout.** You get the full reply when the task ends. Long outputs are split into several messages.
- **One task at a time per engine + thread + repo.** Extra messages for the same combination wait their turn. `!stop` only stops the current engine + repo task.
- **The PC must be on.** The bot and agents run on your machine, so a sleeping or powered-off PC means no answers.
- **CLI flags can change.** The bot calls each agent CLI with specific flags (`--model`, `--effort`, `--add-dir`, `--resume`/`--conversation`, ...). If a CLI update renames them, that engine may break until the script is updated.
- **Model and effort names depend on your accounts and CLI versions.** Always trust `!model`, not the examples in this guide.
- **Linux / WSL2 only.**

---

## Updating, stopping and uninstalling

**Update**

```bash
cd ~/scripts
git pull
pm2 restart discord-hub
```

If you edited the config block in place, `git pull` may complain about local changes. Stash or merge them, and **re-check that your token is still set and not committed anywhere**.

**Stop / remove**

```bash
pm2 stop discord-hub filebrowser      # stop
pm2 delete discord-hub filebrowser    # remove from PM2
pm2 save                              # persist the change
```

Then delete `~/scripts` (and `~/filebrowser`, `~/filebrowser-root`) if you no longer need them. To fully revoke access, **reset the token** in the Developer Portal or remove the bot from your server, and remove the machine from your Tailscale admin console.

---

## Disclaimer

This is an independent, community project. It is **not affiliated with or endorsed by** Anthropic, Cursor, Google, Discord, Tailscale or FileBrowser. It automates third-party command-line tools and runs them with their safety prompts disabled. **Use it at your own risk**, on machines and code you are allowed to expose, and review what the agents change before you push it.
