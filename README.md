<p align="center"><img src="data/icons/io.github.swoop.Swoop.svg" width="128" alt="Swoop logo"></p>

# Swoop

Swoop is an open source download manager for Linux, inspired by Free Download Manager.
Downloads are handled by [aria2](https://aria2.github.io/); Swoop provides the GTK4/libadwaita
interface, a CLI, browser integration and the lifecycle management of the aria2 process.

**Status:** early development.

## Usage

```sh
swoop                         # start Swoop (aria2 runs in the background)
swoop add <url> [--dir DIR] [--out NAME]
swoop quit
swoop install-browser-host    # register the native messaging host for Firefox/Chromium
```

Commands sent while Swoop is running are forwarded to the running instance over D-Bus.

## Browser extension

```sh
python browser-extension/build.py   # writes browser-extension/dist/{firefox,chromium}
swoop install-browser-host
```

Load `dist/firefox` from `about:debugging` or `dist/chromium` from `chrome://extensions`
(developer mode). Downloads are handed to Swoop; if Swoop is not available the browser keeps
them. Private-window downloads are never intercepted.

The Firefox build also forwards the site's cookies for intercepted downloads, so downloads behind
a login work. aria2 cannot scope a header to one host: if the server redirects the download to
another site, the cookies are sent there too. Links sent with "Download with Swoop" never carry
cookies, since they are often redirectors.

## Development

```sh
uv venv --system-site-packages   # reuse the system PyGObject
uv sync
uv run pytest
```

Requires Python 3.11+ and `aria2c` on `PATH`.

## License

GPL-3.0-or-later
