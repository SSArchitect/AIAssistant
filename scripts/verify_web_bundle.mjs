import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

// Validate the files being shipped, rather than imports from a development checkout.
export function verifyWebBundle(directory) {
  const root = resolve(directory);
  const html = readFileSync(resolve(root, 'index.html'), 'utf8');
  const scripts = [...html.matchAll(/<script\b[^>]*\bsrc=["']([^"']+)["']/gi)]
    .map(match => match[1]).filter(src => !/^https?:\/\//.test(src))
    .map(src => src.split(/[?#]/)[0].replace(/^\/+/, ''));
  for (const script of scripts) {
    assert.ok(existsSync(resolve(root, script)), `Missing script: ${script}`);
  }
  const appIndex = scripts.findIndex(script => basename(script) === 'app.js');
  assert.ok(appIndex >= 0, 'Missing app.js entrypoint');
  const app = readFileSync(resolve(root, scripts[appIndex]), 'utf8');
  const context = vm.createContext({ URL });
  const methods = [];
  for (const [name, file] of [['VideoMedia', 'video-media.js'], ['ThinkingProcess', 'thinking-process.js']]) {
    const index = scripts.findIndex(script => basename(script) === file);
    assert.ok(index >= 0 && index < appIndex, `${file} must load before app.js`);
    vm.runInContext(readFileSync(resolve(root, scripts[index]), 'utf8'), context, { filename: file });
    const references = new Set([...app.matchAll(new RegExp(`\\b(?:globalThis\\.)?${name}\\??\\.([A-Za-z_]\\w*)`, 'g'))].map(match => match[1]));
    for (const method of references) {
      assert.equal(typeof context[name]?.[method], 'function', `Missing bundle API: ${name}.${method}`);
      methods.push(`${name}.${method}`);
    }
  }

  const escape = value => String(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
  Object.assign(context, {
    escapeHtml: escape, escapeAttr: escape, API_BASE: 'https://app.test', t: value => value,
    renderCodeCopyButton: () => '',
  });
  // Verify the shipped renderers together; stubbing the inline renderer used to
  // conceal broken relative links and structured-media integration.
  for (const name of ['formatContent', 'renderInlineMarkdown', 'renderMediaMarkdown',
    'renderVideoBlock', 'videoMediaLabels', 'renderSafeLink', 'isSafeContentUrl',
    'isSafeDataImageUrl', 'isImageUrl', 'isVideoUrl', 'normalizeArtifacts',
    'renderArtifactPanel', 'renderDriveArtifactCard', 'isMarkdownTableStart',
    'isMarkdownTableRow', 'splitMarkdownTableRow', 'isMarkdownTableSeparatorCell']) {
    const start = app.indexOf(`function ${name}(`);
    const end = app.indexOf('\nfunction ', start + 1);
    assert.ok(start >= 0 && end > start, `Missing renderer: ${name}`);
    vm.runInContext(app.slice(start, end), context);
  }
  assert.equal(context.formatContent('发布验证'), '<p>发布验证</p>');
  const url = '/static/generated/aigc/bundle-smoke.mp4';
  const video = context.formatContent(`🎬 **[视频](${url})**`);
  assert.match(video, /<video[^>]+controls/);
  const artifacts = [{ type: 'video', url, mime_type: 'video/mp4' }];
  for (const text of ['完成，没有链接', `🎬 **[视频](${url})**`]) {
    const rendered = context.formatContent(text, { artifacts }) + context.renderArtifactPanel(artifacts);
    assert.equal((rendered.match(/<video /g) || []).length, 1);
    assert.ok(rendered.includes(`src="https://app.test${url}"`));
  }
  assert.match(context.formatContent('```text\n<code>\n```'), /&lt;code&gt;/);
  return { scripts: scripts.length, methods, smokeRender: true };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = verifyWebBundle(process.argv[2] || resolve(import.meta.dirname, '../web'));
  console.log(`Web bundle verified: ${result.scripts} scripts, ${result.methods.length} module APIs, text/video rendering passed.`);
}
