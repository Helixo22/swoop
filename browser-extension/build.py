"""Build the Swoop WebExtension for Firefox and Chromium.

Both builds share src/ (background script and icons) and differ only in their
manifest: only Firefox gets cookie access, so its logged-in downloads keep working.
Usage: python browser-extension/build.py  ->  browser-extension/dist/{firefox,chromium}
"""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path
from typing import Any

from swoop.browser_integration import FIREFOX_EXTENSION_ID

ROOT = Path(__file__).resolve().parent
# Public half of the key that pins CHROMIUM_EXTENSION_ID; the private key is not in the repo.
CHROMIUM_PUBLIC_KEY = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwL+Wan4MZRaKwTBuuykrwSUV7qyp1vrkmPsvqhwHPFiv"
    "cIUfp7wtbOo72ULWN+XtH5GI8GmBNyIDdKwabxM1VWvsXEMmWGFgM/67+GX2WeqqvG8Y6k7ojdJ6nWSBm7AB5UEH"
    "w0fKUhZVWHUahLgqFcPSAE8eTKst25NVS+0trOJdyt+o02a46QGHZcOEppMuYSp+eWFhXvvOgYtAjPybqQASiekL"
    "XWoWtnJ9ZKF5HQ0p4+MlRXy/vUSRhDlRMSiN7Gktz1Le9UFpl9LjouoyWNRU6xyDwzLNcsaNKv8ZfLHzpkZUvOoW"
    "MSpLUFAxI9Wh4bZ1MZYDbAJFscOyVMGakwIDAQAB"
)
_PERMISSIONS = ["downloads", "nativeMessaging", "contextMenus"]


def _version() -> str:
    with (ROOT.parent / "pyproject.toml").open("rb") as file:
        return str(tomllib.load(file)["project"]["version"])


def manifest(browser: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "manifest_version": 3,
        "name": "Swoop",
        "version": _version(),
        "description": "Hand browser downloads over to the Swoop download manager.",
        "icons": {size: f"icons/swoop-{size}.png" for size in ("16", "48", "128")},
    }
    if browser == "firefox":
        return base | {
            "permissions": [*_PERMISSIONS, "cookies"],
            "host_permissions": ["<all_urls>"],  # cookies.getAll needs the download's origin
            "background": {"scripts": ["background.js"]},
            "browser_specific_settings": {
                "gecko": {
                    "id": FIREFOX_EXTENSION_ID,
                    "strict_min_version": "127.0",  # first to grant host permissions at install
                    "data_collection_permissions": {"required": ["none"]},
                }
            },
        }
    if browser == "chromium":
        return base | {
            "permissions": _PERMISSIONS,
            "background": {"service_worker": "background.js"},
            "key": CHROMIUM_PUBLIC_KEY,
        }
    raise ValueError(f"unknown browser: {browser}")


def build(dist: Path) -> list[Path]:
    """Write dist/<browser>/ and dist/swoop-<browser>.zip for every browser."""
    outputs = []
    for browser in ("firefox", "chromium"):
        target = dist / browser
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(ROOT / "src", target)
        (target / "manifest.json").write_text(json.dumps(manifest(browser), indent=2) + "\n")
        archive = shutil.make_archive(str(dist / f"swoop-{browser}"), "zip", target)
        outputs += [target, Path(archive)]
    return outputs


if __name__ == "__main__":
    for output in build(ROOT / "dist"):
        print(output)
