"""The one place the app's version is written.

lee: *"also kkeep track of vesion ad thsi is v1.0.0"*.

Everything that names a version reads it from here: the pill in the editor's
header, `/api/version`, the bundle a chapter is saved as, the release zip
`tools/release.py` builds, and the git tag the release workflow runs on - the
workflow refuses a tag that does not match this file, so the number on the
download page and the number in the running app cannot disagree.

Plain semver, three numbers. The beta is said separately (`CHANNEL`) so
`1.0.0` stays `1.0.0` when the word comes off, and so a version compare in
the launcher never has to parse `-beta`.

Bumping it: change the string, commit, tag `v<string>`, push the tag. Nothing
else.
"""

__version__ = "1.0.0"

#: What the release is called beside the number. Empty string once the beta
#: is over - and the header pill reads the same string, so that is the
#: change that takes BETA off the screen.
CHANNEL = "beta"


#: Where a person with a problem goes. Read by the editor's Help section
#: and by the website's build, so the two never name different doors. Empty
#: until lee makes them; an empty one is simply not offered.
SUPPORT = {
    # This has to be a NEVER-EXPIRING invite. Discord's default is 7 days and
    # 100 uses, and this link is baked into a shipped exe as well as the site -
    # an installed copy would go on offering a dead door long after the invite
    # lapsed, with nothing to tell the person why nobody answered.
    # Confirmed never-expiring by lee, 2026-09-09. Worth re-checking on the
    # server if the invite is ever regenerated.
    "discord": "https://discord.gg/wsuD2EnSKt",
    # A plain Gmail, deliberately, and not a stopgap. An address on the domain
    # was costed out - it needs a mail host and DNS records, because forwarding
    # alone cannot SEND, and Google stopped letting a free Gmail send as an
    # outside address in 2023. lee: *"we not dong this we doing teh email i
    # gabve you only not forwarding just teh email"*. A working inbox somebody
    # reads beats a better-looking one that bounces.
    "email": "mangatct@gmail.com",
    "guide": "https://mangatctproject.web.app/tutorial",
    "download": "https://mangatctproject.web.app/download",
}


def parse(v: str) -> tuple:
    """`"1.2.10"` -> `(1, 2, 10)`, tolerant of a leading `v` and a trailing
    `-beta`; anything unparseable sorts below every real version."""
    v = (v or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    try:
        parts = tuple(int(x) for x in v.split("."))
    except ValueError:
        return (-1,)
    return parts + (0,) * (3 - len(parts)) if len(parts) < 3 else parts


def newer(candidate: str, current: str = __version__) -> bool:
    """Is `candidate` a strictly newer version than `current`?"""
    return parse(candidate) > parse(current)
