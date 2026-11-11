#!/usr/bin/env python3
"""Serve Pandora stations as continuous MP3 streams for MPD."""

import argparse
import json
import logging
import os
import shutil
from secrets import compare_digest, token_urlsafe
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import BoundedSemaphore, Event, Lock
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from pandora.client import APIClient
from pandora.clientbuilder import PydoraConfigFileBuilder

from station_management import manage

STREAM_SLOTS = BoundedSemaphore(2)
API_SLOTS = BoundedSemaphore(4)
MANAGEMENT_TOKEN = token_urlsafe(32)


ACTIVE_TRACKS = {}
TRACK_LOCK = Lock()


class PandoraClient(APIClient):
    """Retain the song identity omitted by Pydora's playlist model."""

    def __call__(self, method, **kwargs):
        result = super().__call__(method, **kwargs)
        if method == "station.getPlaylist":
            self.song_identities = {
                item["trackToken"]: item.get("songIdentity")
                for item in result["items"] if item.get("trackToken")
            }
        return result


class ActiveTrack:
    """Identify one playback instance and its allowed controls."""

    def __init__(self, track, station, title):
        self.track = track
        self.station = station
        self.title = title
        self.id = uuid4().hex
        self.skip = Event()
        self.feedback_id = None
        self.rating = getattr(track, "song_rating", None)

    def status(self):
        """Return controls and rating without exposing Pandora tokens."""
        return {
            "id": self.id, "title": self.title,
            "canSkip": not self.track.is_ad and not self.skip.is_set(),
            "canLove": bool(getattr(self.track, "allow_feedback", False))
            and self.rating in (0, 1) and not self.skip.is_set(),
            "loved": self.rating == 1,
            "songActions": bool(getattr(self.track, "track_token", None))
            and not self.track.is_ad and not self.skip.is_set(),
        }

    def song_action(self, action):
        """Run an action for the exact current track."""
        if not self.status()["songActions"]:
            raise ValueError("Pandora song action is unavailable")
        track = self.track
        client = track._api_client
        if action == "dislike":
            if not getattr(track, "allow_feedback", False):
                raise ValueError("Pandora feedback is unavailable for this track")
            track.thumbs_down()
            self.rating = None
            self.skip.set()
        elif action == "tired":
            track.sleep()
            self.skip.set()
        elif action == "remove-rating":
            feedback_id = self.feedback_id or self.find_feedback(
                ("thumbs_up", "thumbs_down")
            )
            client.delete_feedback(feedback_id)
            self.feedback_id = None
            self.rating = 0
        elif action == "explain":
            return {"explanation": client.explain_track(track.track_token)}
        elif action == "create":
            station = client.create_station(track_token=track.track_token)
            return {"created": station.name}
        return {}


    def set_loved(self, loved):
        """Apply or remove feedback for this exact song."""
        if not self.status()["canLove"]:
            raise ValueError("Pandora feedback is unavailable for this track")
        if loved == (self.rating == 1):
            return
        track = self.track
        if loved:
            feedback = track.thumbs_up()
            self.feedback_id = feedback.get("feedbackId")
        else:
            client = track._api_client
            feedback_id = self.feedback_id
            if not feedback_id:
                feedback_id = self.find_feedback(("thumbs_up",))
            client.delete_feedback(feedback_id)
            self.feedback_id = None
        self.rating = int(loved)


    def find_feedback(self, groups):
        """Find a unique rating for the current song on its source station."""
        track = self.track
        client = track._api_client
        identity = client.song_identities.get(track.track_token)
        if not identity:
            raise ValueError("Pandora did not provide a song identity")
        station = self.station
        if track.station_id and track.station_id != station.id:
            station = client.get_station_list()[track.station_id]
        feedback = client.get_station(station.token).feedback
        matches = [
            item.feedback_id for group in groups
            for item in getattr(feedback, group, ()) or ()
            if item.song_identity == identity and item.feedback_id
        ]
        if len(matches) != 1:
            raise ValueError("Could not identify a unique Pandora rating")
        return matches[0]


