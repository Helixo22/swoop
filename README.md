<p align="center"><img src="src/swoop/ui/icons/hicolor/scalable/apps/io.github.swoop.Swoop.svg" width="128" alt="Swoop logo"></p>

# Swoop

Swoop is an open source download manager for Linux, inspired by Free Download Manager.
Downloads are handled by [aria2](https://aria2.github.io/); Swoop provides the GTK4/libadwaita
interface, a CLI, browser integration and the lifecycle management of the aria2 process.

**Status:** early development.

## Usage

```sh
swoop                         # open the window (aria2 runs in the background)
swoop add <url|magnet> [--dir DIR] [--out NAME]
swoop add-torrent <file.torrent> [--dir DIR]
swoop open <url|magnet|file>  # what the desktop calls for magnet links and .torrent files
swoop list                    # unfinished downloads
swoop quit                    # stop Swoop and aria2
swoop setup-browsers          # register the browser host and export the extension
swoop install-desktop         # add Swoop and its icon to the app launcher
```

Commands sent while Swoop is running are forwarded to the running instance over D-Bus;
otherwise the command starts Swoop in the background first (`setup-browsers` and
`install-desktop` always run on their own). `--dir` paths must stay inside your home directory;
relative ones start there.
Closing the window keeps downloads going; choose Quit (Ctrl+Q) to stop them. Without a display
Swoop runs headless.

On first launch a setup guide configures everything in one click: download folder, queue
limits, browser host, launcher entry with icon and magnet links. It then offers to install the
browser extension and can be reopened from the menu. Preferences (Ctrl+,) set the download
folder, the number of simultaneous downloads and the speed limit, saved in
`~/.config/swoop/config.toml`.

Torrents and magnet links are downloaded by aria2 (Ctrl+O opens a .torrent file) and seed until
a share ratio of 1.0, aria2's default.

## Browser extension

The setup guide installs it in every detected browser (Firefox, Zen, LibreWolf, Chromium,
Google Chrome):

- Firefox-based browsers only install add-ons signed by Mozilla permanently. Until a signed
  package is shipped (put it at `src/swoop/data/swoop-firefox-signed.xpi` and the Install button
  uses it), Swoop opens `about:debugging`: choose "Load Temporary Add-on" and pick `manifest.json`
  in the folder Swoop shows. The add-on then stays until the browser restarts. To sign it with
  your own addons.mozilla.org account: `npx web-ext sign --channel=unlisted --source-dir
  ~/.local/share/swoop/browser-extension/firefox --api-key=… --api-secret=…`.
- Chromium-based browsers open their extensions page together with the folder to pick with
  "Load unpacked" (Developer mode); this install is permanent.
- Browsers installed as Flatpak are listed but cannot be connected: their sandbox does not let
  an extension start programs outside it.

`swoop setup-browsers` exports the same builds to `~/.local/share/swoop/browser-extension`.

Downloads are handed to Swoop; if Swoop is not available the browser keeps them.
Private-window downloads are never intercepted.

The Firefox build also forwards the site's cookies for intercepted downloads, so downloads behind
a login work. aria2 cannot scope a header to one host: if the server redirects the download to
another site, the cookies are sent there too. Links sent with "Download with Swoop" never carry
cookies, since they are often redirectors.

## Flatpak

```sh
flatpak-builder --user --install --force-clean build-dir packaging/flatpak/io.github.swoop.Swoop.yml
flatpak run io.github.swoop.Swoop
```

The Flatpak bundles aria2 and installs its own launcher entry and icons. Browser integration
needs the native host on the host system, so for now it works with the pip/uv installation.

## Development

```sh
uv venv --system-site-packages   # reuse the system PyGObject
uv sync
uv run pytest
```

Requires Python 3.11+ and `aria2c` on `PATH`.

## License

GPL-3.0-or-later
