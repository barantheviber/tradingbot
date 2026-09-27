// Adds the release version to app.json at build time. CI sets APP_VERSION (e.g. 0.2.0) and
// APP_VERSION_CODE (a number that grows with every build) so a newer APK installs over an
// older one and keeps the bot's data.
module.exports = ({ config }) => ({
  ...config,
  version: process.env.APP_VERSION || config.version,
  android: {
    ...config.android,
    versionCode: Number(process.env.APP_VERSION_CODE || config.android?.versionCode || 1),
  },
});
