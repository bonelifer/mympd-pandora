/* myMPD player controls for the local Pandora bridge. */
(() => {
    "use strict";
    const bridge = "http://127.0.0.1:18765";
    let track;
    let busy = false;
    let polling = false;

    function currentStation() {
        if (currentState.state !== "play" || !currentSongObj?.uri) {
            return null;
        }
        const prefix = bridge + "/stream/";
        const uri = currentSongObj.uri;
        const station = uri.startsWith(prefix) ? uri.slice(prefix.length) : "";
        return /^[a-zA-Z0-9_-]+$/.test(station) ? station : null;
    }

    async function request(station, action, id) {
        const query = new URLSearchParams({station});
        if (action) {
            query.set("action", action);
            query.set("track", id);
        }
        return proxy(query, Boolean(action));
    }

    async function proxy(query, post) {
        const path = subdir + "/script/" +
            encodeURIComponent(localSettings.partition) + "/PandoraControls?";
        const response = await fetch(path + query.toString().replaceAll("+", "%20"), {
            method: post ? "POST" : "GET",
            body: post ? "{}" : undefined,
            cache: "no-store",
            signal: AbortSignal.timeout(30000)
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || "Pandora control unavailable");
        }
        return result;
    }

    function element(tag, text, className) {
        const node = document.createElement(tag);
        if (text) node.textContent = text;
        if (className) node.className = className;
        return node;
    }

    function button(label, handler, className = "btn btn-secondary") {
        const control = element("button", label, className);
        control.type = "button";
        control.addEventListener("click", handler);
        return control;
    }

    async function openManager() {
        const dialog = element("dialog", "", "rounded p-3 text-bg-dark");
        dialog.style.maxWidth = "min(36rem, 95vw)";
        dialog.style.maxHeight = "85vh";
        const status = element("p", "", "small mb-2");
        status.setAttribute("role", "status");
        const content = element("div", "", "d-grid gap-2");
        dialog.append(element("h2", "Manage Pandora stations", "h5"),
            status, content, button("Close", () => dialog.close(), "btn btn-secondary mt-3"));
        dialog.addEventListener("close", () => dialog.remove());
        document.body.append(dialog);
        dialog.showModal();

        const stationPicker = element("select", "", "form-select");
        stationPicker.setAttribute("aria-label", "Pandora station");
        const actions = element("div", "", "d-flex flex-wrap gap-2");
        const details = element("div", "", "d-grid gap-2");
        const search = element("input", "", "form-control");
        search.placeholder = "Search for an artist or song";
        search.setAttribute("aria-label", search.placeholder);
        const searchResults = element("select", "", "form-select");
        searchResults.setAttribute("aria-label", "Pandora search results");
        searchResults.hidden = true;
        let token, stations = [];

        async function manage(action, data = {}) {
            const query = new URLSearchParams({
                manage: action, payload: JSON.stringify({...data, token})
            });
            return proxy(query, true);
        }

        function run(operation) {
            return async () => {
                content.inert = true;
                status.textContent = "";
                try {
                    await operation();
                } catch (error) {
                    status.textContent = error.message;
                } finally {
                    content.inert = false;
                }
            };
        }

        async function refreshStations() {
            const previous = stationPicker.value;
            stations = await manage("list");
            stationPicker.replaceChildren(...stations.map(
                item => new Option(item.name, item.id)
            ));
            if (stations.some(item => item.id === previous)) {
                stationPicker.value = previous;
            }
            await showStation();
        }

        async function showStation() {
            const station = stations.find(item => item.id === stationPicker.value);
            actions.replaceChildren();
            details.replaceChildren();
            if (!station) return;
            if (station.quickMix) {
                const selected = new Set(station.members);
                const checks = stations.filter(item => !item.quickMix).map(item => {
                    const check = element("input", "", "form-check-input me-2");
                    check.type = "checkbox";
                    check.value = item.id;
                    check.checked = selected.has(item.id);
                    const label = element("label", "", "form-check");
                    label.append(check, item.name);
                    details.append(label);
                    return check;
                });
                actions.append(button("Save QuickMix", run(async () => {
                    await manage("quickmix", {members: checks.filter(
                        check => check.checked
                    ).map(check => check.value)});
                    status.textContent = "QuickMix updated";
                })));
                return;
            }
            if (station.canRename) {
                actions.append(button("Rename", run(async () => {
                    const name = window.prompt("New Pandora station name", station.name);
                    if (!name?.trim() || name.trim() === station.name) return;
                    await manage("rename", {station: station.id, name});
                    await refreshStations();
                })));
            }
            if (station.canDelete) {
                actions.append(button("Delete station", run(async () => {
                    if (!window.confirm("Delete Pandora station “" + station.name + "”?")) return;
                    await manage("delete", {station: station.id});
                    await refreshStations();
                })));
            }
            const records = await manage("details", {station: station.id});
            for (const [items, heading, action] of [
                [records.seeds, "Seeds", "remove-seed"],
                [records.ratings, "Ratings", "remove-rating"]
            ]) {
                if (!items.length) continue;
                details.append(element("h3", heading, "h6 mt-2"));
                for (const record of items) {
                    const row = element("div", "", "d-flex gap-2 align-items-center");
                    const prefix = record.positive === undefined ? "" :
                        (record.positive ? "Thumbs up · " : "Thumbs down · ");
                    row.append(element("span", prefix + record.name),
                        button("Remove", run(async () => {
                            if (!window.confirm("Remove “" + record.name + "”?")) return;
                            await manage(action, {station: station.id, record: record.id});
                            await showStation();
                        }), "btn btn-sm btn-secondary"));
                    details.append(row);
                }
            }
        }

        content.append(stationPicker, actions, details,
            element("h3", "Find an artist or song", "h6 mt-2"), search,
            button("Search", run(async () => {
                const matches = await manage("search", {query: search.value});
                searchResults.replaceChildren(...matches.map(item => new Option(item.name, item.id)));
                searchResults.hidden = !matches.length;
                if (!matches.length) status.textContent = "No Pandora matches";
            })), searchResults,
            button("Create station from result", run(async () => {
                if (!searchResults.value) return;
                const result = await manage("create", {seed: searchResults.value});
                await refreshStations();
                status.textContent = "Created “" + result.name + "”";
            })),
            button("Add result as seed to selected station", run(async () => {
                const station = stations.find(item => item.id === stationPicker.value);
                if (!searchResults.value || !station?.canAddSeed) {
                    throw new Error("Select a result and a station that accepts seeds");
                }
                await manage("add-seed", {station: station.id, seed: searchResults.value});
                await showStation();
                status.textContent = "Seed added";
            }))
        );
        stationPicker.addEventListener("change", run(showStation));
        await run(async () => {
            ({token} = await proxy(new URLSearchParams({manage: "token"}), false));
            await refreshStations();
        })();
    }

    function initialize() {
        const next = document.getElementById("footerNextBtn");
        if (!next) {
            return;
        }
        const heart = document.createElement("button");
        heart.type = "button";
        heart.className = "btn px-2 mi rounded-2 d-none";
        heart.style.backgroundColor = "transparent";
        const thumbsDown = button("thumb_down", () => control("dislike"),
            "btn px-2 mi rounded-2 d-none");
        thumbsDown.title = "Thumbs down Pandora song";
        thumbsDown.setAttribute("aria-label", thumbsDown.title);
        const removeRating = button("heart_broken", () => {
            if (window.confirm("Remove the rating for this Pandora song?")) {
                control("remove-rating");
            }
        }, "btn px-2 mi rounded-2 d-none");
        removeRating.title = "Remove Pandora rating";
        removeRating.setAttribute("aria-label", removeRating.title);
        const songActions = button("more_horiz", openSongActions,
            "btn px-2 mi rounded-2 d-none");
        songActions.title = "Pandora song actions";
        songActions.setAttribute("aria-label", songActions.title);
        const manager = button("tune", openManager, "btn px-2 mi rounded-2");
        manager.title = "Manage Pandora stations";
        manager.setAttribute("aria-label", manager.title);
        next.after(heart, thumbsDown, removeRating, songActions, manager);

        function openSongActions() {
            const dialog = element("dialog", "", "rounded p-3 text-bg-dark");
            const actions = element("div", "", "d-grid gap-2");
            for (const [label, action] of [
                ["I’m tired of this song", "tired"],
                ["Why this song?", "explain"], ["Create station from song", "create"]
            ]) {
                actions.append(button(label, () => {
                    dialog.close();
                    control(action);
                }));
            }
            actions.append(button("Close", () => dialog.close()));
            dialog.append(element("h2", "Pandora song actions", "h5"), actions);
            dialog.addEventListener("close", () => dialog.remove());
            document.body.append(dialog);
            dialog.showModal();
        }

        const updateNativeControls = updatePlaybackControls;
        let hadPandoraControls = false;

        function renderMetadata(station) {
            if (!station || track?.station !== station ||
                track?.title !== currentSongObj?.Title) {
                return;
            }
            for (const [selector, value] of [
                ["#PlaybackTitle", track.song],
                ["#currentArtist p", track.artist],
                ["#currentAlbum p", track.album]
            ]) {
                const field = document.querySelector(selector);
                if (field && typeof value === "string" && value &&
                    field.textContent !== value) {
                    field.textContent = value;
                }
            }
        }

        function render() {
            const station = currentStation();
            renderMetadata(station);
            if (station) {
                const canSkip = !busy && track?.station === station &&
                    track.title === currentSongObj?.Title && track.canSkip;
                for (const button of document.querySelectorAll(
                    "#footerNextBtn, #popoverFooterNextBtn"
                )) {
                    button.disabled = !canSkip;
                }
            } else if (hadPandoraControls) {
                updateNativeControls();
            }
            hadPandoraControls = Boolean(station);
            const loved = Boolean(track?.loved);
            heart.classList.toggle("d-none", !station);
            thumbsDown.classList.toggle("d-none", !station);
            thumbsDown.disabled = busy || !track?.canLove;
            for (const button of [removeRating, songActions]) {
                button.classList.toggle("d-none", !station);
                button.disabled = busy || !track?.songActions;
            }
            heart.disabled = busy || !track?.canLove;
            heart.textContent = loved ? "favorite" : "favorite_border";
            heart.style.color = loved ? "#e53935" : "inherit";
            heart.setAttribute("aria-pressed", String(loved));
            heart.setAttribute("aria-label", "Love Pandora song");
            heart.title = loved ? "Unlove Pandora song" : "Love Pandora song";
        }

        async function refresh() {
            if (polling || busy) {
                return;
            }
            const station = currentStation();
            if (!station || track?.station !== station ||
                track?.title !== currentSongObj?.Title) {
                track = null;
            }
            render();
            if (!station) {
                return;
            }
            polling = true;
            try {
                const result = await request(station);
                if (!busy && station === currentStation() &&
                    result.title === currentSongObj?.Title) {
                    track = {...result, station};
                }
            } catch {
                if (!busy) {
                    track = null;
                }
            } finally {
                polling = false;
                render();
            }
        }

        async function control(action) {
            const station = currentStation();
            if (busy) {
                return;
            }
            if (track?.station !== station || track?.title !== currentSongObj?.Title ||
                !(action === "skip" ? track.canSkip :
                    ["love", "unlove"].includes(action) ? track.canLove :
                    action === "dislike" ? track.canLove : track.songActions)) {
                showNotification("Pandora control unavailable for this track", "Pandora", "warn");
                return;
            }
            const id = track.id;
            busy = true;
            render();
            try {
                const result = await request(station, action, id);
                track = {...result, station};
                if (result.explanation) {
                    const reasons = result.explanation.explanations || [];
                    const text = reasons.map(item => item.focusTraitName || item.explanation)
                        .filter(Boolean).join("\n");
                    window.alert(text || "Pandora did not provide an explanation.");
                }
                if (result.created) {
                    showNotification("Created Pandora station “" + result.created + "”",
                        "Pandora", "notice");
                }
            } catch (error) {
                showNotification(error.message, "Pandora", "error");
                track = null;
            } finally {
                busy = false;
                render();
            }
        }

        updatePlaybackControls = function () {
            updateNativeControls();
            render();
        };

        heart.addEventListener("click", () => control(track?.loved ? "unlove" : "love"));
        document.addEventListener("click", (event) => {
            if (!event.target.closest("#footerNextBtn, #popoverFooterNextBtn") ||
                !currentStation()) {
                return;
            }
            event.preventDefault();
            event.stopImmediatePropagation();
            control("skip");
        }, true);
        refresh();
        window.setInterval(refresh, 1500);
    }

    if (document.readyState === "loading") {
        window.addEventListener("DOMContentLoaded", initialize, {once: true});
    } else {
        initialize();
    }
})();
