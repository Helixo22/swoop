"""Registration of the native messaging host with Firefox and Chromium browsers.

Writes the host manifests that let only the Swoop extension start
swoop-native-host, for each browser whose profile directory exists.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

HOST_NAME = "io.github.swoop"
HOST_EXECUTABLE = "swoop-native-host"
FIREFOX_EXTENSION_ID = "swoop@swoop.github.io"
CHROMIUM_EXTENSION_ID = "jnibaeahonigkhacgglkbbedmiiddccf"  # derived from "key" in manifest.json

# browser profile directory -> manifest directory, relative to the home directory
_MANIFEST_DIRS = {
    ".mozilla": ".mozilla/native-messaging-hosts",
    ".config/chromium": ".config/chromium/NativeMessagingHosts",
    ".config/google-chrome": ".config/google-chrome/NativeMessagingHosts",
}
_BROWSER_NAMES = {
    ".mozilla": "Firefox",
    ".config/chromium": "Chromium",
    ".config/google-chrome": "Google Chrome",
}


def installed_browsers(home: Path | None = None) -> list[str]:
    """Names of the supported browsers that have a profile in the home directory."""
    home = home or Path.home()
    return [name for profile, name in _BROWSER_NAMES.items() if (home / profile).is_dir()]


def host_manifest(host_path: Path, *, firefox: bool) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "name": HOST_NAME,
        "description": "Swoop download manager",
        "path": str(host_path),
        "type": "stdio",
    }
    if firefox:
        manifest["allowed_extensions"] = [FIREFOX_EXTENSION_ID]
    else:
        manifest["allowed_origins"] = [f"chrome-extension://{CHROMIUM_EXTENSION_ID}/"]
    return manifest


def install_host_manifests(home: Path | None = None, host_path: Path | None = None) -> list[Path]:
    """Write the manifests for every installed browser and return their paths."""
    home = home or Path.home()
    host_path = host_path or _find_host()
    written = []
    for profile_dir, manifest_dir in _MANIFEST_DIRS.items():
        if not (home / profile_dir).is_dir():
            continue
        target = home / manifest_dir / f"{HOST_NAME}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        manifest = host_manifest(host_path, firefox=profile_dir == ".mozilla")
        target.write_text(json.dumps(manifest, indent=2) + "\n")
        written.append(target)
    return written


def _find_host() -> Path:
    found = shutil.which(HOST_EXECUTABLE)
    if found is None:
        raise FileNotFoundError(f"{HOST_EXECUTABLE} is not on PATH; install Swoop first")
    return Path(found).resolve()
