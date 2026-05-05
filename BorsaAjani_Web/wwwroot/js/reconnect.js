/**
 * BorsaAjani — Blazor SignalR Connection Manager
 * - Custom reconnect overlay control
 * - Server keepalive ping to prevent Railway sleep
 * - Connection state logging
 */

(function () {
    'use strict';

    // ── Overlay element references ────────────────────────────────────────
    const MODAL_ID   = 'components-reconnect-modal';
    const ERROR_ID   = 'blazor-error-ui';

    // ── Reconnect overlay state management ───────────────────────────────
    // Blazor adds CSS classes to #components-reconnect-modal automatically.
    // We watch for class changes to show/hide the inner cards.
    function observeReconnectModal() {
        const modal = document.getElementById(MODAL_ID);
        if (!modal) return;

        const spinnerCard = modal.querySelector('.rc-card:not(.rc-failed-card)');
        const failedCard  = modal.querySelector('.rc-failed-card');

        const observer = new MutationObserver(() => {
            const cls = modal.className;
            if (cls.includes('components-reconnect-failed') ||
                cls.includes('components-reconnect-rejected')) {
                if (spinnerCard) spinnerCard.style.display = 'none';
                if (failedCard)  failedCard.style.display  = 'flex';
            } else {
                if (spinnerCard) spinnerCard.style.display = 'flex';
                if (failedCard)  failedCard.style.display  = 'none';
            }
        });

        observer.observe(modal, { attributes: true, attributeFilter: ['class'] });
    }

    // ── Server keepalive (prevents Railway from sleeping) ─────────────────
    // Pings the backend health endpoint every 4 minutes.
    // Railway free tier sleeps after ~5 min of inactivity.
    function startKeepalive() {
        const PING_INTERVAL_MS = 4 * 60 * 1000; // 4 minutes
        const PING_URL = '/api/ping'; // Blazor server itself — cheap GET

        setInterval(async () => {
            try {
                // Just touch the server; we don't care about the response
                await fetch(PING_URL, { method: 'GET', cache: 'no-store' });
            } catch {
                // Silently ignore — reconnect overlay will appear if SignalR drops
            }
        }, PING_INTERVAL_MS);
    }

    // ── Page visibility — resume check on tab focus ───────────────────────
    // When user returns to tab, Blazor may already be reconnecting.
    // We show a subtle indicator and let Blazor handle the rest.
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            console.log('[BorsaAjani] Tab refocused — connection state:', window.__blazorState ?? 'unknown');
        }
    });

    // ── Init ──────────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        observeReconnectModal();
        startKeepalive();
        console.log('[BorsaAjani] Reconnect manager initialised');
    });

    // ── Blazor lifecycle hooks (optional) ─────────────────────────────────
    // These fire if Blazor exposes them in the current version.
    window.Blazor?.addEventListener?.('enhancedload', () => {
        console.log('[BorsaAjani] Enhanced navigation completed');
    });

})();
