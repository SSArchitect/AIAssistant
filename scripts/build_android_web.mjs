import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { build } from 'esbuild';

const projectRoot = resolve(import.meta.dirname, '..');
const sourceDir = resolve(projectRoot, 'web');
const outputDir = resolve(projectRoot, 'dist', 'android-web');
const apiBase = String(
  process.env.AGENT_ASSISTANT_API_BASE || 'https://www.architect8.cn',
).replace(/\/+$/, '');
const packageJson = JSON.parse(readFileSync(resolve(projectRoot, 'package.json'), 'utf8'));
const appVersionName = String(packageJson.version || '0.1.0');
const appVersionCode = Number.parseInt(process.env.AGENT_ASSISTANT_ANDROID_VERSION_CODE || '1', 10);
const webVersion = String(process.env.AGENT_ASSISTANT_WEB_VERSION || appVersionName);
const otaSequence = Number.parseInt(process.env.AGENT_ASSISTANT_OTA_SEQUENCE || '0', 10);

rmSync(outputDir, { recursive: true, force: true });
mkdirSync(outputDir, { recursive: true });
cpSync(sourceDir, outputDir, { recursive: true });

writeFileSync(
  resolve(outputDir, 'static', 'js', 'runtime-config.js'),
  `globalThis.AGENT_ASSISTANT_CONFIG = Object.freeze(${JSON.stringify({
    apiBase,
    appVersionName,
    appVersionCode,
    webVersion,
    otaSequence: Number.isFinite(otaSequence) && otaSequence >= 0 ? otaSequence : 0,
  })});\n`,
);

await build({
  entryPoints: [resolve(projectRoot, 'mobile', 'android-bridge.js')],
  outfile: resolve(outputDir, 'static', 'js', 'android-bridge.js'),
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: 'chrome109',
  minify: true,
});

console.log(`Android web assets built with API base: ${apiBase}`);
