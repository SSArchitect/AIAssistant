(function initStreamTypewriter(root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.StreamTypewriter = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, () => {
    'use strict';

    function clamp(value, minimum, maximum) {
        return Math.min(maximum, Math.max(minimum, value));
    }

    function splitGraphemes(value) {
        const text = String(value || '');
        if (!text) return [];
        if (typeof Intl === 'object' && typeof Intl.Segmenter === 'function') {
            const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
            return Array.from(segmenter.segment(text), (item) => item.segment);
        }
        return Array.from(text);
    }

    class AdaptiveStreamBuffer {
        constructor(options = {}) {
            this.onRender = typeof options.onRender === 'function' ? options.onRender : () => {};
            this.onRate = typeof options.onRate === 'function' ? options.onRate : () => {};
            this.now = typeof options.now === 'function'
                ? options.now
                : () => (globalThis.performance?.now?.() ?? Date.now());
            this.schedule = typeof options.schedule === 'function'
                ? options.schedule
                : (callback, delay) => setTimeout(callback, delay);
            this.cancelSchedule = typeof options.cancelSchedule === 'function'
                ? options.cancelSchedule
                : (timer) => clearTimeout(timer);
            this.tickMs = clamp(Number(options.tickMs) || 32, 12, 80);
            this.prebufferChars = clamp(Number(options.prebufferChars) || 8, 1, 48);
            this.prebufferMs = clamp(Number(options.prebufferMs) || 80, 0, 300);
            this.minRate = clamp(Number(options.minRate) || 18, 1, 120);
            this.maxRate = Math.max(this.minRate, Number(options.maxRate) || 180);
            this.maxFinishRate = Math.max(this.maxRate, Number(options.maxFinishRate) || 420);
            this.finishWindowMs = clamp(Number(options.finishWindowMs) || 520, 120, 2000);
            this.initialRate = clamp(Number(options.initialRate) || 48, this.minRate, this.maxRate);
            this.currentRate = this.initialRate;
            this.pending = [];
            this.rendered = '';
            this.receivedUnits = 0;
            this.arrivalRate = null;
            this.arrivalSamples = 0;
            this.arrivalWindow = [];
            this.firstArrivalAt = null;
            this.lastArrivalAt = null;
            this.lastTickAt = null;
            this.budget = 0;
            this.started = false;
            this.closing = false;
            this.finishDeadline = null;
            this.timer = null;
            this.waiters = [];
            this.boundTick = () => {
                this.timer = null;
                this.tick();
            };
        }

        enqueue(value, timestamp = this.now()) {
            const units = splitGraphemes(value);
            if (!units.length) return this.rendered;
            const wasIdle = this.started && this.pending.length === 0 && this.timer === null;

            if (this.firstArrivalAt === null) {
                this.firstArrivalAt = timestamp;
                this.arrivalWindow.push({ timestamp, units: 0 });
            }
            this.receivedUnits += units.length;
            this.arrivalWindow.push({ timestamp, units: this.receivedUnits });
            const cutoff = timestamp - 1200;
            while (this.arrivalWindow.length > 2 && this.arrivalWindow[1].timestamp < cutoff) {
                this.arrivalWindow.shift();
            }
            const baseline = this.arrivalWindow[0];
            const elapsedMs = Math.max(0, timestamp - baseline.timestamp);
            if (elapsedMs >= 160) {
                const sampleRate = clamp(
                    ((this.receivedUnits - baseline.units) * 1000) / elapsedMs,
                    1,
                    this.maxFinishRate * 2,
                );
                this.arrivalRate = this.arrivalRate === null
                    ? sampleRate
                    : (this.arrivalRate * 0.78) + (sampleRate * 0.22);
                this.arrivalSamples += 1;
            }
            this.lastArrivalAt = timestamp;
            this.pending.push(...units);
            // Network streams often pause and then deliver several tokens in one chunk.
            // Do not turn that idle wall time into an immediate display budget burst.
            if (wasIdle) this.lastTickAt = timestamp;
            this.ensureScheduled(0);
            return this.rendered;
        }

        finish(expectedValue = '', timestamp = this.now()) {
            this.reconcileExpected(String(expectedValue || ''));
            this.closing = true;
            this.finishDeadline = timestamp + this.finishWindowMs;

            if (!this.pending.length) {
                this.settle();
                return Promise.resolve(this.rendered);
            }

            const promise = new Promise((resolve) => this.waiters.push(resolve));
            this.ensureScheduled(0);
            return promise;
        }

        setImmediate(value = '') {
            this.reset();
            this.rendered = String(value || '');
            this.receivedUnits = splitGraphemes(this.rendered).length;
            this.onRender(this.rendered);
            return this.rendered;
        }

        reset({ notify = false } = {}) {
            if (this.timer !== null) {
                this.cancelSchedule(this.timer);
                this.timer = null;
            }
            const hadText = Boolean(this.rendered);
            this.pending = [];
            this.rendered = '';
            this.receivedUnits = 0;
            this.arrivalRate = null;
            this.arrivalSamples = 0;
            this.arrivalWindow = [];
            this.firstArrivalAt = null;
            this.lastArrivalAt = null;
            this.lastTickAt = null;
            this.budget = 0;
            this.started = false;
            this.closing = false;
            this.finishDeadline = null;
            this.currentRate = this.initialRate;
            this.resolveWaiters();
            if (notify && hadText) this.onRender('');
        }

        getStats() {
            return {
                pending: this.pending.length,
                rendered: splitGraphemes(this.rendered).length,
                arrivalRate: this.arrivalRate,
                displayRate: this.currentRate,
                closing: this.closing,
            };
        }

        reconcileExpected(expected) {
            const queuedText = this.pending.join('');
            const completeText = this.rendered + queuedText;
            if (completeText === expected) return;

            if (expected.startsWith(this.rendered)) {
                this.pending = splitGraphemes(expected.slice(this.rendered.length));
                return;
            }

            const renderedUnits = splitGraphemes(this.rendered);
            const expectedUnits = splitGraphemes(expected);
            let commonLength = 0;
            while (
                commonLength < renderedUnits.length
                && commonLength < expectedUnits.length
                && renderedUnits[commonLength] === expectedUnits[commonLength]
            ) {
                commonLength += 1;
            }
            const commonText = expectedUnits.slice(0, commonLength).join('');
            if (commonText !== this.rendered) {
                this.rendered = commonText;
                this.onRender(this.rendered);
            }
            this.pending = expectedUnits.slice(commonLength);
        }

        desiredRate(now) {
            const observed = this.arrivalRate ?? this.initialRate;
            let target = clamp(observed * 1.06, this.minRate, this.maxRate);
            const desiredBacklog = Math.max(this.prebufferChars, target * 0.12);
            if (this.pending.length > desiredBacklog) {
                const pressure = (this.pending.length - desiredBacklog) / desiredBacklog;
                target += Math.min(this.maxRate * 0.55, pressure * target * 0.22);
            }
            if (this.closing && this.finishDeadline !== null) {
                const remainingMs = Math.max(this.tickMs, this.finishDeadline - now);
                target = Math.max(target, (this.pending.length * 1000) / remainingMs);
            }
            return clamp(target, this.minRate, this.closing ? this.maxFinishRate : this.maxRate);
        }

        tick() {
            if (!this.pending.length) {
                if (this.closing) this.settle();
                return;
            }

            const now = this.now();
            if (!this.started) {
                const bufferedFor = Math.max(0, now - (this.firstArrivalAt ?? now));
                if (this.pending.length < this.prebufferChars && bufferedFor < this.prebufferMs) {
                    this.ensureScheduled(Math.min(this.tickMs, this.prebufferMs - bufferedFor));
                    return;
                }
                this.started = true;
                this.lastTickAt = now - this.tickMs;
            }

            const elapsedMs = clamp(now - (this.lastTickAt ?? now), 1, 160);
            this.lastTickAt = now;
            const targetRate = this.desiredRate(now);
            this.currentRate = (this.currentRate * 0.7) + (targetRate * 0.3);
            this.budget += (this.currentRate * elapsedMs) / 1000;
            const maxUnitsPerTick = this.closing ? 18 : 8;
            const count = Math.min(this.pending.length, maxUnitsPerTick, Math.floor(this.budget));

            if (count > 0) {
                this.budget -= count;
                this.rendered += this.pending.splice(0, count).join('');
                this.onRender(this.rendered);
            }

            if (this.pending.length) this.ensureScheduled(this.tickMs);
            else if (this.closing) this.settle();
        }

        settle() {
            this.closing = false;
            this.finishDeadline = null;
            if (this.arrivalRate !== null && this.arrivalSamples > 0) {
                this.onRate(clamp(this.arrivalRate, this.minRate, this.maxRate));
            }
            this.resolveWaiters();
        }

        resolveWaiters() {
            const waiters = this.waiters.splice(0);
            waiters.forEach((resolve) => resolve(this.rendered));
        }

        ensureScheduled(delay) {
            if (this.timer !== null) return;
            this.timer = this.schedule(this.boundTick, Math.max(0, delay));
        }
    }

    return {
        AdaptiveStreamBuffer,
        splitGraphemes,
    };
}));
