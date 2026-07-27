(function initializeShareCardRenderer(globalScope, factory) {
    const api = factory(globalScope);
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    }
    if (globalScope) {
        globalScope.ShareCardRenderer = api;
    }
}(typeof globalThis !== 'undefined' ? globalThis : this, function buildShareCardRenderer(globalScope) {
    'use strict';

    const CARD_WIDTH = 1080;
    const MIN_CARD_HEIGHT = 1080;
    const MAX_CARD_HEIGHT = 14400;
    const BODY_X = 48;
    const BODY_WIDTH = CARD_WIDTH - (BODY_X * 2);
    const BODY_PADDING = 54;
    const CONTENT_WIDTH = BODY_WIDTH - (BODY_PADDING * 2);
    const MAX_SHARE_CARD_IMAGES = 6;
    const MAX_SHARE_CARD_IMAGE_HEIGHT = 680;
    const FONT_STACK = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif';
    const MONO_STACK = '"SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace';

    function sanitizeInlineText(value = '') {
        return decodeBasicEntities(
            String(value)
                .replace(/!\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)/g, (_, alt) => (alt ? `图片：${alt}` : '图片'))
                .replace(/\[([^\]]+)\]\((?:[^()]|\([^()]*\))*\)/g, '$1')
                .replace(/<((?:https?:\/\/|mailto:)[^>]+)>/gi, '$1')
                .replace(/<\/?[^>]+>/g, '')
                .replace(/`([^`]+)`/g, '$1')
                .replace(/(\*\*|__|~~)(.*?)\1/g, '$2')
                .replace(/(^|[\s([{])([*_])([^*_\n]+)\2(?=$|[\s)\]},.!?，。！？；：])/g, '$1$3')
                .replace(/\\([\\`*_[\]{}()#+.!>~-])/g, '$1')
                .replace(/[ \t]+/g, ' ')
                .trim()
        );
    }

    function decodeBasicEntities(value = '') {
        const entities = {
            amp: '&',
            lt: '<',
            gt: '>',
            quot: '"',
            apos: "'",
            nbsp: ' ',
        };
        return String(value).replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (match, entity) => {
            const normalized = entity.toLowerCase();
            if (normalized[0] !== '#') return entities[normalized] ?? match;
            const hexadecimal = normalized[1] === 'x';
            const parsed = Number.parseInt(normalized.slice(hexadecimal ? 2 : 1), hexadecimal ? 16 : 10);
            return Number.isFinite(parsed) && parsed >= 0 && parsed <= 0x10ffff
                ? String.fromCodePoint(parsed)
                : match;
        });
    }

    function parseMarkdownBlocks(markdown = '') {
        const lines = String(markdown).replace(/\r\n?/g, '\n').split('\n');
        const blocks = [];
        let paragraph = [];
        let quote = [];
        let list = null;
        let code = null;

        const flushParagraph = () => {
            const text = sanitizeInlineText(paragraph.join(' '));
            if (text) blocks.push({ type: 'paragraph', text });
            paragraph = [];
        };
        const flushQuote = () => {
            const text = sanitizeInlineText(quote.join(' '));
            if (text) blocks.push({ type: 'quote', text });
            quote = [];
        };
        const flushList = () => {
            if (list?.items?.length) blocks.push(list);
            list = null;
        };
        const flushText = () => {
            flushParagraph();
            flushQuote();
            flushList();
        };

        for (let index = 0; index < lines.length; index += 1) {
            const rawLine = lines[index];
            const trimmed = rawLine.trim();

            if (code) {
                if (new RegExp(`^${code.fence}{3,}\\s*$`).test(trimmed)) {
                    blocks.push({
                        type: 'code',
                        language: code.language,
                        text: code.lines.join('\n').replace(/\n+$/, ''),
                    });
                    code = null;
                } else {
                    code.lines.push(rawLine);
                }
                continue;
            }

            const fence = trimmed.match(/^(`{3,}|~{3,})\s*([\w.+-]*)\s*$/);
            if (fence) {
                flushText();
                code = {
                    fence: fence[1][0],
                    language: fence[2] || '',
                    lines: [],
                };
                continue;
            }

            if (!trimmed) {
                flushText();
                continue;
            }

            const image = parseShareCardImageBlock(trimmed);
            if (image) {
                flushText();
                blocks.push(image);
                continue;
            }

            if (isMarkdownTableStart(lines, index)) {
                flushText();
                const header = parseTableCells(lines[index]);
                index += 2;
                const rows = [];
                while (index < lines.length && isMarkdownTableRow(lines[index])) {
                    rows.push(parseTableCells(lines[index]));
                    index += 1;
                }
                index -= 1;
                blocks.push({ type: 'table', header, rows });
                continue;
            }

            const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
            if (heading) {
                flushText();
                const text = sanitizeInlineText(heading[2]);
                if (text) blocks.push({ type: 'heading', level: heading[1].length, text });
                continue;
            }

            if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
                flushText();
                blocks.push({ type: 'separator' });
                continue;
            }

            const ordered = trimmed.match(/^(\d+)[.)、]\s+(.+)$/);
            const unordered = trimmed.match(/^[-*+]\s+(.+)$/);
            if (ordered || unordered) {
                flushParagraph();
                flushQuote();
                const orderedList = Boolean(ordered);
                if (list && list.ordered !== orderedList) flushList();
                if (!list) {
                    list = {
                        type: 'list',
                        ordered: orderedList,
                        start: ordered ? Number(ordered[1]) || 1 : 1,
                        items: [],
                    };
                }
                const text = sanitizeInlineText(ordered ? ordered[2] : unordered[1]);
                if (text) list.items.push(text);
                continue;
            }

            const quoted = trimmed.match(/^>\s?(.*)$/);
            if (quoted) {
                flushParagraph();
                flushList();
                quote.push(quoted[1]);
                continue;
            }

            flushQuote();
            flushList();
            paragraph.push(trimmed);
        }

        if (code) {
            blocks.push({
                type: 'code',
                language: code.language,
                text: code.lines.join('\n').replace(/\n+$/, ''),
            });
        }
        flushText();

        if (!blocks.length && String(markdown).trim()) {
            blocks.push({ type: 'paragraph', text: sanitizeInlineText(markdown) });
        }
        return blocks;
    }

    function parseShareCardImageBlock(line = '') {
        const value = String(line).trim();
        const markdownImage = value.match(
            /^!\[([^\]]*)\]\((https?:\/\/[^\s)]+|\/[^\s)]+|data:image\/[a-z0-9.+-]+;base64,[^\s)]+)\)$/i
        );
        if (markdownImage && isSafeShareCardImageUrl(markdownImage[2])) {
            return {
                type: 'image',
                alt: sanitizeInlineText(markdownImage[1]),
                url: markdownImage[2],
            };
        }
        if (isSafeShareCardImageUrl(value) && /\.(?:png|jpe?g|gif|webp|avif|bmp|svg)(?:[?#].*)?$/i.test(value)) {
            return { type: 'image', alt: '', url: value };
        }
        return null;
    }

    function isSafeShareCardImageUrl(url = '') {
        const value = String(url).trim();
        if (/^data:image\/(?:png|jpe?g|gif|webp|avif|bmp);base64,[a-z0-9+/=\s]+$/i.test(value)) {
            return true;
        }
        if (/^\/(?!\/)/.test(value)) return true;
        try {
            const parsed = new URL(value);
            return ['http:', 'https:'].includes(parsed.protocol) && Boolean(parsed.hostname);
        } catch {
            return false;
        }
    }

    function isMarkdownTableStart(lines, index) {
        return isMarkdownTableRow(lines[index])
            && index + 1 < lines.length
            && isMarkdownTableSeparator(lines[index + 1]);
    }

    function isMarkdownTableRow(line = '') {
        const value = String(line).trim();
        return value.includes('|') && parseTableCells(value).length >= 2;
    }

    function isMarkdownTableSeparator(line = '') {
        const cells = parseTableCells(line);
        return cells.length >= 2 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s/g, '')));
    }

    function parseTableCells(line = '') {
        const normalized = String(line)
            .trim()
            .replace(/^\|/, '')
            .replace(/\|$/, '');
        return splitMarkdownTableCells(normalized)
            .map((cell) => sanitizeInlineText(cell.replace(/\\\|/g, '|')))
            .filter((cell, index, cells) => cell || cells.length > 1 || index === 0);
    }

    function splitMarkdownTableCells(value = '') {
        const cells = [];
        let cell = '';
        let escaped = false;
        for (const character of String(value)) {
            if (character === '|' && !escaped) {
                cells.push(cell);
                cell = '';
                continue;
            }
            cell += character;
            if (character === '\\' && !escaped) {
                escaped = true;
            } else {
                escaped = false;
            }
        }
        cells.push(cell);
        return cells;
    }

    function resolveShareCardImageFetchUrl(url = '', options = {}) {
        const value = String(url).trim();
        if (!isSafeShareCardImageUrl(value)) return '';
        if (value.startsWith('/') || value.startsWith('data:image/')) return value;

        const origin = String(options.locationOrigin || globalScope?.location?.origin || '').replace(/\/$/, '');
        try {
            const parsed = new URL(value);
            if (origin && parsed.origin === origin) return value;
        } catch {
            return '';
        }

        const proxyPath = String(options.imageProxyPath || '/api/media/download?url=');
        return proxyPath ? `${proxyPath}${encodeURIComponent(value)}` : value;
    }

    async function loadShareCardImageAssets(blocks = [], options = {}) {
        const urls = [];
        const seen = new Set();
        for (const block of blocks) {
            if (block?.type !== 'image' || !block.url || seen.has(block.url)) continue;
            seen.add(block.url);
            urls.push(block.url);
        }

        const limitedUrls = urls.slice(0, Math.max(0, Number(options.maxImages) || MAX_SHARE_CARD_IMAGES));
        const assets = new Map();
        const cleanupUrls = [];
        await Promise.all(limitedUrls.map(async (url) => {
            try {
                const loaded = await loadShareCardImage(url, options);
                assets.set(url, loaded.asset);
                if (loaded.cleanupUrl) cleanupUrls.push(loaded.cleanupUrl);
            } catch (error) {
                assets.set(url, {
                    status: 'failed',
                    error: error?.message || 'image load failed',
                });
            }
        }));

        urls.slice(limitedUrls.length).forEach((url) => {
            assets.set(url, { status: 'failed', error: 'image limit reached' });
        });

        return {
            assets,
            imageCount: urls.length,
            failedCount: Array.from(assets.values()).filter((asset) => asset.status !== 'loaded').length,
            cleanup() {
                const urlApi = options.urlApi || globalScope?.URL;
                cleanupUrls.forEach((url) => {
                    try {
                        urlApi?.revokeObjectURL?.(url);
                    } catch {
                        // The generated card is already independent of the temporary image URL.
                    }
                });
            },
        };
    }

    async function loadShareCardImage(url, options = {}) {
        const source = resolveShareCardImageFetchUrl(url, options);
        if (!source) throw new Error('unsafe image url');

        const fetchApi = options.fetchApi || globalScope?.fetch?.bind(globalScope);
        const urlApi = options.urlApi || globalScope?.URL;
        let imageSource = source;
        let cleanupUrl = '';

        if (typeof fetchApi === 'function' && typeof urlApi?.createObjectURL === 'function') {
            const response = await fetchApi(source, {
                credentials: source.startsWith('/') ? 'same-origin' : 'omit',
            });
            if (!response?.ok) throw new Error(`image request failed: ${response?.status || 0}`);
            const blob = await response.blob();
            if (blob.type && !blob.type.toLowerCase().startsWith('image/')) {
                throw new Error('image response has an invalid content type');
            }
            cleanupUrl = urlApi.createObjectURL(blob);
            imageSource = cleanupUrl;
        }

        try {
            const image = await loadShareCardImageElement(imageSource, options);
            return {
                asset: {
                    status: 'loaded',
                    image,
                    width: Number(image.naturalWidth || image.width || 0),
                    height: Number(image.naturalHeight || image.height || 0),
                },
                cleanupUrl,
            };
        } catch (error) {
            if (cleanupUrl) {
                try {
                    urlApi?.revokeObjectURL?.(cleanupUrl);
                } catch {
                    // Ignore cleanup errors while preserving the original load failure.
                }
            }
            throw error;
        }
    }

    function loadShareCardImageElement(source, options = {}) {
        const ImageCtor = options.ImageCtor || globalScope?.Image;
        if (typeof ImageCtor !== 'function') {
            return Promise.reject(new Error('Image is not available'));
        }
        const timeoutMs = Math.max(1000, Number(options.imageLoadTimeoutMs) || 12000);

        return new Promise((resolve, reject) => {
            const image = new ImageCtor();
            let settled = false;
            const finish = (callback, value) => {
                if (settled) return;
                settled = true;
                clearTimeout(timer);
                image.onload = null;
                image.onerror = null;
                callback(value);
            };
            const timer = setTimeout(() => {
                finish(reject, new Error('image load timed out'));
            }, timeoutMs);
            image.onload = () => {
                const width = Number(image.naturalWidth || image.width || 0);
                const height = Number(image.naturalHeight || image.height || 0);
                if (!width || !height) {
                    finish(reject, new Error('image has invalid dimensions'));
                    return;
                }
                finish(resolve, image);
            };
            image.onerror = () => finish(reject, new Error('image decode failed'));
            image.decoding = 'async';
            image.src = source;
        });
    }

    function wrapMeasuredText(measureText, text = '', maxWidth = 1) {
        const measure = typeof measureText === 'function' ? measureText : ((value) => String(value).length);
        const width = Math.max(1, Number(maxWidth) || 1);
        const wrapped = [];

        String(text).replace(/\r\n?/g, '\n').split('\n').forEach((sourceLine) => {
            if (!sourceLine) {
                wrapped.push('');
                return;
            }

            const tokens = sourceLine.match(/\s+|[\u2e80-\u9fff\uf900-\ufaff]|[^\s\u2e80-\u9fff\uf900-\ufaff]+/gu) || [sourceLine];
            let line = '';

            const pushLine = () => {
                wrapped.push(line.trimEnd());
                line = '';
            };

            tokens.forEach((token) => {
                if (!line && /^\s+$/.test(token)) return;
                const candidate = `${line}${token}`;
                if (measure(candidate) <= width) {
                    line = candidate;
                    return;
                }

                if (line) pushLine();
                if (measure(token) <= width) {
                    line = token.replace(/^\s+/, '');
                    return;
                }

                Array.from(token).forEach((character) => {
                    const characterCandidate = `${line}${character}`;
                    if (line && measure(characterCandidate) > width) pushLine();
                    line += character;
                });
            });

            if (line || !wrapped.length) pushLine();
        });

        return wrapped.length ? wrapped : [''];
    }

    function wrapCanvasText(context, text, maxWidth) {
        return wrapMeasuredText((value) => context.measureText(value).width, text, maxWidth);
    }

    function truncateWrappedLines(context, text, maxWidth, maxLines) {
        const lines = wrapCanvasText(context, text, maxWidth);
        if (lines.length <= maxLines) return lines;
        const result = lines.slice(0, maxLines);
        let tail = `${result[result.length - 1].trimEnd()}…`;
        while (tail.length > 1 && context.measureText(tail).width > maxWidth) {
            tail = `${tail.slice(0, -2).trimEnd()}…`;
        }
        result[result.length - 1] = tail;
        return result;
    }

    function font(weight, size, family = FONT_STACK) {
        return `${weight} ${size}px ${family}`;
    }

    function blockTextStyle(block) {
        if (block.type === 'heading') {
            if (block.level <= 1) return { font: font(760, 38), lineHeight: 52, color: '#111827', top: 24, bottom: 10 };
            if (block.level === 2) return { font: font(740, 32), lineHeight: 46, color: '#172554', top: 22, bottom: 8 };
            return { font: font(720, 27), lineHeight: 40, color: '#1f2937', top: 18, bottom: 6 };
        }
        return { font: font(430, 25), lineHeight: 40, color: '#344054', top: 8, bottom: 10 };
    }

    function layoutBlocks(context, blocks, maxHeight, options = {}) {
        const layouts = [];

        blocks.forEach((block) => {
            if (block.type === 'image') {
                const asset = imageAssetForUrl(options.imageAssets, block.url);
                if (asset?.status === 'loaded' && asset.width > 0 && asset.height > 0) {
                    const scale = Math.min(
                        CONTENT_WIDTH / asset.width,
                        MAX_SHARE_CARD_IMAGE_HEIGHT / asset.height,
                        1.5
                    );
                    const drawWidth = Math.max(1, Math.round(asset.width * scale));
                    const drawHeight = Math.max(1, Math.round(asset.height * scale));
                    const captionStyle = { font: font(560, 18), lineHeight: 29, color: '#667085' };
                    context.font = captionStyle.font;
                    const captionLines = block.alt
                        ? truncateWrappedLines(context, block.alt, CONTENT_WIDTH, 2)
                        : [];
                    const captionHeight = captionLines.length ? 14 + (captionLines.length * captionStyle.lineHeight) : 0;
                    layouts.push({
                        kind: 'image',
                        image: asset.image,
                        sourceUrl: block.url,
                        drawWidth,
                        drawHeight,
                        captionLines,
                        captionStyle,
                        top: 14,
                        bottom: 18,
                        height: 14 + drawHeight + captionHeight + 18,
                    });
                } else {
                    const fallbackStyle = { font: font(620, 21), lineHeight: 34, color: '#667085' };
                    context.font = fallbackStyle.font;
                    const fallbackText = [
                        options.imageFallbackLabel || 'Image unavailable',
                        block.alt ? `：${block.alt}` : '',
                    ].join('');
                    const lines = wrapCanvasText(context, fallbackText, CONTENT_WIDTH - 88);
                    layouts.push({
                        kind: 'imagePlaceholder',
                        lines,
                        ...fallbackStyle,
                        top: 12,
                        bottom: 16,
                        height: 28 + Math.max(92, (lines.length * fallbackStyle.lineHeight) + 38),
                    });
                }
                return;
            }

            if (block.type === 'heading' || block.type === 'paragraph') {
                const style = blockTextStyle(block);
                context.font = style.font;
                const lines = wrapCanvasText(context, block.text, CONTENT_WIDTH);
                layouts.push({
                    kind: 'text',
                    role: block.type,
                    lines,
                    ...style,
                    height: style.top + (lines.length * style.lineHeight) + style.bottom,
                });
                return;
            }

            if (block.type === 'list') {
                block.items.forEach((text, itemIndex) => {
                    const style = blockTextStyle({ type: 'paragraph' });
                    context.font = style.font;
                    const lines = wrapCanvasText(context, text, CONTENT_WIDTH - 48);
                    layouts.push({
                        kind: 'list',
                        marker: block.ordered ? `${block.start + itemIndex}.` : '•',
                        lines,
                        ...style,
                        top: 5,
                        bottom: 5,
                        height: 10 + (lines.length * style.lineHeight),
                    });
                });
                layouts.push({ kind: 'spacer', height: 6 });
                return;
            }

            if (block.type === 'quote') {
                const style = { font: font(520, 24), lineHeight: 38, color: '#344054' };
                context.font = style.font;
                const lines = wrapCanvasText(context, block.text, CONTENT_WIDTH - 64);
                layouts.push({
                    kind: 'quote',
                    lines,
                    ...style,
                    top: 10,
                    bottom: 12,
                    boxPadding: 28,
                    height: 22 + (lines.length * style.lineHeight) + 32,
                });
                return;
            }

            if (block.type === 'code') {
                const style = { font: font(430, 21, MONO_STACK), lineHeight: 33, color: '#e2e8f0' };
                context.font = style.font;
                const lines = [];
                String(block.text || '').split('\n').forEach((line) => {
                    lines.push(...wrapCanvasText(context, line || ' ', CONTENT_WIDTH - 42));
                });
                layouts.push({
                    kind: 'code',
                    language: block.language,
                    lines,
                    ...style,
                    top: 12,
                    bottom: 14,
                    boxPadding: 24,
                    height: 26 + (lines.length * style.lineHeight) + 40,
                });
                return;
            }

            if (block.type === 'table') {
                const tableRows = [
                    { cells: block.header, header: true },
                    ...block.rows.map((cells) => ({ cells, header: false })),
                ];
                tableRows.forEach((row, rowIndex) => {
                    const style = {
                        font: font(row.header ? 700 : 470, 21),
                        lineHeight: 34,
                        color: row.header ? '#1e3a8a' : '#344054',
                    };
                    context.font = style.font;
                    const text = row.cells.filter(Boolean).join('  ·  ');
                    const lines = wrapCanvasText(context, text, CONTENT_WIDTH - 38);
                    const top = rowIndex === 0 ? 12 : 3;
                    const bottom = 3;
                    const rowBoxHeight = (lines.length * style.lineHeight) + 28;
                    layouts.push({
                        kind: 'tableRow',
                        header: row.header,
                        alternate: rowIndex % 2 === 0,
                        lines,
                        ...style,
                        top,
                        bottom,
                        height: top + rowBoxHeight + bottom,
                    });
                });
                layouts.push({ kind: 'spacer', height: 12 });
                return;
            }

            if (block.type === 'separator') {
                layouts.push({ kind: 'separator', height: 42 });
            }
        });

        return constrainLayouts(layouts, maxHeight);
    }

    function imageAssetForUrl(imageAssets, url) {
        if (imageAssets instanceof Map) return imageAssets.get(url);
        if (imageAssets && typeof imageAssets === 'object') return imageAssets[url];
        return null;
    }

    function constrainLayouts(layouts, maxHeight) {
        const output = [];
        const noticeHeight = 96;
        let used = 0;
        let truncated = false;

        for (let index = 0; index < layouts.length; index += 1) {
            const item = layouts[index];
            const room = maxHeight - used;
            const reserve = index < layouts.length - 1 ? noticeHeight : 0;
            if (item.height <= room - reserve) {
                output.push(item);
                used += item.height;
                continue;
            }

            const clipped = clipLayoutItem(item, Math.max(0, room - noticeHeight));
            if (clipped) {
                output.push(clipped);
                used += clipped.height;
            }
            truncated = true;
            break;
        }

        if (truncated) {
            const notice = {
                kind: 'notice',
                height: noticeHeight,
                font: font(650, 22),
                lineHeight: 34,
                color: '#92400e',
            };
            while (output.length && used + notice.height > maxHeight) {
                used -= output.pop().height;
            }
            if (used + notice.height <= maxHeight) {
                output.push(notice);
                used += notice.height;
            }
        }

        return { layouts: output, height: used, truncated };
    }

    function clipLayoutItem(item, availableHeight) {
        if (!item?.lines?.length || availableHeight <= 0) return null;
        const fixedHeight = item.height - (item.lines.length * item.lineHeight);
        const lineCount = Math.floor((availableHeight - fixedHeight) / item.lineHeight);
        if (lineCount < 1) return null;
        return {
            ...item,
            lines: item.lines.slice(0, lineCount),
            height: fixedHeight + (lineCount * item.lineHeight),
        };
    }

    function renderShareCardCanvas(options = {}) {
        const documentApi = options.documentApi || globalScope?.document;
        const createCanvas = options.createCanvas || (() => documentApi?.createElement?.('canvas'));
        const canvas = createCanvas();
        if (!canvas?.getContext) throw new Error('Canvas is not available');

        canvas.width = CARD_WIDTH;
        canvas.height = 16;
        let context = canvas.getContext('2d');
        if (!context) throw new Error('2D canvas context is not available');

        const question = sanitizeInlineText(options.question || '');
        const answer = String(options.answer || '').trim();
        const blocks = Array.isArray(options.blocks) ? options.blocks : parseMarkdownBlocks(answer);
        const questionText = question || sanitizeInlineText(options.fallbackTitle || options.answerLabel || 'AI Answer');

        context.font = font(760, 34);
        const questionLines = truncateWrappedLines(context, questionText, CARD_WIDTH - 144, 3);
        const headerHeight = 216 + (questionLines.length * 48);
        const bodyY = headerHeight - 22;
        const bodyTop = 76;
        const footerHeight = 112;
        const maxContentHeight = MAX_CARD_HEIGHT - bodyY - bodyTop - footerHeight - 54;
        const bodyLayout = layoutBlocks(context, blocks, maxContentHeight, options);
        const naturalHeight = bodyY + bodyTop + bodyLayout.height + footerHeight + 54;
        const finalHeight = Math.max(MIN_CARD_HEIGHT, Math.min(MAX_CARD_HEIGHT, Math.ceil(naturalHeight / 2) * 2));

        canvas.height = finalHeight;
        context = canvas.getContext('2d');
        if (!context) throw new Error('2D canvas context is not available');

        drawBackground(context, finalHeight, headerHeight);
        drawHeader(context, {
            brand: options.brand || 'AI Assistant',
            product: options.product || 'Super Chat',
            questionLabel: options.questionLabel || 'QUESTION',
            questionLines,
        });
        drawBody(context, {
            y: bodyY,
            height: finalHeight - bodyY - 44,
            answerLabel: options.answerLabel || 'AI Answer',
            layouts: bodyLayout.layouts,
            truncatedLabel: options.truncatedLabel || 'The complete answer is too long for one image.',
            footer: options.footer || '',
        });

        return {
            canvas,
            width: CARD_WIDTH,
            height: finalHeight,
            truncated: bodyLayout.truncated,
            layout: {
                headerHeight,
                bodyY,
                questionLines,
                bodyLayouts: bodyLayout.layouts,
            },
        };
    }

    function drawBackground(context, height, headerHeight) {
        const background = context.createLinearGradient(0, 0, 0, height);
        background.addColorStop(0, '#e8edff');
        background.addColorStop(0.45, '#f5f7fb');
        background.addColorStop(1, '#edf2f7');
        context.fillStyle = background;
        context.fillRect(0, 0, CARD_WIDTH, height);

        const header = context.createLinearGradient(0, 0, CARD_WIDTH, headerHeight);
        header.addColorStop(0, '#172554');
        header.addColorStop(0.58, '#293c88');
        header.addColorStop(1, '#3157d5');
        context.fillStyle = header;
        context.fillRect(0, 0, CARD_WIDTH, headerHeight);

        context.save();
        context.globalAlpha = 0.15;
        context.fillStyle = '#ffffff';
        context.beginPath();
        context.arc(944, 54, 156, 0, Math.PI * 2);
        context.fill();
        context.globalAlpha = 0.09;
        context.beginPath();
        context.arc(858, 210, 118, 0, Math.PI * 2);
        context.fill();
        context.restore();
    }

    function drawHeader(context, options) {
        drawRoundedRect(context, 72, 58, 48, 48, 15, '#ffffff');
        context.fillStyle = '#3157d5';
        context.font = font(820, 21);
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.fillText('AI', 96, 83);

        context.textAlign = 'left';
        context.fillStyle = 'rgba(255,255,255,0.96)';
        context.font = font(720, 23);
        context.fillText(options.brand, 136, 78);
        context.fillStyle = 'rgba(255,255,255,0.62)';
        context.font = font(560, 18);
        context.fillText(options.product, 136, 103);

        const badgeText = 'SHARE CARD';
        context.font = font(720, 16);
        const badgeWidth = context.measureText(badgeText).width + 34;
        drawRoundedRect(context, CARD_WIDTH - 72 - badgeWidth, 64, badgeWidth, 36, 18, 'rgba(255,255,255,0.13)');
        context.fillStyle = 'rgba(255,255,255,0.82)';
        context.textAlign = 'center';
        context.fillText(badgeText, CARD_WIDTH - 72 - (badgeWidth / 2), 83);

        context.textAlign = 'left';
        context.textBaseline = 'alphabetic';
        context.fillStyle = 'rgba(255,255,255,0.62)';
        context.font = font(700, 17);
        context.fillText(String(options.questionLabel).toLocaleUpperCase(), 72, 154);

        context.fillStyle = '#ffffff';
        context.font = font(760, 34);
        options.questionLines.forEach((line, index) => {
            context.fillText(line, 72, 202 + (index * 48));
        });
    }

    function drawBody(context, options) {
        drawRoundedRect(context, BODY_X, options.y, BODY_WIDTH, options.height, 34, '#ffffff');

        const labelWidth = drawLabel(context, BODY_X + BODY_PADDING, options.y + 42, options.answerLabel);
        context.fillStyle = '#dbe4ff';
        context.fillRect(BODY_X + BODY_PADDING + labelWidth + 18, options.y + 57, CONTENT_WIDTH - labelWidth - 18, 2);

        let cursorY = options.y + 84;
        options.layouts.forEach((item) => {
            cursorY = drawLayoutItem(context, item, BODY_X + BODY_PADDING, cursorY, CONTENT_WIDTH, options.truncatedLabel);
        });

        const footerY = options.y + options.height - 78;
        context.fillStyle = '#e4e7ec';
        context.fillRect(BODY_X + BODY_PADDING, footerY, CONTENT_WIDTH, 2);
        context.fillStyle = '#98a2b3';
        context.font = font(560, 18);
        context.textAlign = 'left';
        context.textBaseline = 'alphabetic';
        context.fillText(options.footer, BODY_X + BODY_PADDING, footerY + 42);
        context.textAlign = 'right';
        context.fillText('AI · CARD', BODY_X + BODY_WIDTH - BODY_PADDING, footerY + 42);
    }

    function drawLabel(context, x, y, label) {
        context.font = font(740, 18);
        const width = context.measureText(label).width + 32;
        drawRoundedRect(context, x, y, width, 32, 16, '#e9f0ff');
        context.fillStyle = '#3157d5';
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.fillText(label, x + (width / 2), y + 17);
        context.textAlign = 'left';
        context.textBaseline = 'alphabetic';
        return width;
    }

    function drawLayoutItem(context, item, x, y, width, truncatedLabel) {
        if (item.kind === 'spacer') return y + item.height;
        if (item.kind === 'separator') {
            context.fillStyle = '#e4e7ec';
            context.fillRect(x, y + 20, width, 2);
            return y + item.height;
        }

        if (item.kind === 'notice') {
            drawRoundedRect(context, x, y + 12, width, item.height - 20, 18, '#fff7ed');
            context.fillStyle = item.color;
            context.font = item.font;
            context.textAlign = 'left';
            context.textBaseline = 'middle';
            context.fillText(`… ${truncatedLabel}`, x + 24, y + (item.height / 2) + 2);
            return y + item.height;
        }

        if (item.kind === 'image') {
            const imageY = y + item.top;
            const imageX = x + Math.max(0, (width - item.drawWidth) / 2);
            drawRoundedRect(context, imageX, imageY, item.drawWidth, item.drawHeight, 18, '#f2f4f7');

            let drawn = false;
            context.save();
            roundedRectPath(context, imageX, imageY, item.drawWidth, item.drawHeight, 18);
            context.clip();
            try {
                context.imageSmoothingEnabled = true;
                context.imageSmoothingQuality = 'high';
                context.drawImage(item.image, imageX, imageY, item.drawWidth, item.drawHeight);
                drawn = true;
            } catch {
                // A single undecodable image should not prevent the rest of the card from rendering.
            }
            context.restore();

            if (!drawn) {
                drawImageFallbackBox(context, imageX, imageY, item.drawWidth, item.drawHeight, 'Image unavailable');
            }

            if (item.captionLines.length) {
                context.fillStyle = item.captionStyle.color;
                context.font = item.captionStyle.font;
                context.textAlign = 'left';
                context.textBaseline = 'alphabetic';
                item.captionLines.forEach((line, index) => {
                    context.fillText(
                        line,
                        imageX,
                        imageY + item.drawHeight + 14 + item.captionStyle.lineHeight - 9
                            + (index * item.captionStyle.lineHeight)
                    );
                });
            }
            return y + item.height;
        }

        if (item.kind === 'imagePlaceholder') {
            const boxY = y + item.top;
            const boxHeight = item.height - item.top - item.bottom;
            drawImageFallbackBox(context, x, boxY, width, boxHeight, '');
            drawTextLines(context, item, x + 66, boxY + Math.max(14, (boxHeight - (item.lines.length * item.lineHeight)) / 2));
            return y + item.height;
        }

        if (item.kind === 'quote') {
            const boxY = y + item.top;
            const boxHeight = item.height - item.top - item.bottom;
            drawRoundedRect(context, x, boxY, width, boxHeight, 18, '#f7f9fc');
            drawRoundedRect(context, x, boxY, 7, boxHeight, 4, '#3157d5');
            drawTextLines(context, item, x + item.boxPadding + 10, boxY + 30);
            return y + item.height;
        }

        if (item.kind === 'code') {
            const boxY = y + item.top;
            const boxHeight = item.height - item.top - item.bottom;
            drawRoundedRect(context, x, boxY, width, boxHeight, 20, '#101828');
            if (item.language) {
                context.fillStyle = '#98a2b3';
                context.font = font(700, 15, MONO_STACK);
                context.fillText(item.language.toLocaleUpperCase(), x + item.boxPadding, boxY + 26);
            }
            drawTextLines(context, item, x + item.boxPadding, boxY + (item.language ? 29 : 14));
            return y + item.height;
        }

        if (item.kind === 'tableRow') {
            const rowY = y + item.top;
            const rowHeight = item.height - item.top - item.bottom;
            drawRoundedRect(
                context,
                x,
                rowY,
                width,
                rowHeight,
                13,
                item.header ? '#e9f0ff' : (item.alternate ? '#f8fafc' : '#ffffff')
            );
            if (!item.header) {
                context.strokeStyle = '#e4e7ec';
                context.lineWidth = 1.5;
                strokeRoundedRect(context, x, rowY, width, rowHeight, 13);
            }
            drawTextLines(context, item, x + 20, rowY + 12);
            return y + item.height;
        }

        if (item.kind === 'list') {
            context.fillStyle = '#3157d5';
            context.font = font(740, 24);
            context.textAlign = 'right';
            context.fillText(item.marker, x + 32, y + item.top + item.lineHeight - 9);
            drawTextLines(context, item, x + 48, y + item.top);
            return y + item.height;
        }

        drawTextLines(context, item, x, y + item.top);
        return y + item.height;
    }

    function drawImageFallbackBox(context, x, y, width, height, label) {
        drawRoundedRect(context, x, y, width, height, 18, '#f7f9fc');
        context.strokeStyle = '#d0d5dd';
        context.lineWidth = 1.5;
        strokeRoundedRect(context, x, y, width, height, 18);

        const iconX = x + 24;
        const iconY = y + Math.max(20, (height - 34) / 2);
        drawRoundedRect(context, iconX, iconY, 34, 34, 8, '#e9f0ff');
        context.fillStyle = '#3157d5';
        context.beginPath();
        context.arc(iconX + 24, iconY + 11, 4, 0, Math.PI * 2);
        context.fill();
        context.beginPath();
        context.moveTo(iconX + 7, iconY + 27);
        context.lineTo(iconX + 15, iconY + 18);
        context.lineTo(iconX + 21, iconY + 24);
        context.lineTo(iconX + 27, iconY + 17);
        context.lineTo(iconX + 30, iconY + 27);
        context.closePath();
        context.fill();

        if (label) {
            context.fillStyle = '#667085';
            context.font = font(620, 18);
            context.textAlign = 'left';
            context.textBaseline = 'middle';
            context.fillText(label, iconX + 48, y + (height / 2));
        }
    }

    function drawTextLines(context, item, x, top) {
        context.fillStyle = item.color;
        context.font = item.font;
        context.textAlign = 'left';
        context.textBaseline = 'alphabetic';
        item.lines.forEach((line, index) => {
            context.fillText(line, x, top + item.lineHeight - 9 + (index * item.lineHeight));
        });
    }

    function drawRoundedRect(context, x, y, width, height, radius, fillStyle) {
        roundedRectPath(context, x, y, width, height, radius);
        context.fillStyle = fillStyle;
        context.fill();
    }

    function strokeRoundedRect(context, x, y, width, height, radius) {
        roundedRectPath(context, x, y, width, height, radius);
        context.stroke();
    }

    function roundedRectPath(context, x, y, width, height, radius) {
        const safeRadius = Math.max(0, Math.min(radius, width / 2, height / 2));
        context.beginPath();
        context.moveTo(x + safeRadius, y);
        context.arcTo(x + width, y, x + width, y + height, safeRadius);
        context.arcTo(x + width, y + height, x, y + height, safeRadius);
        context.arcTo(x, y + height, x, y, safeRadius);
        context.arcTo(x, y, x + width, y, safeRadius);
        context.closePath();
    }

    function canvasToPngBlob(canvas) {
        return new Promise((resolve, reject) => {
            if (typeof canvas.toBlob === 'function') {
                canvas.toBlob((blob) => {
                    if (blob) resolve(blob);
                    else reject(new Error('PNG encoding failed'));
                }, 'image/png');
                return;
            }

            try {
                const dataUrl = canvas.toDataURL('image/png');
                const [header, payload] = dataUrl.split(',');
                const mime = header.match(/^data:([^;]+)/)?.[1] || 'image/png';
                const bytes = globalScope.atob(payload);
                const buffer = new Uint8Array(bytes.length);
                for (let index = 0; index < bytes.length; index += 1) buffer[index] = bytes.charCodeAt(index);
                resolve(new Blob([buffer], { type: mime }));
            } catch (error) {
                reject(error);
            }
        });
    }

    async function renderShareCardBlob(options = {}) {
        const blocks = Array.isArray(options.blocks)
            ? options.blocks
            : parseMarkdownBlocks(String(options.answer || '').trim());
        const loadedImages = await loadShareCardImageAssets(blocks, options);
        try {
            const rendered = renderShareCardCanvas({
                ...options,
                blocks,
                imageAssets: loadedImages.assets,
            });
            const blob = await canvasToPngBlob(rendered.canvas);
            return {
                blob,
                width: rendered.width,
                height: rendered.height,
                truncated: rendered.truncated,
                imageCount: loadedImages.imageCount,
                imageFailedCount: loadedImages.failedCount,
            };
        } finally {
            loadedImages.cleanup();
        }
    }

    function buildShareCardFilename(value = '', now = new Date()) {
        const title = sanitizeInlineText(value)
            .replace(/[\\/:*?"<>|]+/g, '-')
            .replace(/\s+/g, '-')
            .replace(/-+/g, '-')
            .replace(/^[.-]+|[.-]+$/g, '')
            .slice(0, 36);
        const date = now instanceof Date && !Number.isNaN(now.getTime())
            ? [
                now.getFullYear(),
                String(now.getMonth() + 1).padStart(2, '0'),
                String(now.getDate()).padStart(2, '0'),
            ].join('')
            : '';
        return `${title || 'super-chat-answer'}${date ? `-${date}` : ''}.png`;
    }

    return Object.freeze({
        buildShareCardFilename,
        loadShareCardImageAssets,
        parseMarkdownBlocks,
        renderShareCardBlob,
        renderShareCardCanvas,
        resolveShareCardImageFetchUrl,
        sanitizeInlineText,
        wrapMeasuredText,
    });
}));
