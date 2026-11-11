#!/usr/bin/env python3
"""Install the Pandora station picker using myMPD's protected JSON-RPC API."""

import argparse
import json
import os
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


def main():
    """Submit the bundled Lua script to the selected myMPD partition."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mympd", required=True, help="myMPD base URL")
    parser.add_argument("--partition", default="default")
    parser.add_argument("--service", default="http://pandora:8080",
                        help="Bridge URL reachable from myMPD and MPD")
    parser.add_argument("--controls", action="store_true",
                        help="Install the player controls proxy")
    parser.add_argument("--replace", action="store_true",
                        help="Replace the installed script of the same name")
    args = parser.parse_args()
    for url in (args.mympd, args.service):
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.query or parsed.fragment
                or not url.isascii() or any(ord(char) <= 32 for char in url)):
            parser.error("URLs must be HTTP(S) without credentials or queries")

    filename = "pandora-controls.lua" if args.controls else "pandora.lua"
    default_service = ("http://127.0.0.1:18765" if args.controls
                       else "http://pandora:8080")
    metadata_line, _, source = Path(__file__).with_name(filename).read_text(
        encoding="utf-8"
    ).partition("\n")
    metadata = json.loads(metadata_line.removeprefix("-- "))
    source = source.replace(
        json.dumps(default_service), json.dumps(args.service.rstrip("/")), 1
    )
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "MYMPD_API_SCRIPT_SAVE",
        "params": {
            "script": metadata["name"],
            "oldscript": metadata["name"] if args.replace else "",
            "file": metadata["file"],
            "version": metadata["version"],
            "order": metadata["order"],
            "arguments": metadata["arguments"],
            "content": source,
        },
    }
    headers = {"Content-Type": "application/json"}
    if session := os.environ.get("MYMPD_SESSION"):
        headers["X-myMPD-Session"] = session
    endpoint = args.mympd.rstrip("/") + "/api/" + quote(args.partition, safe="")
    request = Request(endpoint, json.dumps(payload).encode(), headers)
    try:
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
    except (URLError, TimeoutError, ValueError) as error:
        parser.exit(1, f"myMPD request failed: {error}\n")
    if "result" not in result or "error" in result:
        parser.exit(1, f"myMPD rejected the script: {result.get('error')}\n")
    print(f"Installed {metadata['name']} in myMPD.")


if __name__ == "__main__":
    main()
