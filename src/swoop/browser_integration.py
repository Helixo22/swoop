"""Browser integration: native messaging host and the Swoop extension.

Registers the host manifests that let only the Swoop extension start
swoop-native-host, builds the per-browser extension packages from the sources
shipped in this package (cookies are requested by the Firefox build only), and
opens them in the user's browsers for installation.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass
from importlib.metadata import version
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

from gi.repository import Gio

from swoop.desktop import desktop_app

HOST_NAME = "io.github.swoop"
HOST_EXECUTABLE = "swoop-native-host"
FIREFOX_EXTENSION_ID = "swoop@swoop.github.io"
CHROMIUM_EXTENSION_ID = "jnibaeahonigkhacgglkbbedmiiddccf"  # derived from CHROMIUM_PUBLIC_KEY
# Public half of the key that pins CHROMIUM_EXTENSION_ID; the private key is not in the repo.
CHROMIUM_PUBLIC_KEY = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwL+Wan4MZRaKwTBuuykrwSUV7qyp1vrkmPsvqhwHPFiv"
    "cIUfp7wtbOo72ULWN+XtH5GI8GmBNyIDdKwabxM1VWvsXEMmWGFgM/67+GX2WeqqvG8Y6k7ojdJ6nWSBm7AB5UEH"
    "w0fKUhZVWHUahLgqFcPSAE8eTKst25NVS+0trOJdyt+o02a46QGHZcOEppMuYSp+eWFhXvvOgYtAjPybqQASiekL"
    "XWoWtnJ9ZKF5HQ0p4+MlRXy/vUSRhDlRMSiN7Gktz1Le9UFpl9LjouoyWNRU6xyDwzLNcsaNKv8ZfLHzpkZUvOoW"
    "MSpLUFAxI9Wh4bZ1MZYDbAJFscOyVMGakwIDAQAB"
)
_PERMISSIONS = ["downloads", "nativeMessaging", "contextMenus"]


@dataclass(frozen=True)
class Browser:
    name: str
    profile_dir: str  # relative to the home directory
    manifest_dir: str  # where the native messaging host manifest goes, relative to home
    desktop_ids: tuple[str, ...]
    firefox: bool


BROWSERS = (
    Browser(
        "Firefox",
        ".mozilla",
        ".mozilla/native-messaging-hosts",
        ("firefox.desktop", "firefox-esr.desktop", "firefox-developer-edition.desktop"),
        firefox=True,
    ),
    Browser(
        "Chromium",
        ".config/chromium",
        ".config/chromium/NativeMessagingHosts",
        ("chromium.desktop", "chromium-browser.desktop"),
        firefox=False,
    ),
    Browser(
        "Google Chrome",
        ".config/google-chrome",
        ".config/google-chrome/NativeMessagingHosts",
        ("google-chrome.desktop", "google-chrome-stable.desktop"),
        firefox=False,
    ),
)


@dataclass(frozen=True)
class ExtensionBuild:
    firefox_package: Path  # .xpi, opened by Firefox's add-on installer
    chromium_dir: Path  # unpacked extension for "Load unpacked"


def installed_browsers(home: Path | None = None) -> list[Browser]:
    """The supported browsers that have a profile in the home directory."""
    home = home or Path.home()
    return [browser for browser in BROWSERS if (home / browser.profile_dir).is_dir()]


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
    for browser in installed_browsers(home):
        target = home / browser.manifest_dir / f"{HOST_NAME}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        manifest = host_manifest(host_path, firefox=browser.firefox)
        target.write_text(json.dumps(manifest, indent=2) + "\n")
        written.append(target)
    return written


def extension_manifest(firefox: bool) -> dict[str, Any]:
    base: dict[str, Any] = {
        "manifest_version": 3,
        "name": "Swoop",
        "version": version("swoop"),
        "description": "Hand browser downloads over to the Swoop download manager.",
        "icons": {size: f"icons/swoop-{size}.png" for size in ("16", "48", "128")},
    }
    if firefox:
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
    return base | {
        "permissions": _PERMISSIONS,
        "background": {"service_worker": "background.js"},
        "key": CHROMIUM_PUBLIC_KEY,
    }


def export_extension(target: Path) -> ExtensionBuild:
    """Write the Firefox package and the unpacked Chromium extension under target."""
    firefox_dir, chromium_dir = target / "firefox", target / "chromium"
    for directory, firefox in ((firefox_dir, True), (chromium_dir, False)):
        shutil.rmtree(directory, ignore_errors=True)
        with as_file(files("swoop") / "browser_extension") as sources:
            shutil.copytree(sources, directory)
        manifest = json.dumps(extension_manifest(firefox), indent=2) + "\n"
        (directory / "manifest.json").write_text(manifest)
    package = target / "swoop-firefox.xpi"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(firefox_dir.rglob("*")):
            archive.write(file, file.relative_to(firefox_dir))
    return ExtensionBuild(package, chromium_dir)


def open_extension_installer(browser: Browser, build: ExtensionBuild) -> None:
    """Firefox opens its add-on installer on the package; Chromium its extensions page."""
    app = next(filter(None, map(desktop_app, browser.desktop_ids)), None)
    if app is None:
        raise FileNotFoundError(f"{browser.name} is not installed as a desktop application")
    if browser.firefox:
        app.launch([Gio.File.new_for_path(str(build.firefox_package))], None)
    else:
        app.launch_uris(["chrome://extensions"], None)


def _find_host() -> Path:
    found = shutil.which(HOST_EXECUTABLE)
    if found is None:
        raise FileNotFoundError(f"{HOST_EXECUTABLE} is not on PATH; install Swoop first")
    return Path(found).resolve()
