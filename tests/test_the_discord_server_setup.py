"""The Discord server, set up by a script lee runs with his own bot token.

lee: *"can you set up the whole server?"*. Asked of a fake Discord: no network
and no token anywhere in the suite. What matters is what the script SENDS -
that a dry run sends nothing, that a second run adds nothing, that a channel
already on the server is not touched, that the notice channels are read-only
and the beta and staff ones private, and that the token is never printed.
"""
import importlib.util

from where import PKG

_spec = importlib.util.spec_from_file_location("discord_setup", PKG / "tools" / "discord_setup.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


class FakeDiscord:
    """Just enough of Discord's API to set a server up against."""

    def __init__(self, channels=(), roles=(), features=()):
        self.channels = [dict(c) for c in channels]
        self.roles = [{"id": "g1", "name": "@everyone"}] + [dict(r) for r in roles]
        self.guild = {"id": "g1", "name": "MangaTCT", "features": list(features),
                      "verification_level": 0, "explicit_content_filter": 0,
                      "default_message_notifications": 0}
        self.calls, self.posts, self.patches, self.hooks = [], [], [], {}
        self.n = 0

    def _id(self, prefix):
        self.n += 1
        return f"{prefix}{self.n}"

    def __call__(self, method, path, body=None):
        self.calls.append((method, path))
        at = len(self.calls)
        if (method, path) == ("GET", "/users/@me/guilds"):
            return [{"id": "g1", "name": "MangaTCT"}]
        if (method, path) == ("GET", "/guilds/g1"):
            return dict(self.guild, roles=[dict(r) for r in self.roles])
        if (method, path) == ("GET", "/guilds/g1/channels"):
            return [dict(c) for c in self.channels]
        if (method, path) == ("POST", "/guilds/g1/roles"):
            role = dict(body, id=self._id("r"))
            self.roles.append(role)
            return role
        if (method, path) == ("POST", "/guilds/g1/channels"):
            channel = dict(body, id=self._id("c"), _at=at)
            self.channels.append(channel)
            return channel
        if (method, path) == ("PATCH", "/guilds/g1"):
            self.patches.append(dict(body, _at=at))
            self.guild.update(body)
            return self.guild
        if method == "POST" and path.endswith("/messages"):
            self.posts.append((path.split("/")[2], body["content"]))
            return {"id": self._id("m")}
        if path.endswith("/webhooks"):
            cid = path.split("/")[2]
            if method == "GET":
                return list(self.hooks.get(cid, []))
            hook = {"id": self._id("w"), "token": "webhook-secret", "name": body["name"]}
            self.hooks.setdefault(cid, []).append(hook)
            return hook
        raise AssertionError(f"unexpected call {method} {path}")


def _quiet(_line):
    pass


def _by_name(fake):
    return {c["name"]: c for c in fake.channels}


def test_a_dry_run_changes_nothing_and_shows_the_whole_plan():
    fake, lines = FakeDiscord(), []
    S.run(fake, apply=False, say=lines.append)
    assert {method for method, _path in fake.calls} == {"GET"}, "a dry run only looks"
    out = "\n".join(lines)
    for want in ("+ role Moderator", "+ role Beta Tester", "+ category Start here", "+ #rules",
                 "+ #help (forum)", "+ voice Lounge", "+ #beta-testing", "No piracy",
                 "Community server", "Nothing was changed"):
        assert want in out, want


def test_it_builds_the_server_once_and_a_second_run_adds_nothing():
    fake = FakeDiscord()
    S.run(fake, apply=True, say=_quiet)
    names = set(_by_name(fake))
    for want in ("Start here", "welcome", "rules", "announcements", "Help", "help", "bug-reports",
                 "feature-requests", "Community", "general", "showcase", "off-topic", "Lounge",
                 "Beta", "beta-testing", "Staff", "mod-chat", "mod-updates"):
        assert want in names, want
    before, posts, lines = len(fake.calls), len(fake.posts), []
    S.run(fake, apply=True, say=lines.append)
    assert not [c for c in fake.calls[before:] if c[0] in ("POST", "PATCH")], "nothing is made twice"
    assert len(fake.posts) == posts, "the welcome and rules are not posted twice"
    assert "webhook-secret" not in "\n".join(lines), "the webhook address is printed only when it is made"


def test_a_channel_already_on_the_server_is_left_alone():
    mine = {"id": "old1", "name": "general", "type": S.TEXT, "topic": "mine"}
    fake, lines = FakeDiscord(channels=[mine]), []
    S.run(fake, apply=True, say=lines.append)
    assert [c for c in fake.channels if c["name"] == "general"] == [mine]
    assert any(line.startswith("= #general") for line in lines)


def test_the_notice_channels_are_read_only_and_beta_and_staff_are_private():
    fake = FakeDiscord()
    S.run(fake, apply=True, say=_quiet)
    ch = _by_name(fake)
    mod = next(r["id"] for r in fake.roles if r["name"] == "Moderator")
    beta = next(r["id"] for r in fake.roles if r["name"] == "Beta Tester")
    for name in ("welcome", "rules", "announcements"):
        ow = {o["id"]: o for o in ch[name]["permission_overwrites"]}
        assert int(ow["g1"]["deny"]) & (1 << 11), f"#{name}: everyone may not write"
        assert int(ow[mod]["allow"]) & (1 << 11), f"#{name}: moderators may"
    for name, allowed in (("beta-testing", {beta, mod}), ("mod-updates", {mod}), ("mod-chat", {mod})):
        ow = {o["id"]: o for o in ch[name]["permission_overwrites"]}
        assert int(ow["g1"]["deny"]) & (1 << 10), f"#{name} is hidden from everyone"
        assert {rid for rid, o in ow.items() if int(o["allow"]) & (1 << 10)} == allowed, name
    assert next(r for r in fake.roles if r["name"] == "Beta Tester")["permissions"] == "0"
    assert not ch["general"]["permission_overwrites"], "the community channels are open"


def test_the_help_forums_carry_their_tags_and_the_posts_link_the_channels():
    fake = FakeDiscord()
    S.run(fake, apply=True, say=_quiet)
    ch = _by_name(fake)
    assert ch["bug-reports"]["type"] == S.FORUM
    assert "Fixed" in [t["name"] for t in ch["bug-reports"]["available_tags"]]
    posted = dict(fake.posts)
    assert "No piracy" in posted[ch["rules"]["id"]]
    assert f"<#{ch['help']['id']}>" in posted[ch["welcome"]["id"]], "channels are links, not typed names"
    for text in posted.values():
        assert len(text) <= 2000, "Discord's limit for one message"
        assert "{" not in text, "every mention was filled in"


def test_the_community_settings_come_before_the_forums_need_them():
    fake = FakeDiscord()
    S.run(fake, apply=True, say=_quiet)
    (patch,) = fake.patches
    ch = _by_name(fake)
    assert "COMMUNITY" in patch["features"]
    assert patch["rules_channel_id"] == ch["rules"]["id"]
    assert patch["public_updates_channel_id"] == ch["mod-updates"]["id"]
    assert patch["verification_level"] >= 1 and patch["explicit_content_filter"] == 2
    assert patch["default_message_notifications"] == 1
    assert patch["_at"] < ch["help"]["_at"], "the forums are made after the server is a Community one"


def test_the_token_comes_from_the_environment_only_and_is_never_printed():
    fake, lines = FakeDiscord(), []
    assert S.main(["--apply"], env={}, call=fake, say=lines.append) == 2
    assert "DISCORD_BOT_TOKEN" in "\n".join(lines) and fake.calls == [], "no token, no call"
    lines.clear()
    assert S.main(["--apply"], env={"DISCORD_BOT_TOKEN": "tok-SECRET-123"}, call=fake,
                  say=lines.append) == 0
    assert "tok-SECRET-123" not in "\n".join(lines)
    src = (PKG / "tools" / "discord_setup.py").read_text(encoding="utf-8")
    assert 'env.get("DISCORD_BOT_TOKEN")' in src and '"--token"' not in src


def test_a_refused_token_is_said_in_words():
    def refuses(method, path, body=None):
        raise S.DiscordError(401, {"message": "401: Unauthorized", "code": 0})
    lines = []
    assert S.main([], env={"DISCORD_BOT_TOKEN": "x"}, call=refuses, say=lines.append) == 1
    assert "Reset Token" in "\n".join(lines)
