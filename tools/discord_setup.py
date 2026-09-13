#!/usr/bin/env python3
"""Set up the MangaTCT Discord server: categories, channels, forum tags, roles,
permissions, the welcome and rules posts, the server's safety settings, and a
webhook for release announcements.

lee: *"can you set up the whole server?"* - the server he already has, with a
script he runs himself, so the bot's token never passes through anybody else.

    1. https://discord.com/developers/applications -> New Application (call
       it "MangaTCT Setup") -> Bot -> Reset Token, and copy the token.
    2. OAuth2 -> URL Generator: tick the `bot` scope and the `Administrator`
       permission. Open the link it makes and pick the MangaTCT server.
    3. In PowerShell, from the repository folder:
           $env:DISCORD_BOT_TOKEN = "<the token>"
           python tools\\discord_setup.py            # shows what it would do
           python tools\\discord_setup.py --apply    # does it

WHAT IS ALREADY THERE IS LEFT ALONE. A role or channel with the same name is
reported and not touched - not renamed, not moved, not given new permissions -
so it can be run again after the plan changes and it only adds what is missing.
The welcome and rules messages are posted only into channels this run made.

The token is read from the environment and nowhere else: an argument would sit
in the shell history. It is never printed. The webhook's address, which is a
secret of its own, is printed once, to the terminal the script runs in, when
the webhook is made - it is what the last step of `.github/workflows/release.yml`
posts to, from the repository secret DISCORD_RELEASE_WEBHOOK. Set that with
`gh secret set DISCORD_RELEASE_WEBHOOK`, which asks for the value without
showing it. If it ever leaks: delete "MangaTCT Releases" under #announcements >
Edit Channel > Integrations > Webhooks, run this again with --apply for a new
one, and set the secret again.

Standard library only, so it runs on the Python the app already needs.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://mangatct.com, 1.0)"
HOOK_NAME = "MangaTCT Releases"

# Channel types and permission bits, as Discord numbers them.
TEXT, VOICE, CATEGORY, NEWS, FORUM = 0, 2, 4, 5, 15
VIEW = 1 << 10
# Sending, in the channel and in its threads, and starting threads: all four,
# or a "read-only" channel still takes replies in a thread.
SEND = (1 << 11) | (1 << 38) | (1 << 35) | (1 << 36)
MODERATOR_PERMISSIONS = ((1 << 1)      # kick
                         | (1 << 2)    # ban
                         | (1 << 7)    # view the audit log
                         | (1 << 13)   # manage messages
                         | (1 << 22)   # mute in voice
                         | (1 << 24)   # move in voice
                         | (1 << 34)   # manage threads and forum posts
                         | (1 << 40))  # time out members

ROLES = [
    {"name": "Moderator", "color": 0xFFC400, "hoist": True, "mentionable": True,
     "permissions": str(MODERATOR_PERMISSIONS)},
    {"name": "Beta Tester", "color": 0x7C4DFF, "hoist": False, "mentionable": True,
     "permissions": "0"},
]

WELCOME = """**Welcome to MangaTCT.**

MangaTCT is a Windows app that translates, cleans and typesets manga, manhwa and manhua - and keeps every decision where you can change it.

**Get started**
- Download: https://mangatct.com/download
- The guide: https://mangatct.com/tutorial
- Coins and prices: https://mangatct.com/pricing

**In here**
- Read {rules} once.
- Stuck? Start a post in {help}.
- Found a bug? One post per bug in {bug_reports}, with what File > Help > Report a problem copies for you.
- Ideas go in {feature_requests}.
- New versions are posted in {announcements}.
- Show what you made in {showcase}, and talk in {general}."""

RULES = """**Rules**

1. Be kind. No harassment, hate, slurs or personal attacks.
2. No piracy. Do not share, ask for or link raws or translations you do not have the right to share. MangaTCT only opens files you already have.
3. Keep {help}, {bug_reports} and {feature_requests} on topic. Everything else is welcome in {general} and {off_topic}.
4. No NSFW content, anywhere.
5. No spam, no advertising, and no DMs nobody asked for.
6. Never post a password, a sign-in link or a key - and nobody from MangaTCT will ever ask you for one.
7. Follow Discord's Terms of Service and Community Guidelines.

