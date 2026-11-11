# Pandora for myMPD

Pick a saved Pandora station in myMPD and listen through MPD. A Python
service uses Pydora to load stations and FFmpeg to deliver a continuous
MP3 stream across tracks and playlist batches.

## Start the bridge

Use an existing working Pydora config. Compose mounts it read-only and
runs the bridge as your UID and GID so it can read a mode-0600 file.

```bash
export PANDORA_CONFIG="$HOME/.pydora.cfg"
export PANDORA_UID="$(id -u)" PANDORA_GID="$(id -g)"
```

If myMPD and MPD use host networking, start the bridge on loopback.

```bash
docker compose -f compose.yaml -f compose.host.yaml up --pull always -d
```

If myMPD and MPD share a private Docker network, use the base Compose file.

```bash
export MPD_NETWORK=your-existing-mpd-network
docker compose up --pull always -d
```

Clients on that Docker network can list and play stations.

## Install the picker

Enable Lua scripting in myMPD. Run the installer against its HTTP or HTTPS
base URL. If PIN protection is enabled, set `MYMPD_SESSION` to a valid
session token obtained with `MYMPD_API_SESSION_LOGIN`.

```bash
python3 install-picker.py --mympd http://localhost:8081 \
  --service http://127.0.0.1:18765
```

Replace the myMPD URL with your instance's address. Omit `--service` for
the shared Docker network deployment, which defaults to
`http://pandora:8080`. Use `--partition` for a non-default partition. Alternatively,
paste the Lua source into the myMPD script editor, name the script
`Pandora`, and set its menu order to 1.

Open **Pandora** from myMPD's scripts menu and select a station. The script
adds its stream to the MPD queue and starts playback. Use MPD's stop control
to end the stream. MPD receives the station name and updates its track title
to Artist — Song Title as Pandora advances.

## Refresh station artwork

After adding or changing stations, run the artwork sync from a host that can
reach the bridge and write to myMPD's `pics/thumbs` directory. Use the same
bridge URL that the picker uses for MPD playback.

```bash
python3 sync-station-art.py --service http://127.0.0.1:18765 \
  --thumbs /var/lib/mympd/pics/thumbs
```

myMPD uses its default stream image for stations without Pandora artwork.

## Player controls

Install the controls proxy with `install-picker.py --controls` using the same
myMPD and bridge URLs as for the picker. Use `--replace` to update an existing
proxy.

Copy `pandora-controls.js` to `pics/pandora-controls-v4.js` in myMPD's work
directory. Add the contents of `pandora-loader.js` to `config/custom_js`
(`config/custom.js` in some versions). The loader keeps the customization file
within myMPD's size limit. If you use a different bridge URL, set the
`bridge` constant in the player script to match. Restart myMPD and reload the
web app.

While a Pandora station is playing, Next skips the current song and the heart
toggles its Pandora thumbs-up. A red heart indicates a thumbs-up. The controls
wait for the displayed track to match the bridge's active track.

The player also offers separate **Thumbs Down** and **Remove Pandora rating**
buttons and a Pandora song actions menu. The **Manage Pandora stations** button opens station
search, creation, editing, ratings, seeds, and QuickMix membership.

## Contributing

Report bugs in [Issues](https://github.com/bonelifer/mympd-pandora/issues).
Use [Discussions](https://github.com/bonelifer/mympd-pandora/discussions) for
questions and feature ideas.

## Acknowledgments

- Code and documentation assisted by [Codex](https://openai.com/codex/).

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
The Pandora icon has [its own license](assets/README.md).
