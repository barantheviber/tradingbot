// Expo config plugin: turns the prebuilt Android project into one that runs the Python bot on
// the phone. Applied by `npx expo prebuild` (see app.json "plugins").
//
// - Chaquopy (Python for Android) bundles the bot's modules (repo root, api/, execution/,
//   local_runtime.py, packaging/android/android_runtime.py) and the packages in
//   packaging/android/requirements-android.txt.
// - BotService (plugins/bot-runtime/BotService.kt) runs it as a foreground service;
//   BootReceiver.kt starts it again after a phone restart or app update if it was running.
// - Cleartext HTTP is allowed only to 127.0.0.1, where the phone's own API listens.
// - Release builds are signed with the keystore named by ANDROID_KEYSTORE_* environment
//   variables when they are set (CI release builds), otherwise with the debug key.
// - ANDROID_ABIS picks the CPU types to build for (comma separated). Phones are arm64-v8a;
//   x86_64 is for emulators. CI builds arm64-v8a only, which roughly halves the APK.
const fs = require('fs');
const path = require('path');
const {
  withAndroidManifest,
  withAppBuildGradle,
  withDangerousMod,
  withProjectBuildGradle,
} = require('expo/config-plugins');

const CHAQUOPY_VERSION = '17.0.0';
const ABIS = (process.env.ANDROID_ABIS || 'arm64-v8a,x86_64')
  .split(',')
  .map((a) => a.trim())
  .filter((a) => /^(arm64-v8a|armeabi-v7a|x86_64|x86)$/.test(a));
const PYTHON_VERSION = '3.12';
const PACKAGE_PATH = 'com/barantheviber/tradingbot';

const BOT_MODULES = [
  'bot_engine.py', 'config.py', 'exchange_client.py', 'local_runtime.py', 'logging_setup.py',
  'main.py', 'performance.py', 'risk_manager.py', 'state_manager.py', 'strategy.py',
];
const BOT_PACKAGES = ['api', 'execution'];

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (entry.name === '__pycache__') continue;
    const from = path.join(src, entry.name);
    const to = path.join(dest, entry.name);
    if (entry.isDirectory()) copyDir(from, to);
    else if (entry.name.endsWith('.py')) fs.copyFileSync(from, to);
  }
}