Moderators may remove anything that breaks these rules. To ask about a decision, message a moderator rather than the channel."""

LAYOUT = [
    {"category": "Start here", "access": "read_only", "channels": [
        {"name": "welcome", "type": TEXT, "topic": "What MangaTCT is, and where to go in here.",
         "post": WELCOME},
        {"name": "rules", "type": TEXT, "topic": "The rules of this server. Read them once.",
         "post": RULES},
        {"name": "announcements", "type": TEXT,
         "topic": "New versions of MangaTCT, as they come out.", "webhook": True},
    ]},
    {"category": "Help", "access": None, "channels": [
        {"name": "help", "type": FORUM,
         "topic": "Ask anything about using MangaTCT. One question per post and a clear title. "
                  "File > Help > Report a problem copies your version for you. "
                  "Tag it Solved when it is.",
         "tags": ["Installing", "Signing in", "Coins", "Find text", "Translating", "Cleaning",
                  "Typesetting", "Export", "Solved"]},
        {"name": "bug-reports", "type": FORUM,
         "topic": "One bug per post: your version, what you did, what you expected, and what "
                  "happened instead. File > Help > Report a problem > Copy to clipboard gives "
                  "your version, machine and last log lines - paste them in.",
         "tags": ["Open", "Confirmed", "Fixed", "Can't reproduce", "Duplicate"]},
        {"name": "feature-requests", "type": FORUM,
         "topic": "One idea per post. Say what you are trying to do, not only the button you want.",
         "tags": ["Under consideration", "Planned", "Done", "Not planned"]},
    ]},
    {"category": "Community", "access": None, "channels": [
        {"name": "general", "type": TEXT, "topic": "MangaTCT, manga, manhwa and manhua."},
        {"name": "showcase", "type": TEXT,
         "topic": "Pages you made with MangaTCT. Only share work you have the right to share."},
        {"name": "off-topic", "type": TEXT, "topic": "Anything else."},
        {"name": "Lounge", "type": VOICE},
    ]},
    {"category": "Beta", "access": "beta", "channels": [
        {"name": "beta-testing", "type": TEXT,
         "topic": "Early builds and what to try in them. Beta testers only."},
    ]},
    {"category": "Staff", "access": "staff", "channels": [
        {"name": "mod-chat", "type": TEXT, "topic": "Moderators only."},
        {"name": "mod-updates", "type": TEXT, "topic": "The notices Discord sends to server staff."},
    ]},
]

# The Community settings need a rules channel and a staff-updates channel to
# exist first, and forums are made after them - so these two sections go first.
FIRST = ("Start here", "Staff")

SETTING_WORDS = {
    "verification_level": "members need a verified email",
    "explicit_content_filter": "media from every member is scanned",
    "default_message_notifications": "notifications for mentions only",
    "features": "Community server, with #rules and #mod-updates",
}


class SetupError(Exception):
    """Something to say to the person running it, in words."""


class DiscordError(Exception):
    def __init__(self, status, body):
        self.status = int(status)
        self.body = body if isinstance(body, dict) else {}
        self.code = self.body.get("code")
        super().__init__(f"{self.status} {self.body.get('message', '')}".strip())


def explain(e):
    if e.status == 401:
        return ("Discord refused the token. In the Developer Portal open the application, "
                "Bot > Reset Token, and set DISCORD_BOT_TOKEN to the new one.")
    if e.status == 403 or e.code == 50013:
        return ("The bot is missing a permission. Open the invite link again (OAuth2 > URL "
                "Generator, scope bot, permission Administrator) and pick the server.")
    if e.code == 50001:
        return "The bot cannot see that part of the server. Is it in the server?"
    return f"Discord said {e}."


def overwrites(access, everyone, roles):
    """Who may see and write in a channel. `everyone` is the @everyone role,
    whose id is the server's own."""
    mod, beta = roles.get("Moderator"), roles.get("Beta Tester")
    if access == "read_only":
        out = [{"id": everyone, "type": 0, "allow": "0", "deny": str(SEND)}]
        if mod:
            out.append({"id": mod, "type": 0, "allow": str(SEND), "deny": "0"})
        return out
    if access in ("beta", "staff"):
        out = [{"id": everyone, "type": 0, "allow": "0", "deny": str(VIEW)}]
        for rid in ((beta, mod) if access == "beta" else (mod,)):
            if rid:
                out.append({"id": rid, "type": 0, "allow": str(VIEW), "deny": "0"})
        return out
    return []


class _Mentions(dict):
    def __missing__(self, key):
        return "#" + key.replace("_", "-")


