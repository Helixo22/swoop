<p align="center"><img src="data/icons/io.github.swoop.Swoop.svg" width="128" alt="Swoop logo"></p>

# Swoop

Swoop is an open source download manager for Linux, inspired by Free Download Manager.
Downloads are handled by [aria2](https://aria2.github.io/); Swoop provides the GTK4/libadwaita
interface, a CLI, browser integration and the lifecycle management of the aria2 process.

**Status:** early development.

## Development

```sh
uv venv --system-site-packages   # reuse the system PyGObject
uv sync
uv run pytest
```

Requires Python 3.11+ and `aria2c` on `PATH`.

## License

GPL-3.0-or-later
