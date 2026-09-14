# Proposed: clean the Discord webhook before `curl` uses it

For `.github/workflows/release.yml`, step **Announce the release on Discord**.
Workflows are lee's to edit; this is the change, ready to paste.

## Why

The 1.0.11 and 1.0.12 releases both ended the step with

    curl: (3) URL rejected: Malformed input to a URL function

The secret `DISCORD_RELEASE_WEBHOOK` was set again on 2026-09-14 and the error
did not change. curl says this when the address has something in it an address
cannot have: a line ending, a space, quote marks around it, or an invisible
character such as the byte-order mark Windows PowerShell likes to put at the
start of text. None of those show up when you look at a pasted link, and GitHub
never shows a secret back, so there is no way to see it from outside.

So the step takes those characters off itself, and when what is left still is
not a Discord webhook address it says in words what is wrong with it - without
printing the address, which stays a secret either way (GitHub also masks it).

## The step, replaced

```yaml
      - name: Announce the release on Discord
        continue-on-error: true
        env:
          WEBHOOK: ${{ secrets.DISCORD_RELEASE_WEBHOOK }}
          VERSION: ${{ needs.check.outputs.version }}
        run: |
          if [ -z "$WEBHOOK" ]; then
            echo "DISCORD_RELEASE_WEBHOOK is not set; the release was not announced on Discord"
            exit 0
          fi
          # A pasted secret can carry what a browser never shows: a line ending,
          # spaces, quote marks, a byte-order mark. Take them off.
          clean="$(printf '%s' "$WEBHOOK" | sed $'s/^\xEF\xBB\xBF//' | tr -d '\r\n\t "'"'"'')"
          case "$clean" in
            https://discord.com/api/webhooks/*|https://discordapp.com/api/webhooks/*) ;;
            *)
              echo "The webhook secret is not a Discord webhook address after cleaning."
              echo "Length ${#clean}; it starts with: ${clean:0:8}..."
              echo "Set it again with: gh secret set DISCORD_RELEASE_WEBHOOK --repo $GITHUB_REPOSITORY"
              exit 1
              ;;
          esac
          jq -n --arg v "$VERSION" --arg repo "$GITHUB_REPOSITORY" '{
            username: "MangaTCT",
            content: ("**MangaTCT \($v)** is out.\n"
              + "Installed copies update themselves. New here? https://mangatct.com/download\n"
              + "What is in it: https://github.com/\($repo)/releases/tag/v\($v)"),
            allowed_mentions: {parse: []}
          }' | curl -fsS -X POST -H "Content-Type: application/json" --data @- "$clean"
```

`${clean:0:8}` prints only the first eight characters (`https://` when the
address is right), never the webhook's id or token.

## Or, without touching the workflow

Set the secret again by typing it at gh's own prompt instead of passing it in
from PowerShell, which is where an invisible character can come from:

    gh secret set DISCORD_RELEASE_WEBHOOK --repo Lerbernard/MangaTCT

then paste the address at the `? Paste your secret` prompt and press Enter.