def pandora_client():
    """Build a client from the mounted config and authenticate with timeouts."""
    builder = PydoraConfigFileBuilder(os.environ.get("PYDORA_CFG"),
                                     authenticate=False, client_class=PandoraClient)
    config = builder.parse_config()
    client = builder.build_from_settings_dict(config)
    session = client.transport._http
    request = session.request

    def timed_request(*args, **kwargs):
        kwargs.setdefault("timeout", (5, 15))
        return request(*args, **kwargs)

    session.request = timed_request
    client.login(config["USER"]["USERNAME"], config["USER"]["PASSWORD"])
    return client


ICY_INTERVAL = 8192


class IcyStream:
    """Insert metadata blocks at fixed audio byte intervals."""

    def __init__(self, output):
        self.output = output
        self.remaining = ICY_INTERVAL
        self.title = ""
        self.sent_title = None

    def write(self, audio):
        """Write audio, adding the current title when it changes."""
        while audio:
            chunk = audio[:self.remaining]
            self.output.write(chunk)
            self.remaining -= len(chunk)
            audio = audio[len(chunk):]
            if not self.remaining:
                self.write_metadata()
                self.remaining = ICY_INTERVAL

    def write_metadata(self):
        """Write one padded ICY metadata block or a zero-length marker."""
        if self.title == self.sent_title:
            self.output.write(b"\0")
            return
        title = self.title.replace("';", "’؛").replace("\0", "")
        title = title.encode("utf-8")[:4065].decode("utf-8", "ignore")
        payload = f"StreamTitle='{title}';".encode("utf-8")
        blocks = (len(payload) + 15) // 16
        self.output.write(bytes([blocks]) + payload.ljust(blocks * 16, b"\0"))
        self.sent_title = self.title


def stream_track(url, output, skip):
    """Transcode one HTTP audio track and write MP3 frames to the listener."""
    if not url or urlsplit(url).scheme not in {"http", "https"}:
        return False
    command = [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-protocol_whitelist", "http,https,tcp,tls",
        "-rw_timeout", "15000000", "-re", "-i", url,
        "-map", "0:a:0", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame",
        "-b:a", "128k", "-f", "mp3", "-write_xing", "0",
        "-id3v2_version", "0", "pipe:1",
    ]
    with subprocess.Popen(command, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL) as process:
        try:
            while chunk := process.stdout.read1(4096):
                if skip.is_set():
                    return True
                output.write(chunk)
            return process.wait() == 0
        finally:
            if process.poll() is None:
                process.kill()