function withChaquopyGradle(config) {
  config = withProjectBuildGradle(config, (cfg) => {
    const line = `classpath('com.chaquo.python:gradle:${CHAQUOPY_VERSION}')`;
    if (!cfg.modResults.contents.includes('com.chaquo.python:gradle')) {
      cfg.modResults.contents = cfg.modResults.contents.replace(
        /(buildscript\s*\{[\s\S]*?dependencies\s*\{)/,
        `$1\n    ${line}`,
      );
    }
    return cfg;
  });
  return withAppBuildGradle(config, (cfg) => {
    let g = cfg.modResults.contents;
    if (g.includes('com.chaquo.python')) return cfg;
    g = g.replace('apply plugin: "com.android.application"', 'apply plugin: "com.android.application"\napply plugin: "com.chaquo.python"');
    const abis = ABIS.map((a) => `"${a}"`).join(', ');
    g = g.replace(/defaultConfig\s*\{/, `defaultConfig {\n        ndk { abiFilters ${abis} }`);
    g = g.replace(
      /signingConfigs\s*\{/,
      `signingConfigs {
        release {
            if (System.getenv("ANDROID_KEYSTORE_PATH")) {
                storeFile file(System.getenv("ANDROID_KEYSTORE_PATH"))
                storePassword System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias System.getenv("ANDROID_KEY_ALIAS")
                keyPassword System.getenv("ANDROID_KEY_PASSWORD")
            }
        }`,
    );
    g = g.replace(
      /(release\s*\{[^{}]*?)signingConfig signingConfigs\.debug/,
      '$1signingConfig System.getenv("ANDROID_KEYSTORE_PATH") ? signingConfigs.release : signingConfigs.debug',
    );
    g += `
chaquopy {
    defaultConfig {
        version = "${PYTHON_VERSION}"
        pip {
            options "--no-deps"
            install "-r", "requirements-android.txt"
        }
    }
}
`;
    cfg.modResults.contents = g;
    return cfg;
  });
}

function withBotManifest(config) {
  return withAndroidManifest(config, (cfg) => {
    const manifest = cfg.modResults.manifest;
    const perms = [
      'android.permission.FOREGROUND_SERVICE',
      'android.permission.FOREGROUND_SERVICE_SPECIAL_USE',
      'android.permission.POST_NOTIFICATIONS',
      'android.permission.WAKE_LOCK',
      'android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS',
      'android.permission.RECEIVE_BOOT_COMPLETED',
    ];
    manifest['uses-permission'] = manifest['uses-permission'] ?? [];
    for (const name of perms) {
      if (!manifest['uses-permission'].some((p) => p.$['android:name'] === name)) {
        manifest['uses-permission'].push({ $: { 'android:name': name } });
      }
    }
    // Expo adds SYSTEM_ALERT_WINDOW for dev tools; the bot does not need it.
    manifest['uses-permission'] = manifest['uses-permission'].filter(
      (p) => p.$['android:name'] !== 'android.permission.SYSTEM_ALERT_WINDOW',
    );
    const app = manifest.application[0];
    app.$['android:networkSecurityConfig'] = '@xml/network_security_config';
    app.service = (app.service ?? []).filter((s) => s.$['android:name'] !== '.BotService');
    app.service.push({
      $: {
        'android:name': '.BotService',
        'android:exported': 'false',
        'android:foregroundServiceType': 'specialUse',
      },
      property: [
        {
          $: {
            'android:name': 'android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE',
            'android:value': 'Runs the user\'s own paper-trading bot on the device',
          },
        },
      ],
    });
    // Restarts the bot after a phone restart or an app update if it was running (BootReceiver.kt).
    app.receiver = (app.receiver ?? []).filter((r) => r.$['android:name'] !== '.BootReceiver');
    app.receiver.push({
      $: { 'android:name': '.BootReceiver', 'android:exported': 'true' },
      'intent-filter': [
        {
          action: [
            { $: { 'android:name': 'android.intent.action.BOOT_COMPLETED' } },
            { $: { 'android:name': 'android.intent.action.MY_PACKAGE_REPLACED' } },
          ],
        },
      ],
    });
    return cfg;
  });
}

function withBotFiles(config) {
  return withDangerousMod(config, [
    'android',
    (cfg) => {
      const projectRoot = cfg.modRequest.projectRoot;
      const repoRoot = path.resolve(projectRoot, '..');
      const appDir = path.join(cfg.modRequest.platformProjectRoot, 'app');
      const main = path.join(appDir, 'src', 'main');

      const pyDir = path.join(main, 'python');
      fs.rmSync(pyDir, { recursive: true, force: true });
      fs.mkdirSync(pyDir, { recursive: true });
      for (const file of BOT_MODULES) fs.copyFileSync(path.join(repoRoot, file), path.join(pyDir, file));
      for (const pkg of BOT_PACKAGES) copyDir(path.join(repoRoot, pkg), path.join(pyDir, pkg));
      fs.copyFileSync(path.join(repoRoot, 'packaging', 'android', 'android_runtime.py'), path.join(pyDir, 'android_runtime.py'));
      fs.copyFileSync(
        path.join(repoRoot, 'packaging', 'android', 'requirements-android.txt'),
        path.join(appDir, 'requirements-android.txt'),
      );

      const javaDir = path.join(main, 'java', PACKAGE_PATH);
      fs.mkdirSync(javaDir, { recursive: true });
      for (const file of ['BotService.kt', 'BootReceiver.kt', 'shared/RunMemory.kt']) {
        fs.copyFileSync(path.join(__dirname, 'bot-runtime', file), path.join(javaDir, path.basename(file)));
      }

      const xmlDir = path.join(main, 'res', 'xml');
      fs.mkdirSync(xmlDir, { recursive: true });
      fs.writeFileSync(
        path.join(xmlDir, 'network_security_config.xml'),
        `<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <base-config cleartextTrafficPermitted="false" />
  <domain-config cleartextTrafficPermitted="true">
    <domain includeSubdomains="false">127.0.0.1</domain>
    <domain includeSubdomains="false">localhost</domain>
  </domain-config>
</network-security-config>
`,
      );
      return cfg;
    },
  ]);
}

module.exports = function withBotRuntime(config) {
  return withBotFiles(withBotManifest(withChaquopyGradle(config)));
};
