#!/usr/bin/env python3
"""Copy Pandora artwork into myMPD's stream thumbnail directory."""

import argparse
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

MAX_IMAGE_BYTES = 5 * 1024 * 1024


def save_artwork(url, filename):
    """Download a bounded JPEG or PNG and atomically publish its bytes."""
    with urlopen(url, timeout=10) as response:
        if urlsplit(response.url).scheme != "https":
            raise ValueError("Artwork must use HTTPS")
        data = response.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Artwork exceeds the size limit")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        extension = ".png"
    elif data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        extension = ".jpg"
    else:
        raise ValueError("Artwork is not a JPEG or PNG")
    with NamedTemporaryFile(dir=filename.parent, delete=False) as temporary:
        path = Path(temporary.name)
        try:
            temporary.write(data)
            temporary.close()
            path.chmod(0o644)
            os.replace(path, filename.with_suffix(extension))
        finally:
            path.unlink(missing_ok=True)
    for suffix in {".png", ".jpg"} - {extension}:
        filename.with_suffix(suffix).unlink(missing_ok=True)


def main():
    """Refresh station images from the bridge and report missing artwork."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True)
    parser.add_argument("--thumbs", required=True, type=Path)
    args = parser.parse_args()
    base = args.service.rstrip("/")
    with urlopen(base + "/stations", timeout=35) as response:
        stations = json.load(response)
    saved = missing = failed = 0
    for station in stations:
        station_id = str(station["id"])
        if not re.fullmatch(r"[A-Za-z0-9_-]+", station_id):
            failed += 1
            continue
        uri = f"{base}/stream/{station_id}"
        # Match the filename myMPD derives from the stream URI.
        filename = args.thumbs / re.sub(r"[^A-Za-z0-9]", "_", uri)
        url = station.get("artUrl")
        if not url:
            for suffix in (".png", ".jpg"):
                filename.with_suffix(suffix).unlink(missing_ok=True)
            missing += 1
            continue
        try:
            if urlsplit(url).scheme != "https":
                raise ValueError("Artwork must use HTTPS")
            save_artwork(url, filename)
            saved += 1
        except (OSError, URLError, ValueError) as error:
            print(f"Could not save artwork for station {station_id}: {error}")
            failed += 1
    print(f"Saved {saved} images, {missing} without artwork, {failed} failed")
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(main())
