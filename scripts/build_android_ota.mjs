import { createHash } from 'node:crypto';
import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { relative, resolve, sep } from 'node:path';
import { spawnSync } from 'node:child_process';

const projectRoot = resolve(import.meta.dirname, '..');
const version = String(process.argv[2] || '').trim();
const sequence = Number.parseInt(process.argv[3] || '', 10);
const safeVersionPattern = /^[0-9A-Za-z][0-9A-Za-z._-]{0,79}$/;

if (!safeVersionPattern.test(version)) {
  throw new Error('Usage: npm run android:ota -- <version> <positive-sequence>');
}
if (!Number.isInteger(sequence) || sequence <= 0) {
  throw new Error('OTA sequence must be a positive integer and increase for every release.');
}

const minNativeVersionCode = Number.parseInt(
  process.env.AGENT_ASSISTANT_OTA_MIN_NATIVE_VERSION_CODE || '1',
  10,
);
const maxNativeVersionCode = Number.parseInt(
  process.env.AGENT_ASSISTANT_OTA_MAX_NATIVE_VERSION_CODE || '0',
  10,
);
const sourceDir = resolve(projectRoot, 'dist', 'android-web');
const otaRoot = resolve(projectRoot, 'artifacts', 'android-ota');
const releaseDir = resolve(otaRoot, version);
const filesDir = resolve(releaseDir, 'files');
const latestPath = resolve(otaRoot, 'latest.json');

if (existsSync(releaseDir)) {
  throw new Error(`OTA version ${version} already exists. Release versions are immutable; choose a new version.`);
}

if (!Number.isInteger(minNativeVersionCode) || minNativeVersionCode <= 0) {
  throw new Error('AGENT_ASSISTANT_OTA_MIN_NATIVE_VERSION_CODE must be a positive integer.');
}
if (!Number.isInteger(maxNativeVersionCode) || maxNativeVersionCode < 0) {
  throw new Error('AGENT_ASSISTANT_OTA_MAX_NATIVE_VERSION_CODE must be zero or a positive integer.');
}
if (maxNativeVersionCode > 0 && maxNativeVersionCode < minNativeVersionCode) {
  throw new Error('OTA maximum native version code cannot be lower than the minimum.');
}

try {
  const previous = JSON.parse(readFileSync(latestPath, 'utf8'));
  const previousSequence = Number(previous?.sequence || 0);
  if (Number.isInteger(previousSequence) && sequence <= previousSequence) {
    throw new Error(`OTA sequence must be greater than the current sequence ${previousSequence}.`);
  }
} catch (error) {
  if (error?.code !== 'ENOENT') throw error;
}

const buildResult = spawnSync(process.execPath, [resolve(projectRoot, 'scripts', 'build_android_web.mjs')], {
  cwd: projectRoot,
  env: {
    ...process.env,
    AGENT_ASSISTANT_WEB_VERSION: version,
    AGENT_ASSISTANT_OTA_SEQUENCE: String(sequence),
  },
  stdio: 'inherit',
});
if (buildResult.status !== 0) {
  throw new Error(`Android web build failed with exit code ${buildResult.status ?? 'unknown'}.`);
}

mkdirSync(filesDir, { recursive: true });
cpSync(sourceDir, filesDir, { recursive: true });

function walkFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolutePath = resolve(directory, entry.name);
    return entry.isDirectory() ? walkFiles(absolutePath) : [absolutePath];
  });
}

function urlPathForFile(fileName) {
  return fileName.split('/').map(encodeURIComponent).join('/');
}

const manifest = walkFiles(filesDir)
  .filter((filePath) => statSync(filePath).isFile())
  .map((filePath) => {
    const fileName = relative(filesDir, filePath).split(sep).join('/');
    return {
      file_name: fileName,
      file_hash: createHash('sha256').update(readFileSync(filePath)).digest('hex'),
      download_url: `/updates/android/${encodeURIComponent(version)}/files/${urlPathForFile(fileName)}`,
    };
  })
  .sort((left, right) => left.file_name.localeCompare(right.file_name));

if (!manifest.some((entry) => entry.file_name === 'index.html')) {
  throw new Error('OTA release is invalid: index.html is missing.');
}

const release = {
  version,
  sequence,
  min_native_version_code: minNativeVersionCode,
  max_native_version_code: maxNativeVersionCode,
  published_at: new Date().toISOString(),
  manifest,
};
const json = `${JSON.stringify(release, null, 2)}\n`;

writeFileSync(resolve(releaseDir, 'manifest.json'), json);
mkdirSync(otaRoot, { recursive: true });
const pendingLatestPath = resolve(otaRoot, `.latest-${process.pid}.json`);
writeFileSync(pendingLatestPath, json);
renameSync(pendingLatestPath, latestPath);

const totalBytes = manifest.reduce((sum, entry) => (
  sum + statSync(resolve(filesDir, entry.file_name)).size
), 0);
console.log(`OTA ${version} (#${sequence}) contains ${manifest.length} files, ${totalBytes} bytes before reuse.`);
console.log(`Release directory: ${releaseDir}`);
