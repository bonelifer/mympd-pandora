"""Pandora station operations for the myMPD management dialog."""


def required_text(data, key, maximum=256):
    """Get a nonempty, bounded string from a management request."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Invalid {key}")
    return value.strip()


def station_details(station):
    """Expose editable seeds and ratings by their Pandora record IDs."""
    seeds = station.seeds
    feedback = station.feedback
    return {
        "seeds": [
            {"id": seed.seed_id,
             "name": seed.song_name or seed.artist_name or seed.genre_name}
            for group in ("songs", "artists", "genres")
            for seed in getattr(seeds, group, []) or []
            if seed.seed_id
        ],
        "ratings": [
            {"id": item.feedback_id,
             "name": " — ".join(filter(None, (item.artist_name, item.song_name))),
             "positive": positive}
            for group, positive in (("thumbs_up", True), ("thumbs_down", False))
            for item in getattr(feedback, group, []) or []
            if item.feedback_id
        ],
    }


def manage(client, action, data):
    """Dispatch a validated request using Pydora's station APIs."""
    if action == "search":
        results = client.search(required_text(data, "query"))
        return [
            {"id": item.token, "name": " — ".join(filter(
                None, (item.artist, getattr(item, "song_name", None))
            ))}
            for item in (results.artists or []) + (results.songs or [])
            if item.token
        ][:100]
    if action == "create":
        station = client.create_station(search_token=required_text(data, "seed"))
        return {"name": station.name}

    stations = {station.id: station for station in client.get_station_list()}
    if action == "list":
        return [{
            "id": item.id, "name": item.name, "quickMix": bool(item.is_quickmix),
            "members": item.quickmix_stations or [],
            "canRename": bool(item.can_rename), "canDelete": bool(item.can_delete),
            "canAddSeed": bool(item.can_add_music),
        } for item in stations.values()]
    if action == "quickmix":
        members = data.get("members")
        if not isinstance(members, list) or any(
            not isinstance(key, str) or key not in stations or
            stations[key].is_quickmix for key in members
        ):
            raise ValueError("Invalid QuickMix membership")
        client.set_quick_mix(*dict.fromkeys(members))
        return {}

    station = stations.get(required_text(data, "station"))
    if station is None:
        raise ValueError("Pandora station no longer exists")
    if action == "details":
        return station_details(client.get_station(station.token))
    if action == "rename" and station.can_rename:
        client.rename_station(station.token, required_text(data, "name"))
    elif action == "delete" and station.can_delete:
        client.delete_station(station.token)
    elif action == "add-seed" and station.can_add_music:
        client.add_music(required_text(data, "seed"), station.token)
    elif action in {"remove-seed", "remove-rating"}:
        details = station_details(client.get_station(station.token))
        record = required_text(data, "record")
        if action == "remove-seed" and record in {item["id"] for item in details["seeds"]}:
            client.delete_music(record)
        elif action == "remove-rating" and record in {item["id"] for item in details["ratings"]}:
            client.delete_feedback(record)
        else:
            raise ValueError("Pandora record no longer exists on this station")
    else:
        raise ValueError("Pandora station action is unavailable")
    return {}