def run(call, apply=False, say=print, guild_id=None):
    """Compare the server with the plan; say what is there and what is not;
    with `apply`, add what is not. `call(method, path, body)` speaks to Discord
    and returns the decoded answer. Returns the counts."""
    guilds = call("GET", "/users/@me/guilds") or []
    if guild_id:
        guild = next((g for g in guilds if str(g.get("id")) == str(guild_id)), None)
        if guild is None:
            raise SetupError(f"The bot is not in a server with the ID {guild_id}.")
    elif len(guilds) == 1:
        guild = guilds[0]
    elif not guilds:
        raise SetupError("The bot is not in any server yet. Open the invite link from step 2 "
                         "at the top of tools/discord_setup.py and pick the MangaTCT server.")
    else:
        raise SetupError("The bot is in more than one server. Say which one with --guild: "
                         + ", ".join(f'{g.get("name")} ({g.get("id")})' for g in guilds))
    gid = str(guild["id"])
    info = call("GET", f"/guilds/{gid}") or {}
    channels = list(call("GET", f"/guilds/{gid}/channels") or [])
    name = info.get("name") or guild.get("name") or gid
    say(f'Setting up "{name}".' if apply else
        f'Dry run for "{name}" - nothing is changed. Run it again with --apply to do it.')
    count = {"new": 0, "kept": 0}

    def placeholder(label):
        return f"<new {label}>"

    roles = {}
    have_roles = {str(r.get("name", "")).casefold(): r for r in info.get("roles") or []}
    for spec in ROLES:
        got = have_roles.get(spec["name"].casefold())
        if got:
            roles[spec["name"]] = str(got["id"])
            count["kept"] += 1
            say(f'= role {spec["name"]} (already there, left as it is)')
            continue
        count["new"] += 1
        say(f'+ role {spec["name"]}')
        roles[spec["name"]] = (str(call("POST", f"/guilds/{gid}/roles", spec)["id"])
                               if apply else placeholder(spec["name"]))

    ids, made = {}, set()

    def find(wanted, kinds):
        for ch in channels:
            if str(ch.get("name", "")).casefold() == wanted.casefold() and ch.get("type") in kinds:
                return ch
        return None

    def create(body, label):
        got = call("POST", f"/guilds/{gid}/channels", body)
        channels.append(got)
        return str(got["id"])

    def section(sec, position):
        access = sec.get("access")
        cat = find(sec["category"], (CATEGORY,))
        if cat:
            cat_id = str(cat["id"])
            count["kept"] += 1
            say(f'= category {sec["category"]} (already there, left as it is)')
        else:
            count["new"] += 1
            say(f'+ category {sec["category"]}')
            body = {"name": sec["category"], "type": CATEGORY, "position": position,
                    "permission_overwrites": overwrites(access, gid, roles)}
            cat_id = create(body, sec["category"]) if apply else placeholder(sec["category"])
        for spec in sec["channels"]:
            kinds = {TEXT: (TEXT, NEWS), FORUM: (FORUM, TEXT, NEWS)}.get(spec["type"], (spec["type"],))
            label = ("voice " if spec["type"] == VOICE else "#") + spec["name"]
            got = find(spec["name"], kinds)
            if got:
                ids[spec["name"]] = str(got["id"])
                count["kept"] += 1
                say(f"= {label} (already there, left as it is)")
                continue
            count["new"] += 1
            say(f"+ {label}" + (" (forum)" if spec["type"] == FORUM else "")
                + (f" - {spec['topic']}" if spec.get("topic") else ""))
            body = {"name": spec["name"], "type": spec["type"], "parent_id": cat_id,
                    "permission_overwrites": overwrites(access, gid, roles)}
            if spec.get("topic") and spec["type"] != VOICE:
                body["topic"] = spec["topic"]
            if spec.get("tags"):
                body["available_tags"] = [{"name": t} for t in spec["tags"]]
                say("    tags: " + ", ".join(spec["tags"]))
            if not apply:
                ids[spec["name"]] = placeholder(spec["name"])
            elif spec["type"] == FORUM:
                try:
                    ids[spec["name"]] = create(body, spec["name"])
                except DiscordError as e:
                    # A server Discord will not give forums to still gets the
                    # channel, as an ordinary one, rather than a gap.
                    plain = {k: v for k, v in body.items() if k != "available_tags"}
                    plain["type"] = TEXT
                    ids[spec["name"]] = create(plain, spec["name"])
                    say(f"! #{spec['name']} could not be a forum here ({e}); "
                        "it was made as a text channel instead")
            else:
                ids[spec["name"]] = create(body, spec["name"])
            made.add(spec["name"])

    def settings():
        change = {}
        if int(info.get("verification_level") or 0) < 1:
            change["verification_level"] = 1
        if int(info.get("explicit_content_filter") or 0) != 2:
            change["explicit_content_filter"] = 2
        if int(info.get("default_message_notifications") or 0) != 1:
            change["default_message_notifications"] = 1
        features = list(info.get("features") or [])
        if "COMMUNITY" not in features and ids.get("rules") and ids.get("mod-updates"):
            change["features"] = features + ["COMMUNITY"]
            change["rules_channel_id"] = ids["rules"]
            change["public_updates_channel_id"] = ids["mod-updates"]
        if not change:
            count["kept"] += 1
            say("= server settings (already as planned)")
            return
        count["new"] += 1
        say("+ server settings: " + "; ".join(SETTING_WORDS[k] for k in change if k in SETTING_WORDS))
        if apply:
            try:
                call("PATCH", f"/guilds/{gid}", change)
            except DiscordError as e:
                say(f"! the server settings were not changed ({explain(e)}) - everything else "
                    "goes ahead; set them in Server Settings instead")

    order = {sec["category"]: i for i, sec in enumerate(LAYOUT)}
    for sec in LAYOUT:
        if sec["category"] in FIRST:
            section(sec, order[sec["category"]])
    settings()
    for sec in LAYOUT:
        if sec["category"] not in FIRST:
            section(sec, order[sec["category"]])

    mentions = _Mentions({key.replace("-", "_"): (f"<#{cid}>" if apply else f"#{key}")
                          for key, cid in ids.items()})
    for sec in LAYOUT:
        for spec in sec["channels"]:
            if not spec.get("post"):
                continue
            if spec["name"] not in made:
                say(f"= #{spec['name']} was already there, so nothing is posted in it")
                continue
            text = spec["post"].format_map(mentions)
            count["new"] += 1
            say(f"+ post in #{spec['name']}:")
            for line in text.splitlines():
                say("    " + line)
            if apply:
                call("POST", f"/channels/{ids[spec['name']]}/messages", {"content": text})

    hook_channel = next((ids.get(s["name"]) for sec in LAYOUT for s in sec["channels"]
                         if s.get("webhook")), None)
    if hook_channel:
        existing = [] if hook_channel.startswith("<new") else (
            call("GET", f"/channels/{hook_channel}/webhooks") or [])
        if any(h.get("name") == HOOK_NAME for h in existing):
            count["kept"] += 1
            say(f'= webhook "{HOOK_NAME}" (already there - its address was printed when it was made)')
        elif not apply:
            count["new"] += 1
            say(f'+ webhook "{HOOK_NAME}" in #announcements (its address is printed once, when it is made)')
        else:
            count["new"] += 1
            hook = call("POST", f"/channels/{hook_channel}/webhooks", {"name": HOOK_NAME})
            say(f'+ webhook "{HOOK_NAME}". Its address is a secret - anyone with it can post as it:')
            say(f"    https://discord.com/api/webhooks/{hook['id']}/{hook['token']}")
            say("    Save it in GitHub as the repository secret DISCORD_RELEASE_WEBHOOK "
                "(gh secret set DISCORD_RELEASE_WEBHOOK asks for it without showing it).")

    if apply:
        say(f"Done: {count['new']} added, {count['kept']} already there.")
    else:
        say(f"{count['new']} to add, {count['kept']} already there. Nothing was changed.")
    return count