class StationHandler(BaseHTTPRequestHandler):
    """List saved stations and stream one station by ID."""

    def do_GET(self):
        """Handle a station list or stream request."""
        self.connection.settimeout(15)
        path = urlsplit(self.path).path
        if path == "/stations":
            self.list_stations()
        elif path.startswith("/stream/"):
            self.play_station(unquote(path.removeprefix("/stream/")))
        elif path == "/manage":
            self.send_json({"token": MANAGEMENT_TOKEN})
        elif path.startswith("/controls/"):
            self.controls(path.removeprefix("/controls/"))
        else:
            self.send_error(404)

    def do_POST(self):
        """Apply a control to the playback instance identified by its nonce."""
        self.connection.settimeout(15)
        target = urlsplit(self.path)
        if target.path.startswith("/manage/"):
            self.manage_station(target.path.removeprefix("/manage/"))
            return
        station, separator, action = target.path.removeprefix("/controls/").partition("/")
        if not target.path.startswith("/controls/") or not separator:
            self.send_error(404)
            return
        nonce = parse_qs(target.query).get("track", [""])[0]
        self.controls(station, action, nonce)

    def send_json(self, payload, status=200):
        """Send an uncached JSON response."""
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def manage_station(self, action):
        """Run a management action with a same-origin capability."""
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16384:
                raise ValueError("Invalid management request size")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Invalid management request")
            token = data.pop("token", "")
            if not isinstance(token, str) or not compare_digest(
                token.encode(), MANAGEMENT_TOKEN.encode()
            ):
                self.send_json({"error": "Pandora management session expired"}, 403)
                return
            if not API_SLOTS.acquire(blocking=False):
                self.send_json({"error": "Pandora service busy"}, 503)
                return
            try:
                result = manage(pandora_client(), action, data)
            finally:
                API_SLOTS.release()
            self.send_json(result)
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)
        except Exception as error:
            logging.warning("Pandora management failed (%s)", type(error).__name__)
            self.send_json({"error": "Pandora rejected the station action"}, 502)

    def controls(self, station_id, action=None, nonce=None):
        """Read or change the sole active playback of a station."""
        with TRACK_LOCK:
            tracks = ACTIVE_TRACKS.get(station_id, {})
            active = next(iter(tracks.values())) if len(tracks) == 1 else None
            if active is None or (action and active.id != nonce):
                result, status = {"error": "Pandora track changed or is unavailable"}, 409
            else:
                try:
                    extra = {}
                    if action == "skip" and active.status()["canSkip"]:
                        active.skip.set()
                    elif action in {"love", "unlove"}:
                        active.set_loved(action == "love")
                    elif action in {"dislike", "tired", "explain", "create", "remove-rating"}:
                        extra = active.song_action(action)
                    elif action is not None:
                        raise ValueError("Pandora control is unavailable")
                    result, status = {**active.status(), **extra}, 200
                except ValueError as error:
                    result, status = {"error": str(error)}, 409
                except Exception as error:
                    logging.warning("Pandora control failed (%s)", type(error).__name__)
                    result, status = {"error": "Pandora feedback failed"}, 502
        self.send_json(result, status)

    def list_stations(self):
        """Return a JSON array of station IDs and names."""
        if not API_SLOTS.acquire(blocking=False):
            self.send_error(503, "Pandora service busy")
            return
        try:
            stations = pandora_client().get_station_list()
            payload = [
                {"id": station.id, "name": station.name, "artUrl": station.art_url}
                for station in stations
            ]
        except Exception as error:
            logging.error("Station lookup failed (%s)", type(error).__name__)
            self.send_error(502, "Pandora station lookup failed")
            return
        finally:
            API_SLOTS.release()
        self.send_json(payload)

    def play_station(self, station_id):
        """Serve fresh playlists over a single connection until playback ends."""
        if not STREAM_SLOTS.acquire(blocking=False):
            self.send_error(503, "Pandora stream limit reached")
            return
        started = False
        try:
            stations = pandora_client().get_station_list()
            station = next((item for item in stations if item.id == station_id),
                           None)
            if station is None:
                self.send_error(404, "Unknown station")
                return
            tracks = list(station.get_playlist())
            if not tracks:
                self.send_error(502, "Pandora returned an empty playlist")
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            # MPD exposes icy-name as Name, myMPD's fallback for Title.
            name = " ".join(station.name.split())
            self.send_header("icy-name", name.encode("utf-8").decode("latin-1"))
            self.send_header("Cache-Control", "no-store")
            output = self.wfile
            if self.headers.get("Icy-MetaData") == "1":
                self.send_header("icy-metaint", str(ICY_INTERVAL))
                output = IcyStream(self.wfile)
            self.end_headers()
            started = True
            while tracks:
                for track in tracks:
                    fields = (getattr(track, "artist_name", None),
                              getattr(track, "song_name", None))
                    title = " — ".join(filter(None, fields)) or name
                    if isinstance(output, IcyStream):
                        output.title = title
                    active = ActiveTrack(track, station, title)
                    with TRACK_LOCK:
                        ACTIVE_TRACKS.setdefault(station_id, {})[active.id] = active
                    try:
                        if not stream_track(track.audio_url, output, active.skip):
                            logging.warning("Could not stream a Pandora track")
                            return
                    finally:
                        with TRACK_LOCK:
                            del ACTIVE_TRACKS[station_id][active.id]
                            if not ACTIVE_TRACKS[station_id]:
                                del ACTIVE_TRACKS[station_id]
                tracks = list(station.get_playlist())
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception as error:
            logging.error("Station stream failed (%s)", type(error).__name__)
            if not started:
                self.send_error(502, "Pandora stream failed")
        finally:
            STREAM_SLOTS.release()


def main():
    """Start the bridge with an explicitly selected listen address."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", required=True, help="HTTP listen address")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    args = parser.parse_args()
    if not shutil.which("ffmpeg"):
        parser.error("ffmpeg must be installed")
    with ThreadingHTTPServer((args.listen, args.port), StationHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
