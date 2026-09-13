# Proposed: announce each release in the Discord server

For lee to add to `.github/workflows/release.yml` (workflows are his to edit).
lee: *"can you set up the whole server?"* - `tools/discord_setup.py` makes a
webhook called "MangaTCT Releases" in #announcements and prints its address
once. This step posts to it when a release goes out.

## 1. The secret

GitHub > the repository > Settings > Secrets and variables > Actions > New
repository secret:

* Name: `DISCORD_RELEASE_WEBHOOK`
* Value: the address `discord_setup.py --apply` printed
  (`https://discord.com/api/webhooks/...`)

Anyone holding that address can post in #announcements as the webhook, so it
goes in the secret and nowhere else. If it ever leaks: Discord > #announcements
> Edit Channel > Integrations > Webhooks > delete "MangaTCT Releases", run the
setup script again with `--apply` (it makes a new one), and update the secret.

## 2. The step

At the END of the `publish` job, after "Point the channel at the new version".
Last, and not straight after the release is created, because the post says
installed copies update themselves - true only once the manifest names the new
version.

```yaml
      # 3. a note in the Discord server's #announcements, through the webhook
      #    tools/discord_setup.py made. With no secret set it says so and
      #    stops; and a Discord that is down does not fail a release that is
      #    already out (continue-on-error). allowed_mentions is empty so a
      #    version name can never ping anybody.
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
          jq -n --arg v "$VERSION" --arg repo "$GITHUB_REPOSITORY" '{
            username: "MangaTCT",
            content: ("**MangaTCT \($v)** is out.\n"
              + "Installed copies update themselves. New here? https://mangatct.com/download\n"
              + "What is in it: https://github.com/\($repo)/releases/tag/v\($v)"),
            allowed_mentions: {parse: []}
          }' | curl -fsS -X POST -H "Content-Type: application/json" --data @- "$WEBHOOK"
```

`jq` and `curl` are already on `ubuntu-latest`. The secret reaches the step
only through `env`, so it is masked in the log and never written into the
command line the log shows.

After adding it, delete this file.