def caller(token):
    """The real thing: Discord's HTTP API, with the bot token, waiting out the
    rate limit when Discord asks."""
    def call(method, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Authorization": "Bot " + token, "User-Agent": USER_AGENT}
        if data is not None:
            headers["Content-Type"] = "application/json"
        for _ in range(8):
            req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                raw = e.read()
                try:
                    got = json.loads(raw or b"{}")
                except ValueError:
                    got = {}
                if e.code == 429:
                    time.sleep(float(got.get("retry_after", 1)) + 0.25)
                    continue
                raise DiscordError(e.code, got) from None
            except urllib.error.URLError as e:
                raise SetupError(f"Could not reach Discord ({e.reason}).") from None
        raise SetupError("Discord kept asking to slow down. Run it again in a minute.")
    return call


def main(argv=None, env=None, call=None, say=print):
    ap = argparse.ArgumentParser(prog="python tools/discord_setup.py",
                                 description="Set up the MangaTCT Discord server.")
    ap.add_argument("--apply", action="store_true",
                    help="make the changes (without it, only show them)")
    ap.add_argument("--guild", help="the server's ID, if the bot is in more than one server")
    a = ap.parse_args(argv)
    env = os.environ if env is None else env
    token = (env.get("DISCORD_BOT_TOKEN") or "").strip()
    if not token:
        say("Set DISCORD_BOT_TOKEN first. Where the token comes from is at the top of "
            "tools/discord_setup.py; in PowerShell:")
        say('    $env:DISCORD_BOT_TOKEN = "<the bot token>"')
        return 2
    try:
        run(call or caller(token), apply=a.apply, say=say, guild_id=a.guild)
    except SetupError as e:
        say(str(e))
        return 1
    except DiscordError as e:
        say(explain(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
