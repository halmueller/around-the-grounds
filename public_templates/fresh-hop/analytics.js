// Seattle Freshies: loads TelemetryDeck when the server has configured it.
// The app ID lives in analytics-config.js, which is not in the repo and not
// produced by the build: it sits only in the web root (see
// deploy/digitalocean/analytics-config.example.js), so publishes leave it
// alone. Without that file, or with the ID left blank, nothing is loaded.
(function () {
    const config = window.FRESHIES_ANALYTICS || {};

    function addScript(src, attributes) {
        const script = document.createElement('script');
        script.async = true;
        script.src = src;
        Object.assign(script.dataset, attributes || {});
        document.head.appendChild(script);
    }

    // TelemetryDeck's web SDK reads its app ID from its own script tag and
    // sends one signal per page view.
    if (config.telemetryDeckAppId) {
        addScript('https://cdn.telemetrydeck.com/websdk/telemetrydeck.min.js', {
            appId: config.telemetryDeckAppId,
            isTestMode: config.telemetryDeckTestMode ? 'true' : 'false',
        });
    }
})();
