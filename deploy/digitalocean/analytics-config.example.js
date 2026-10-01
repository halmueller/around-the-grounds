// Analytics settings for seattlefreshies.com. Copy to the web root and fill in:
//   cp ~/around-the-grounds/deploy/digitalocean/analytics-config.example.js \
//       /var/www/seattlefreshies.com/analytics-config.js
// The build never writes this file, so hourly publishes leave your copy
// alone. Leave the app ID blank to turn analytics off.
//
// Without this file the site still works and loads no analytics, but every
// page view requests it and gets a 404 (a line in Apache's access log and a
// harmless message in the browser console). To turn analytics off without
// the 404s, install this file with the app ID left blank.
window.FRESHIES_ANALYTICS = {
    // TelemetryDeck app ID (a UUID, from the app's settings in the dashboard).
    telemetryDeckAppId: '',
    // true sends signals as test data, kept apart from real traffic.
    telemetryDeckTestMode: false,
};
