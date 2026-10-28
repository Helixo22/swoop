"""Browser integration: native messaging host and the Swoop extension.

Registers the host manifests that let only the Swoop extension start
swoop-native-host, builds the per-browser extension packages from the sources
shipped in this package (cookies are requested by the Firefox build only), and
opens them in the user's browsers for installation.
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from dataclasses import dataclass
from importlib.metadata import version
from importlib.resources import as_file, files
from importlib.resources.abc import Traversable
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
# Drop a package signed on addons.mozilla.org here to make Firefox installs permanent.
SIGNED_FIREFOX_PACKAGE = "swoop-firefox-signed.xpi"


@dataclass(frozen=True)
class Browser:
    name: str
    roots: tuple[str, ...]  # configuration directories that reveal the browser, relative to home
    manifest_dirs: tuple[str, ...]  # where it looks for native messaging hosts, relative to home
    desktop_ids: tuple[str, ...]
    firefox: bool
    # A Flatpak browser cannot start programs outside its sandbox, so its
    # extension could never reach swoop-native-host.
    sandboxed: bool = False


# Firefox-based browsers read host manifests from ~/.mozilla/native-messaging-hosts even
# when their profiles live elsewhere (verified with Zen 1.23, which ignores its own dirs).
_MOZILLA_HOSTS = ".mozilla/native-messaging-hosts"

BROWSERS = (
    Browser(
        "Firefox",
        # Firefox 147+ follows the XDG base directories; older releases use ~/.mozilla.
        (".config/mozilla", ".mozilla"),
        (_MOZILLA_HOSTS, ".config/mozilla/native-messaging-hosts"),
        ("firefox.desktop", "firefox-esr.desktop", "firefox-developer-edition.desktop"),
        firefox=True,
    ),
    Browser(
        "Zen",
        (".config/zen", ".zen"),
        (_MOZILLA_HOSTS,),
        ("zen.desktop", "zen-browser.desktop"),
        firefox=True,
    ),
    Browser(
        "LibreWolf",
        (".librewolf", ".config/librewolf"),
        (_MOZILLA_HOSTS, ".librewolf/native-messaging-hosts"),
        ("librewolf.desktop", "io.gitlab.librewolf-community.desktop"),
        firefox=True,
    ),
    Browser(
        "Zen (Flatpak)",
        (".var/app/app.zen_browser.zen/.zen",),
        (),
        ("app.zen_browser.zen.desktop",),
        firefox=True,
        sandboxed=True,
    ),
    Browser(
        "Firefox (Flatpak)",
        (".var/app/org.mozilla.firefox/.mozilla",),
        (),
        ("org.mozilla.firefox.desktop",),
        firefox=True,
        sandboxed=True,
    ),
    Browser(
        "Chromium",
        (".config/chromium",),
        (".config/chromium/NativeMessagingHosts",),
        ("chromium.desktop", "chromium-browser.desktop"),
        firefox=False,
    ),
    Browser(
        "Google Chrome",
        (".config/google-chrome",),
        (".config/google-chrome/NativeMessagingHosts",),
        ("google-chrome.desktop", "google-chrome-stable.desktop"),
        firefox=False,
    ),
)


@dataclass(frozen=True)
class ExtensionBuild:
    firefox_package: Path  # .xpi for the add-on installer
    firefox_signed: bool  # only a Mozilla-signed package installs permanently in Firefox
    firefox_dir: Path  # unpacked, for about:debugging's "Load Temporary Add-on"
    chromium_dir: Path  # unpacked, for "Load unpacked"


def installed_browsers(home: Path | None = None) -> list[Browser]:
    """The supported browsers that have a configuration directory in the home directory."""
    home = home or Path.home()
    return [browser for browser in BROWSERS if _has_root(browser, home) and _present(browser)]


def _has_root(browser: Browser, home: Path) -> bool:
    return any((home / root).is_dir() for root in browser.roots)


def _present(browser: Browser) -> bool:
    """A Flatpak keeps its data after uninstalling, so also require the app itself."""
    return not browser.sandboxed or any(map(desktop_app, browser.desktop_ids))


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
    """Write the host manifest wherever an installed browser looks for it; return the paths."""
    home = home or Path.home()
    host_path = host_path or _find_host()
    targets = {
        home / directory / f"{HOST_NAME}.json": browser.firefox
        for browser in installed_browsers(home)
        for directory in browser.manifest_dirs
    }
    for target, firefox in targets.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(host_manifest(host_path, firefox=firefox), indent=2) + "\n")
    return list(targets)


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
    signed = has_signed_firefox_package()
    if signed:
        package.write_bytes(_signed_firefox_package().read_bytes())
    else:
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(firefox_dir.rglob("*")):
                archive.write(file, file.relative_to(firefox_dir))
    return ExtensionBuild(package, signed, firefox_dir, chromium_dir)


def open_extension_installer(browser: Browser, build: ExtensionBuild) -> None:
    """Open the browser where the extension gets installed.

    A Mozilla-signed package goes to Firefox's add-on installer. Unsigned builds
    are refused there ("not verified"), so Firefox-based browsers open
    about:debugging to load the folder instead; Chromium opens its extensions page.
    """
    app = next(filter(None, map(desktop_app, browser.desktop_ids)), None)
    if app is None:
        raise FileNotFoundError(f"{browser.name} is not installed as a desktop application")
    if browser.firefox and build.firefox_signed:
        app.launch([Gio.File.new_for_path(str(build.firefox_package))], None)
    elif browser.firefox:
        app.launch_uris(["about:debugging#/runtime/this-firefox"], None)
    else:
        app.launch_uris(["chrome://extensions"], None)


def unpacked_dir(browser: Browser, build: ExtensionBuild) -> Path | None:
    """The folder the user must pick in the browser, or None when nothing is to pick."""
    if not browser.firefox:
        return build.chromium_dir
    return None if build.firefox_signed else build.firefox_dir


def has_signed_firefox_package() -> bool:
    return _signed_firefox_package().is_file()


def _signed_firefox_package() -> Traversable:
    return files("swoop") / "data" / SIGNED_FIREFOX_PACKAGE


def _find_host() -> Path:
    """The host installed next to the running interpreter (virtualenv, pipx), else on PATH."""
    beside = Path(sys.executable).parent / HOST_EXECUTABLE
    if beside.is_file():
        return beside
    found = shutil.which(HOST_EXECUTABLE)
    if found is None:
        raise FileNotFoundError(f"{HOST_EXECUTABLE} is not installed; install Swoop first")
    return Path(found).resolve()
