/* Load the player controls outside myMPD's custom_js size limit. */
(() => {
    const script = document.createElement("script");
    const base = new URL(".", document.currentScript.src);
    const url = new URL("browse/pics/pandora-controls-v5.js", base).href;
    const policy = window.trustedTypes?.createPolicy("pandora-player", {
        createScriptURL(candidate) {
            if (candidate !== url) {
                throw new TypeError("Unexpected Pandora script URL");
            }
            return url;
        }
    });
    script.src = policy ? policy.createScriptURL(url) : url;
    document.head.append(script);
})();
