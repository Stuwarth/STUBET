/**
 * Sports AI Predictor v2.0 — Dashboard Application
 * Full-featured dashboard with live data, patterns, news & Telegram
 */

const API_BASE = '/api';

// ==================== STATE ====================
let appState = {
    currentSection: 'dashboard',
    dashboardData: null,
    predictions: [],
    valueBets: [],
    patterns: [],
    liveMatches: [],
    news: [],
    isLoading: false,
};

const LIVE_SCOREBOARD_REFRESH_MS = 10000;
const LIVE_CLOCK_TICK_MS = 1000;
const MATCH_CENTER_REFRESH_MS = 10000;

let liveScoreboardRefreshTimer = null;
let liveClockTickerTimer = null;
let liveScoreboardRequestInFlight = false;

// ==================== INITIALIZATION ====================
function showToast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) {
        console.log(`[Toast] ${type}: ${msg}`);
        return;
    }
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = msg;
    toast.style.padding = '10px 20px';
    toast.style.marginBottom = '10px';
    toast.style.borderRadius = '8px';
    toast.style.color = '#fff';
    toast.style.background = type === 'error' ? 'rgba(239, 68, 68, 0.9)' : (type === 'success' ? 'rgba(16, 185, 129, 0.9)' : 'rgba(59, 130, 246, 0.9)');
    toast.style.boxShadow = '0 4px 6px rgba(0,0,0,0.3)';
    toast.style.transition = 'opacity 0.3s';
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initSettings();
    initDatePickers();
    loadDashboard();
    loadScraperStatus();

    // Call loadSettings safely
    if (typeof loadSettings === 'function') {
        loadSettings();
    }
});

function initNavigation() {
    const navLinks = document.querySelectorAll('.nav-link');
    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const section = link.dataset.section;
            switchSection(section);
        });
    });

    const menuToggle = document.getElementById('menu-toggle');
    if (menuToggle) {
        menuToggle.addEventListener('click', () => {
            document.getElementById('sidebar').classList.toggle('open');
        });
    }
}

function switchSection(section) {
    if (section !== 'live') {
        clearLiveScoreboardAutoRefresh();
        clearLiveClockTicker();
    }

    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    const activeLink = document.querySelector(`[data-section="${section}"]`);
    if (activeLink) activeLink.classList.add('active');

    document.querySelectorAll('.content-section').forEach(s => s.classList.remove('active'));
    const sectionEl = document.getElementById(`section-${section}`);
    if (sectionEl) sectionEl.classList.add('active');

    const titles = {
        dashboard: 'Dashboard',
        live: '🔴 En Vivo',
        predictions: 'Predicciones IA',
        valuebets: 'Value Bets',
        patterns: '🔍 Patrones',
        news: '📰 Noticias & Lesiones',
        performance: 'Rendimiento',
        models: 'Modelos ML',
        settings: 'Configuración',
    };
    document.getElementById('page-title').textContent = titles[section] || section;

    switch (section) {
        case 'dashboard': loadDashboard(); break;
        case 'live': loadLiveScoreboard(); break;
        case 'predictions': loadPredictions(); break;
        case 'valuebets': loadValueBets(); break;
        case 'patterns': break; // Manual trigger
        case 'news': break; // Manual trigger
        case 'performance': loadPerformance(); break;
        case 'models': loadModels(); break;
        case 'settings': loadSettings(); break;
    }

    appState.currentSection = section;
    document.getElementById('sidebar').classList.remove('open');
}

function clearLiveScoreboardAutoRefresh() {
    if (liveScoreboardRefreshTimer) {
        window.clearInterval(liveScoreboardRefreshTimer);
        liveScoreboardRefreshTimer = null;
    }
}

function clearLiveClockTicker() {
    if (liveClockTickerTimer) {
        window.clearInterval(liveClockTickerTimer);
        liveClockTickerTimer = null;
    }
}

function startLiveScoreboardAutoRefresh() {
    clearLiveScoreboardAutoRefresh();

    liveScoreboardRefreshTimer = window.setInterval(async () => {
        if (appState.currentSection !== 'live' || currentSport !== 'soccer') {
            clearLiveScoreboardAutoRefresh();
            return;
        }

        if (liveScoreboardRequestInFlight) {
            return;
        }

        liveScoreboardRequestInFlight = true;
        try {
            await loadLiveScoreboard({ silent: true, manageAutoRefresh: false });
        } finally {
            liveScoreboardRequestInFlight = false;
        }
    }, LIVE_SCOREBOARD_REFRESH_MS);
}

function parseLiveMinuteFromStatusLabel(statusLabel) {
    const raw = String(statusLabel || '').trim();
    if (!raw) return null;

    const normalized = raw.toLowerCase();
    if (/^(ht|ft|ap|aet|et|penalties?)$/.test(normalized)) {
        return null;
    }

    // Avoid false positives like "1st half" / "2nd half" being parsed as minute 1/2.
    if (/(?:1st|2nd|first|second)\s*(?:half|tiempo)|half\s*time|descanso/i.test(raw)) {
        return null;
    }

    let match = raw.match(/(\d{1,3})\s*\+\s*(\d{1,2})\s*'?/);
    if (match) {
        const minute = Number(match[1]);
        const added = Number(match[2] || 0);
        if (!Number.isFinite(minute) || minute <= 0 || minute > 130) return null;

        return {
            minute,
            added: Number.isFinite(added) ? added : 0,
        };
    }

    match = raw.match(/(?:^|\s)(\d{1,3})\s*'(?:\s|$)/);
    if (match) {
        const minute = Number(match[1]);
        if (!Number.isFinite(minute) || minute <= 0 || minute > 130) return null;
        return { minute, added: 0 };
    }

    match = raw.match(/(?:^|\s)(\d{1,3}):(\d{2})(?:\s|$)/);
    if (match) {
        const minute = Number(match[1]);
        if (!Number.isFinite(minute) || minute < 0 || minute > 130) return null;
        return { minute, added: 0 };
    }

    return null;
}

function buildLiveClockMeta(match) {
    const statusType = String(match?.status_type || '').toLowerCase();
    const statusLabel = String(match?.status || 'Programado');
    const parsed = parseLiveMinuteFromStatusLabel(statusLabel);
    const startTs = Number(match?.start_timestamp);
    const nowMs = Date.now();

    let baseMinute = parsed?.minute ?? null;
    const baseAdded = parsed?.added ?? 0;

    if (baseMinute === null && Number.isFinite(startTs) && startTs > 0 && ['inprogress', 'halftime'].includes(statusType)) {
        baseMinute = Math.max(0, Math.floor((Math.floor(nowMs / 1000) - startTs) / 60));
    }

    return {
        statusType,
        statusLabel,
        startTs: Number.isFinite(startTs) && startTs > 0 ? startTs : null,
        baseMinute,
        baseAdded,
        capturedAtMs: nowMs,
    };
}

function resolveLiveClockLabel(meta, nowMs = Date.now()) {
    const statusType = String(meta?.statusType || '').toLowerCase();
    const statusLabel = String(meta?.statusLabel || 'Programado');

    if (['finished', 'afterpens', 'aet'].includes(statusType)) {
        return 'FT';
    }

    if (statusType === 'halftime') {
        return 'HT';
    }

    if (statusType === 'notstarted') {
        const startTs = Number(meta?.startTs);
        if (Number.isFinite(startTs) && startTs > 0) {
            const diffMin = Math.round((startTs - Math.floor(nowMs / 1000)) / 60);
            if (diffMin > 0 && diffMin <= 180) {
                return `Inicia en ${diffMin}m`;
            }
        }
        return statusLabel;
    }

    if (statusType === 'inprogress') {
        let minute = Number(meta?.baseMinute);
        const capturedAtMs = Number(meta?.capturedAtMs);
        const startTs = Number(meta?.startTs);

        if (!Number.isFinite(minute)) {
            if (Number.isFinite(startTs) && startTs > 0) {
                minute = Math.max(1, Math.floor((Math.floor(nowMs / 1000) - startTs) / 60));
            } else {
                return statusLabel || 'LIVE';
            }
        } else if (Number.isFinite(capturedAtMs) && capturedAtMs > 0) {
            minute = minute + Math.floor((nowMs - capturedAtMs) / 60000);
        }

        minute = Math.max(1, Math.min(130, minute));
        return `${minute}'`;
    }

    return statusLabel;
}

function updateLiveClockLabels() {
    const nowMs = Date.now();
    document.querySelectorAll('.live-clock').forEach((clockEl) => {
        const meta = {
            statusType: clockEl.dataset.statusType || '',
            statusLabel: clockEl.dataset.statusLabel || '',
            startTs: clockEl.dataset.startTs,
            baseMinute: clockEl.dataset.baseMinute,
            baseAdded: clockEl.dataset.baseAdded,
            capturedAtMs: clockEl.dataset.capturedAtMs,
        };

        clockEl.textContent = resolveLiveClockLabel(meta, nowMs);
    });
}

function startLiveClockTicker() {
    clearLiveClockTicker();
    updateLiveClockLabels();

    liveClockTickerTimer = window.setInterval(() => {
        if (appState.currentSection !== 'live') {
            clearLiveClockTicker();
            return;
        }
        updateLiveClockLabels();
    }, LIVE_CLOCK_TICK_MS);
}

// ==================== API CALLS ====================
async function apiCall(endpoint, method = 'GET', body = null, requestOptions = {}) {
    try {
        const options = {
            method,
            headers: { 'Content-Type': 'application/json' },
            cache: requestOptions.noCache ? 'no-store' : 'default',
        };
        if (body) options.body = JSON.stringify(body);

        const response = await fetch(`${API_BASE}${endpoint}`, options);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(`API Error (${endpoint}):`, error);
        return null;
    }
}

// ==================== DASHBOARD ====================
async function loadDashboard() {
    const data = await apiCall('/dashboard/real');
    if (!data) { renderEmptyDashboard(); return; }

    appState.dashboardData = data;

    const s = data.summary || {};
    const bk = data.bankroll || {};
    const lp = bk.lasplatas || {};
    const mb = bk.metabet || {};

    // ── Stat cards ──────────────────────────────────
    animateValue('stat-total', 0, s.total_picks || 0, 800);
    document.getElementById('stat-accuracy').textContent = (s.accuracy || 0) + '%';
    document.getElementById('stat-roi').textContent = (s.roi || 0) + '%';
    document.getElementById('stat-valuebets').textContent = s.pending || 0;

    document.getElementById('header-accuracy').textContent = (s.accuracy || 0) + '%';
    const headerRoi = document.getElementById('header-roi');
    headerRoi.textContent = (s.roi || 0) + '%';
    headerRoi.style.color = s.roi >= 0 ? '#10b981' : '#ef4444';

    // Accuracy trend
    const accTrend = document.getElementById('accuracy-trend');
    if (s.accuracy >= 60) {
        accTrend.className = 'stat-card-trend up';
        accTrend.innerHTML = '<span>↑</span> Excelente';
    } else if (s.accuracy >= 50) {
        accTrend.className = 'stat-card-trend';
        accTrend.innerHTML = '<span>→</span> Estable';
    } else if (s.accuracy > 0) {
        accTrend.className = 'stat-card-trend down';
        accTrend.innerHTML = '<span>↓</span> Mejorable';
    } else {
        accTrend.className = 'stat-card-trend';
        accTrend.innerHTML = '<span>—</span>';
    }

    // Total picks trend
    const totalTrend = document.getElementById('stat-total-trend');
    if (totalTrend) {
        totalTrend.textContent = `${s.won || 0}W / ${s.lost || 0}L`;
    }

    // ROI trend
    const roiTrend = document.getElementById('roi-trend');
    if (roiTrend) {
        const p = s.profit || 0;
        roiTrend.className = p >= 0 ? 'stat-card-trend up' : 'stat-card-trend down';
        roiTrend.innerHTML = `<span>${p >= 0 ? '↑' : '↓'}</span> Bs ${p >= 0 ? '+' : ''}${p.toFixed(0)}`;
    }

    // Pending trend
    const vbTrend = document.getElementById('vb-trend');
    if (vbTrend) {
        vbTrend.innerHTML = `<span>⏳</span> <span>Por resolver</span>`;
    }

    // ── Bankroll cards in performance ─────────────────────
    const lpEl = document.getElementById('bankroll-lp');
    if (lpEl) {
        lpEl.textContent = lp.current > 0 ? `Bs ${lp.current.toFixed(2)}` : 'Por fijar';
    }
    const mbEl = document.getElementById('bankroll-mb');
    if (mbEl) {
        mbEl.textContent = mb.current > 0 ? `Bs ${mb.current.toFixed(2)}` : 'Por fijar';
    }
    const lpProfit = document.getElementById('lp-monthly-profit');
    if (lpProfit) {
        const d = lp.diff || 0;
        lpProfit.textContent = `Bs ${d >= 0 ? '+' : ''}${d.toFixed(2)}`;
        lpProfit.style.color = d >= 0 ? '#10b981' : '#ef4444';
    }
    const mbProfit = document.getElementById('mb-monthly-profit');
    if (mbProfit) {
        const d = mb.diff || 0;
        mbProfit.textContent = `Bs ${d >= 0 ? '+' : ''}${d.toFixed(2)}`;
        mbProfit.style.color = d >= 0 ? '#f59e0b' : '#ef4444';
    }

    // ── Streak ────────────────────────────────────────
    const streakEl = document.getElementById('streak-display');
    if (streakEl) {
        if (s.streak_count > 0 && s.streak_type) {
            streakEl.textContent = `${s.streak_count} ${s.streak_type === 'WON' ? '🟢 Ganadas' : '🔴 Perdidas'}`;
            streakEl.style.color = s.streak_type === 'WON' ? '#10b981' : '#ef4444';
        } else {
            streakEl.textContent = '—';
        }
    }

    // ── Profit ───────────────────────────────────────
    const profitEl = document.getElementById('profit-display');
    if (profitEl) {
        const p = s.profit || 0;
        profitEl.textContent = `Bs ${p >= 0 ? '+' : ''}${p.toFixed(0)}`;
        profitEl.style.color = p >= 0 ? '#10b981' : '#ef4444';
    }

    // ── Recent picks table ─────────────────────
    renderRecentPicksInDashboard(data.recent_picks || []);

    // ── Charts ─────────────────────
    renderBookmakerChart(data.bookmaker_stats || {});
    drawProfitChart(data.profit_chart || []);
}

function renderEmptyDashboard() {
    document.getElementById('stat-total').textContent = '0';
    document.getElementById('stat-accuracy').textContent = '—';
    document.getElementById('stat-roi').textContent = '—';
    document.getElementById('stat-valuebets').textContent = '0';
    document.getElementById('recent-predictions-body').innerHTML = `
        <tr><td colspan="8" class="empty-state"><div style="padding: 2rem;">
            &#128181; Sin apuestas registradas — Ve a <strong>Rend. & Bankroll</strong> para agregar picks
        </div></td></tr>
    `;
}

// Dashboard recent picks table
function renderRecentPicksInDashboard(picks) {
    const tbody = document.getElementById('recent-predictions-body');
    if (!tbody) return;

    if (!picks || picks.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty-state">
            <div style="padding:2rem;">
                &#128181; Sin apuestas registradas este mes —
                Ve a <strong>Rend. & Bankroll</strong> para agregar picks
            </div></td></tr>`;
        return;
    }

    const BK_COLORS = { lasplatas: '#10b981', metabet: '#f59e0b' };

    tbody.innerHTML = picks.map(p => {
        const date = p.date
            ? new Date(p.date).toLocaleDateString('es',
                {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'})
            : '—';

        const bkColor = BK_COLORS[p.bookmaker] || '#94a3b8';
        const bkLabel = p.bookmaker === 'metabet' ? 'MB' : 'LP';

        let resultHtml = '<span class="badge badge-info">&#9203; Pendiente</span>';
        if (p.result === 'WON') {
            const ganancia = ((p.stake * p.odds) - p.stake).toFixed(1);
            resultHtml = `<span class="badge badge-success">&#9989; +Bs${ganancia}</span>`;
        } else if (p.result === 'LOST') {
            resultHtml = `<span class="badge badge-danger">&#10060; -Bs${p.stake}</span>`;
        }

        return `<tr>
            <td style="font-size:0.75rem;">${date}</td>
            <td><span style="color:${bkColor};font-weight:700;font-size:0.75rem;">${bkLabel}</span></td>
            <td style="font-weight:600;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${p.match || '—'}</td>
            <td style="font-size:0.8rem;color:var(--text-secondary);">${p.market || '—'}</td>
            <td style="font-family:var(--font-mono);color:var(--accent-primary);font-weight:700;">${p.odds || '—'}</td>
            <td style="font-family:var(--font-mono);">Bs ${p.stake || 0}</td>
            <td>${resultHtml}</td>
            <td>
                <button class="btn btn-sm btn-secondary"
                    onclick="switchSection('performance')"
                    style="font-size:0.7rem;padding:2px 8px;">
                    Ver todo
                </button>
            </td>
        </tr>`;
    }).join('');
}

// Bookmaker profit chart (replaces old market accuracy chart)
function renderBookmakerChart(bkStats) {
    const canvas = document.getElementById('market-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = 280 * dpr;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = '280px';
    ctx.scale(dpr, dpr);
    const w = rect.width;
    const h = 280;
    ctx.clearRect(0, 0, w, h);

    const bks = Object.entries(bkStats || {});
    if (bks.length === 0) {
        ctx.fillStyle = '#64748b';
        ctx.font = '14px Sora';
        ctx.textAlign = 'center';
        ctx.fillText('Sin apuestas registradas este mes', w / 2, h / 2);
        return;
    }

    const colors = { lasplatas: '#10b981', metabet: '#f59e0b' };
    const barW = Math.min(120, (w - 100) / bks.length - 30);
    const maxProfit = Math.max(...bks.map(([, s]) => Math.abs(s.profit || 0)), 1);
    const chartH = h - 100;
    const centerY = h / 2;
    const startX = (w - bks.length * (barW + 30)) / 2;

    // Center line (zero line)
    ctx.strokeStyle = 'rgba(255,255,255,0.1)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(30, centerY);
    ctx.lineTo(w - 30, centerY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Zero label
    ctx.fillStyle = '#64748b';
    ctx.font = '10px "JetBrains Mono"';
    ctx.textAlign = 'right';
    ctx.fillText('Bs 0', 28, centerY + 4);

    bks.forEach(([bk, stats], i) => {
        const x = startX + i * (barW + 30);
        const profit = stats.profit || 0;
        const barH = Math.max(4, (Math.abs(profit) / maxProfit) * (chartH / 2 - 20));
        const color = colors[bk] || '#6366f1';

        const gradient = ctx.createLinearGradient(x, 0, x, h);
        gradient.addColorStop(0, color + 'dd');
        gradient.addColorStop(1, color + '44');
        ctx.fillStyle = gradient;

        if (profit >= 0) {
            roundedRect(ctx, x, centerY - barH, barW, barH, 6);
        } else {
            roundedRect(ctx, x, centerY, barW, barH, 6);
        }
        ctx.fill();

        // Profit text
        ctx.fillStyle = profit >= 0 ? color : '#ef4444';
        ctx.font = 'bold 13px "JetBrains Mono"';
        ctx.textAlign = 'center';
        const profitText = `${profit >= 0 ? '+' : ''}Bs${profit.toFixed(0)}`;
        ctx.fillText(profitText, x + barW / 2, profit >= 0 ? centerY - barH - 8 : centerY + barH + 18);

        // Bookmaker name
        ctx.fillStyle = '#94a3b8';
        ctx.font = '11px Sora';
        ctx.fillText(bk === 'lasplatas' ? 'LasPlatas' : 'Metabet', x + barW / 2, h - 15);

        // W/L stats
        ctx.font = '10px "JetBrains Mono"';
        ctx.fillStyle = '#64748b';
        ctx.fillText(`${stats.won}W / ${stats.lost}L`, x + barW / 2, h - 30);
    });
}

// Accumulated profit chart (replaces old daily accuracy chart)
function drawProfitChart(profitData) {
    const canvas = document.getElementById('daily-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = 280 * dpr;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = '280px';
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = 280;
    ctx.clearRect(0, 0, w, h);

    if (!profitData || profitData.length === 0) {
        ctx.fillStyle = '#64748b';
        ctx.font = '14px Sora';
        ctx.textAlign = 'center';
        ctx.fillText('Sin datos de profit — Registra y resuelve picks', w / 2, h / 2);
        return;
    }

    const padding = { top: 30, right: 20, bottom: 50, left: 60 };
    const chartW = w - padding.left - padding.right;
    const chartH = h - padding.top - padding.bottom;

    const profits = profitData.map(d => d.profit);
    const maxP = Math.max(...profits, 0);
    const minP = Math.min(...profits, 0);
    const range = Math.max(maxP - minP, 1);
    const yScale = chartH / range;

    // Grid lines
    const steps = 4;
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.lineWidth = 1;
    ctx.font = '10px "JetBrains Mono"';
    ctx.textAlign = 'right';
    for (let i = 0; i <= steps; i++) {
        const val = maxP - (range / steps) * i;
        const y = padding.top + (maxP - val) * yScale;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(w - padding.right, y);
        ctx.stroke();
        ctx.fillStyle = '#64748b';
        ctx.fillText(`Bs${val >= 0 ? '+' : ''}${val.toFixed(0)}`, padding.left - 8, y + 4);
    }

    // Zero line
    const zeroY = padding.top + maxP * yScale;
    ctx.strokeStyle = 'rgba(245,158,11,0.4)';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(padding.left, zeroY);
    ctx.lineTo(w - padding.right, zeroY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Data points
    const points = profitData.map((d, i) => ({
        x: padding.left + (i / (profitData.length - 1 || 1)) * chartW,
        y: padding.top + (maxP - d.profit) * yScale,
        profit: d.profit,
        date: d.date,
    }));

    if (points.length > 1) {
        // Fill area
        const lastProfit = points[points.length - 1].profit;
        const fillColor = lastProfit >= 0 ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)';
        const lineColor = lastProfit >= 0 ? '#10b981' : '#ef4444';

        const gradient = ctx.createLinearGradient(0, padding.top, 0, h - padding.bottom);
        gradient.addColorStop(0, fillColor);
        gradient.addColorStop(1, 'rgba(0,0,0,0)');

        ctx.beginPath();
        ctx.moveTo(points[0].x, zeroY);
        points.forEach(p => ctx.lineTo(p.x, p.y));
        ctx.lineTo(points[points.length - 1].x, zeroY);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();

        // Line
        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        for (let i = 1; i < points.length; i++) {
            const xc = (points[i].x + points[i - 1].x) / 2;
            const yc = (points[i].y + points[i - 1].y) / 2;
            ctx.quadraticCurveTo(points[i - 1].x, points[i - 1].y, xc, yc);
        }
        ctx.lineTo(points[points.length - 1].x, points[points.length - 1].y);
        ctx.strokeStyle = lineColor;
        ctx.lineWidth = 2.5;
        ctx.stroke();

        // Dots
        points.forEach(p => {
            ctx.beginPath();
            ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
            ctx.fillStyle = p.profit >= 0 ? '#10b981' : '#ef4444';
            ctx.fill();
            ctx.strokeStyle = '#0a0e1a';
            ctx.lineWidth = 2;
            ctx.stroke();
        });
    }

    // Date labels
    const labelStep = Math.max(1, Math.floor(points.length / 8));
    points.forEach((p, i) => {
        if (i % labelStep === 0 || i === points.length - 1) {
            ctx.fillStyle = '#64748b';
            ctx.font = '9px "JetBrains Mono"';
            ctx.textAlign = 'center';
            const dateStr = p.date ? p.date.split('-').slice(1).join('/') : '';
            ctx.fillText(dateStr, p.x, h - padding.bottom + 18);
        }
    });
}

// Keep old functions as no-ops for backward compatibility
function drawMarketChart() {}
function drawDailyChart() {}

// Helper para obtener YYYY-MM-DD en la zona local del usuario
function getLocalDateString(dateObj = new Date()) {
    const offset = dateObj.getTimezoneOffset() * 60000;
    return new Date(dateObj.getTime() - offset).toISOString().split('T')[0];
}

function initDatePickers() {
    const today = new Date().toISOString().split('T')[0];

    const liveDateInput = document.getElementById('live-date-filter');
    if (liveDateInput) liveDateInput.value = today;

    const globalDateInput = document.getElementById('global-date-filter');
    if (globalDateInput) globalDateInput.value = today;
}

function handleFilterChange() {
    if (typeof currentSport !== 'undefined' && currentSport !== 'soccer') {
        loadMultisportScoreboard(currentSport);
    } else {
        loadLiveScoreboard();
    }
}

function changeScoreboardDate(delta) {
    const dateInput = document.getElementById('live-date-filter');
    if (!dateInput) return;
    const current = new Date(dateInput.value + 'T12:00:00');
    current.setDate(current.getDate() + delta);
    dateInput.value = current.toISOString().split('T')[0];
    handleFilterChange();
}

function setScoreboardToday() {
    const dateInput = document.getElementById('live-date-filter');
    if (!dateInput) return;
    dateInput.value = new Date().toISOString().split('T')[0];
    handleFilterChange();
}

function getSelectedDateESPN() {
    const dateInput = document.getElementById('live-date-filter');
    if (!dateInput || !dateInput.value) return null;
    // ESPN expects YYYYMMDD format
    return dateInput.value.replace(/-/g, '');
}

function isSofascorePenaltyStatus(match) {
    const sourceName = String(match?.source || '').toLowerCase();
    if (sourceName !== 'sofascore') {
        return false;
    }

    const statusType = String(match?.status_type || '').toLowerCase();
    const statusText = String(match?.status || '');
    const statusTextNorm = statusText.trim().toLowerCase();
    const statusCode = Number(match?.status_code);
    return statusType === 'afterpens'
        || /penalt/i.test(statusText)
        || statusTextNorm === 'ap'
        || (Number.isFinite(statusCode) && [50, 120].includes(statusCode));
}

function getDerivedPenaltyFromTeamScore(team) {
    const current = readIntOrNull(team?.score_current);
    const display = readIntOrNull(team?.score_display);
    if (current === null || display === null || current <= display) {
        return null;
    }
    return current - display;
}

async function hydratePenaltyShootoutMatches(matches) {
    if (!Array.isArray(matches) || matches.length === 0) {
        return;
    }

    const candidates = matches.filter((match) => {
        if (!isSofascorePenaltyStatus(match)) {
            return false;
        }

        const eventId = Number(match?.event_id || match?.id);
        if (!Number.isFinite(eventId) || eventId <= 0) {
            return false;
        }

        const shootout = match?.penalty_shootout && typeof match.penalty_shootout === 'object' ? match.penalty_shootout : {};
        const home = match?.home_team && typeof match.home_team === 'object' ? match.home_team : {};
        const away = match?.away_team && typeof match.away_team === 'object' ? match.away_team : {};

        const homePen = readIntOrNull(shootout?.home)
            ?? readIntOrNull(home?.penalties)
            ?? getDerivedPenaltyFromTeamScore(home);
        const awayPen = readIntOrNull(shootout?.away)
            ?? readIntOrNull(away?.penalties)
            ?? getDerivedPenaltyFromTeamScore(away);

        const hasRegularScore = readIntOrNull(home?.score_display) !== null && readIntOrNull(away?.score_display) !== null;
        const penaltiesMissing = homePen === null || awayPen === null;
        const scoreLooksCombined = (homePen === 0 && awayPen === 0)
            && (readIntOrNull(home?.score) ?? 0) >= 3
            && (readIntOrNull(away?.score) ?? 0) >= 3;

        return penaltiesMissing || scoreLooksCombined || !hasRegularScore;
    });

    if (candidates.length === 0) {
        return;
    }

    const limited = candidates.slice(0, 6);
    await Promise.allSettled(limited.map(async (match) => {
        const eventId = Number(match?.event_id || match?.id);
        if (!Number.isFinite(eventId) || eventId <= 0) {
            return;
        }

        const payload = await apiCall(
            `/sofascore/event/${eventId}/match-center?history_limit=5&enrich_history_stats=false&include_history_statistics=false&_ts=${Date.now()}`,
            'GET',
            null,
            { noCache: true },
        );

        const eventObj = payload && typeof payload.event === 'object' ? payload.event : null;
        if (!eventObj) {
            return;
        }

        const homeScoreBlock = eventObj.homeScore && typeof eventObj.homeScore === 'object' ? eventObj.homeScore : {};
        const awayScoreBlock = eventObj.awayScore && typeof eventObj.awayScore === 'object' ? eventObj.awayScore : {};

        const homeDisplay = readIntOrNull(homeScoreBlock.display) ?? readIntOrNull(homeScoreBlock.normaltime);
        const awayDisplay = readIntOrNull(awayScoreBlock.display) ?? readIntOrNull(awayScoreBlock.normaltime);
        const homeCurrent = readIntOrNull(homeScoreBlock.current);
        const awayCurrent = readIntOrNull(awayScoreBlock.current);

        let homePen = readIntOrNull(homeScoreBlock.penalties);
        let awayPen = readIntOrNull(awayScoreBlock.penalties);

        if (homePen === null && homeCurrent !== null && homeDisplay !== null && homeCurrent >= homeDisplay) {
            homePen = homeCurrent - homeDisplay;
        }
        if (awayPen === null && awayCurrent !== null && awayDisplay !== null && awayCurrent >= awayDisplay) {
            awayPen = awayCurrent - awayDisplay;
        }

        const statusType = String(eventObj?.status?.type || match?.status_type || '').toLowerCase();

        if (!match.home_team || typeof match.home_team !== 'object') {
            match.home_team = {};
        }
        if (!match.away_team || typeof match.away_team !== 'object') {
            match.away_team = {};
        }

        if (homeDisplay !== null) {
            match.home_team.score = homeDisplay;
            match.home_team.score_display = homeDisplay;
        }
        if (awayDisplay !== null) {
            match.away_team.score = awayDisplay;
            match.away_team.score_display = awayDisplay;
        }
        if (homeCurrent !== null) {
            match.home_team.score_current = homeCurrent;
        }
        if (awayCurrent !== null) {
            match.away_team.score_current = awayCurrent;
        }
        if (homePen !== null) {
            match.home_team.penalties = homePen;
        }
        if (awayPen !== null) {
            match.away_team.penalties = awayPen;
        }

        match.penalty_shootout = {
            is_active: true,
            is_ongoing: statusType === 'inprogress',
            home: homePen ?? 0,
            away: awayPen ?? 0,
        };
    }));
}

async function loadLiveScoreboard(options = {}) {
    const silent = Boolean(options?.silent);
    const manageAutoRefresh = options?.manageAutoRefresh !== false;

    const league = document.getElementById('live-league-filter')?.value || 'eng.1';
    const grid = document.getElementById('live-matches-grid');
    const dateESPN = getSelectedDateESPN();
    const dateInput = document.getElementById('live-date-filter');
    const displayDate = dateInput?.value ? new Date(dateInput.value + 'T12:00:00').toLocaleDateString('es', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }) : 'Hoy';

    if (!silent) {
        grid.innerHTML = `<div class="loading-inline"><div class="spinner-sm"></div> Cargando partidos del ${displayDate} de ESPN...</div>`;
    }

    let url = `/live/scoreboard/${league}`;
    if (dateESPN) url += `?date=${dateESPN}`;
    url += (url.includes('?') ? '&' : '?') + `_ts=${Date.now()}`;

    const data = await apiCall(url, 'GET', null, { noCache: true });

    if (!data || !data.matches || data.matches.length === 0) {
        appState.liveMatches = [];
        clearLiveClockTicker();
        grid.innerHTML = `
            <div class="empty-state glass-card">
                <span style="font-size:3rem;">&#128237;</span>
                <p>No hay partidos para <strong>${displayDate}</strong> en esta liga</p>
                <p style="opacity:0.6;">Prueba con otra fecha o liga</p>
                <div style="display:flex; gap:0.5rem; margin-top:1rem;">
                    <button class="btn btn-sm btn-secondary" onclick="changeScoreboardDate(-1)">&#9664; Día Anterior</button>
                    <button class="btn btn-sm btn-accent" onclick="setScoreboardToday()">&#128197; Hoy</button>
                    <button class="btn btn-sm btn-secondary" onclick="changeScoreboardDate(1)">Día Siguiente &#9654;</button>
                </div>
            </div>`;
        if (manageAutoRefresh) {
            startLiveScoreboardAutoRefresh();
        }
        return;
    }

    const matches = Array.isArray(data.matches) ? [...data.matches] : [];
    await hydratePenaltyShootoutMatches(matches);

    appState.liveMatches = matches;
    appState.liveMatchesSearchDate = displayDate;

    // Check if it's Sofascore global to show the sub-filter
    const subfilterContainer = document.getElementById('sofascore-subfilter-container');
    const sourceIndicator = document.getElementById('source-indicator');
    if (league === 'sofascore_all') {
        if (sourceIndicator) sourceIndicator.textContent = 'Datos en tiempo real de Sofascore';
        if (subfilterContainer) {
            subfilterContainer.style.display = 'flex';

            // Extract unique leagues
            const leagues = new Set();
            matches.forEach(m => {
                if (m.league) leagues.add(m.league);
            });

            const selectEl = document.getElementById('sofascore-league-select');
            let optionsHtml = '<option value="ALL">🗓️ Mostrar Todos</option>';
            // sort alphabetically
            Array.from(leagues).sort().forEach(l => {
                optionsHtml += `<option value="${l}">${l}</option>`;
            });
            selectEl.innerHTML = optionsHtml;
            selectEl.value = 'ALL';
        }
    } else {
        if (sourceIndicator) sourceIndicator.textContent = 'Datos en tiempo real de ESPN';
        if (subfilterContainer) subfilterContainer.style.display = 'none';
    }

    renderLiveMatchesFromState();
    startLiveClockTicker();
    if (manageAutoRefresh) {
        startLiveScoreboardAutoRefresh();
    }
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatMatchDateTime(match) {
    const startTimestamp = Number(match.start_timestamp);
    let dateValue = null;

    if (Number.isFinite(startTimestamp) && startTimestamp > 0) {
        dateValue = new Date(startTimestamp * 1000);
    } else if (match.date) {
        dateValue = new Date(match.date);
    }

    if (!dateValue || Number.isNaN(dateValue.getTime())) {
        return '';
    }

    return dateValue.toLocaleDateString('es', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function getLiveStatusMeta(match) {
    const statusText = String(match.status || 'Programado');
    const statusType = String(match.status_type || '').toLowerCase();

    if (statusType === 'inprogress' || statusType === 'halftime' || /progress|half|live|en juego/i.test(statusText)) {
        return { className: 'live', label: statusText || 'En juego' };
    }

    if (['finished', 'afterpens', 'aet'].includes(statusType) || /^\s*ap\s*$/i.test(statusText) || /final|full|terminado/i.test(statusText)) {
        return { className: 'finished', label: statusText || 'Final' };
    }

    return { className: 'scheduled', label: statusText || 'Programado' };
}

function readIntOrNull(value) {
    if (value === null || value === undefined) {
        return null;
    }
    if (typeof value === 'string' && value.trim() === '') {
        return null;
    }
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
        return null;
    }
    return Math.max(0, Math.trunc(numeric));
}

function resolveLiveTeamScore(team, penaltyValue = null) {
    const displayScore = readIntOrNull(team?.score_display);
    if (displayScore !== null) {
        return displayScore;
    }

    const normaltimeScore = readIntOrNull(team?.score_normaltime);
    if (normaltimeScore !== null) {
        return normaltimeScore;
    }

    const rawScore = readIntOrNull(team?.score);
    const currentScore = readIntOrNull(team?.score_current);
    const penalties = readIntOrNull(penaltyValue);

    if (penalties !== null) {
        if (currentScore !== null && currentScore >= penalties) {
            return currentScore - penalties;
        }
        if (rawScore !== null && rawScore >= penalties && (currentScore === null || rawScore === currentScore)) {
            return rawScore - penalties;
        }
    }

    if (rawScore !== null) {
        return rawScore;
    }
    if (currentScore !== null) {
        return currentScore;
    }
    return '—';
}

function getPenaltyShootoutMeta(match, homeTeam = {}, awayTeam = {}) {
    const shootout = match && typeof match.penalty_shootout === 'object' ? match.penalty_shootout : {};
    const sourceName = String(match?.source || '').toLowerCase();
    const statusType = String(match?.status_type || '').toLowerCase();
    const statusText = String(match?.status || '');
    const statusTextNorm = statusText.trim().toLowerCase();
    const statusCode = Number(match?.status_code);

    const statusIndicatesShootout = sourceName === 'sofascore' && (
        statusType === 'afterpens'
        || /penalt/i.test(statusText)
        || statusTextNorm === 'ap'
        || (Number.isFinite(statusCode) && [50, 120].includes(statusCode))
    );

    let explicitHomePen = readIntOrNull(shootout?.home) ?? readIntOrNull(homeTeam?.penalties);
    let explicitAwayPen = readIntOrNull(shootout?.away) ?? readIntOrNull(awayTeam?.penalties);

    const homeCurrent = readIntOrNull(homeTeam?.score_current);
    const awayCurrent = readIntOrNull(awayTeam?.score_current);
    const homeDisplay = readIntOrNull(homeTeam?.score_display);
    const awayDisplay = readIntOrNull(awayTeam?.score_display);

    if (statusIndicatesShootout && explicitHomePen === null && homeCurrent !== null && homeDisplay !== null && homeCurrent > homeDisplay) {
        explicitHomePen = homeCurrent - homeDisplay;
    }
    if (statusIndicatesShootout && explicitAwayPen === null && awayCurrent !== null && awayDisplay !== null && awayCurrent > awayDisplay) {
        explicitAwayPen = awayCurrent - awayDisplay;
    }

    const hasExplicitPenalties = explicitHomePen !== null || explicitAwayPen !== null;

    const active = Boolean(shootout?.is_active) || hasExplicitPenalties || statusIndicatesShootout;
    if (!active) {
        return { active: false, ongoing: false, home: null, away: null };
    }

    return {
        active: true,
        ongoing: Boolean(shootout?.is_ongoing) || statusType === 'inprogress',
        home: explicitHomePen ?? 0,
        away: explicitAwayPen ?? 0,
    };
}

function getLineupWindowTag(match) {
    const statusType = String(match.status_type || '').toLowerCase();
    const countdown = Number(match.lineup_countdown_minutes);
    const inWindow = Boolean(match.lineup_window_open);

    if (statusType !== 'notstarted') {
        return null;
    }

    if (inWindow || (Number.isFinite(countdown) && countdown <= 75 && countdown >= -15)) {
        return { className: 'lineup-soon', label: 'XI a confirmar (~1h)' };
    }

    if (Number.isFinite(countdown) && countdown > 75) {
        return { className: 'lineup-probable', label: 'XI probable' };
    }

    return null;
}

function getResultFormDots(formValue) {
    return String(formValue || '')
        .split('')
        .slice(0, 5)
        .map((result) => {
            if (result === 'W') return '<span class="form-dot win"></span>';
            if (result === 'D') return '<span class="form-dot draw"></span>';
            if (result === 'L') return '<span class="form-dot loss"></span>';
            return '';
        })
        .join('');
}

function renderLiveMatchCard(match) {
    const home = match.home_team || {};
    const away = match.away_team || {};
    const selectedLeague = document.getElementById('live-league-filter')?.value || '';
    const isSofascore = String(match.source || '').toLowerCase() === 'sofascore' || selectedLeague === 'sofascore_all';

    const statusMeta = getLiveStatusMeta(match);
    const lineupTag = getLineupWindowTag(match);
    const dateLabel = formatMatchDateTime(match);
    const clockMeta = buildLiveClockMeta(match);

    const homeName = home.name || home.short_name || '?';
    const awayName = away.name || away.short_name || '?';
    const homeLogo = home.logo || (home.id ? `https://api.sofascore.app/api/v1/team/${home.id}/image` : '');
    const awayLogo = away.logo || (away.id ? `https://api.sofascore.app/api/v1/team/${away.id}/image` : '');
    const homeForm = getResultFormDots(home.form);
    const awayForm = getResultFormDots(away.form);

    const penaltyMeta = getPenaltyShootoutMeta(match, home, away);
    const homeScore = resolveLiveTeamScore(home, penaltyMeta.home);
    const awayScore = resolveLiveTeamScore(away, penaltyMeta.away);

    const safeHomeName = encodeURIComponent(homeName);
    const safeAwayName = encodeURIComponent(awayName);
    const safeEventId = Number(match.event_id || match.id);

    const matchCenterButton = isSofascore && Number.isFinite(safeEventId)
        ? `<button class="btn btn-sm btn-primary" onclick="openSofascoreMatchCenter(${safeEventId})">&#9917; Match Center</button>`
        : '';

    const roundLabel = match.round ? `<span class="live-meta-pill">${escapeHtml(String(match.round))}</span>` : '';
    const venueLabel = match.venue ? `<span class="live-meta-pill">${escapeHtml(String(match.venue))}</span>` : '';
    const lineupLabel = lineupTag ? `<span class="lineup-tag ${lineupTag.className}">${escapeHtml(lineupTag.label)}</span>` : '';

    const deepAnalysisButton = Number.isFinite(safeEventId)
        && Number.isFinite(Number(home.id)) && Number.isFinite(Number(away.id))
        && Number(home.id) > 0 && Number(away.id) > 0
        ? `<button class="btn btn-sm" style="background:linear-gradient(135deg, #f59e0b, #ef4444); color:white; border:none;" onclick="getDeepAnalysis(${safeEventId}, ${Number(home.id)}, ${Number(away.id)}, decodeURIComponent(this.dataset.home), decodeURIComponent(this.dataset.away))" data-home="${safeHomeName}" data-away="${safeAwayName}">&#128293; Analizar Top</button>`
        : '';

    return `
        <div class="live-match-card glass-card ${statusMeta.className}">
            <div class="live-match-header">
                <div class="live-match-status-wrap">
                    <span class="live-status ${statusMeta.className}">${escapeHtml(statusMeta.label)}</span>
                    ${lineupLabel}
                </div>
                <div class="live-time-wrap">
                    <span
                        class="live-clock ${statusMeta.className}"
                        data-status-type="${escapeHtml(String(clockMeta.statusType || ''))}"
                        data-status-label="${escapeHtml(String(clockMeta.statusLabel || ''))}"
                        data-start-ts="${escapeHtml(String(clockMeta.startTs ?? ''))}"
                        data-base-minute="${escapeHtml(String(clockMeta.baseMinute ?? ''))}"
                        data-base-added="${escapeHtml(String(clockMeta.baseAdded ?? ''))}"
                        data-captured-at-ms="${escapeHtml(String(clockMeta.capturedAtMs ?? ''))}"
                    >${escapeHtml(resolveLiveClockLabel(clockMeta))}</span>
                    <span class="live-date">${escapeHtml(dateLabel)}</span>
                </div>
            </div>

            <div class="live-match-body">
                <div class="live-team">
                    ${homeLogo ? `<img src="${homeLogo}" alt="${escapeHtml(homeName)}" class="team-logo" onerror="this.style.display='none'">` : '<div class="team-logo team-logo-fallback"></div>'}
                    <div class="team-main">
                        <span class="team-name">${escapeHtml(homeName)}</span>
                        <span class="team-form">${homeForm || '<span class="form-empty">Sin forma</span>'}</span>
                    </div>
                </div>

                <div class="live-score">
                    <div class="live-score-main">
                        <span class="score-num">${escapeHtml(String(homeScore))}</span>
                        <span class="score-separator">:</span>
                        <span class="score-num">${escapeHtml(String(awayScore))}</span>
                    </div>
                    ${penaltyMeta.active ? `
                        <div class="live-penalties-row ${penaltyMeta.ongoing ? 'ongoing' : ''}" title="Tanda de penales">
                            <span class="live-penalties-label">Pen</span>
                            <span class="live-penalties-score">${escapeHtml(String(penaltyMeta.home))} - ${escapeHtml(String(penaltyMeta.away))}</span>
                        </div>
                    ` : ''}
                </div>

                <div class="live-team away">
                    ${awayLogo ? `<img src="${awayLogo}" alt="${escapeHtml(awayName)}" class="team-logo" onerror="this.style.display='none'">` : '<div class="team-logo team-logo-fallback"></div>'}
                    <div class="team-main">
                        <span class="team-name">${escapeHtml(awayName)}</span>
                        <span class="team-form">${awayForm || '<span class="form-empty">Sin forma</span>'}</span>
                    </div>
                </div>
            </div>

            <div class="live-match-footer">
                ${roundLabel}
                ${venueLabel}
            </div>

            <div class="live-match-actions">
                ${matchCenterButton}
                ${deepAnalysisButton}
                <button
                    class="btn btn-sm btn-secondary"
                    data-home="${safeHomeName}"
                    data-away="${safeAwayName}"
                    onclick="getMatchContext(decodeURIComponent(this.dataset.home), decodeURIComponent(this.dataset.away))"
                >🧠 Contexto IA</button>
            </div>
        </div>
    `;
}

function renderLiveMatchesFromState() {
    const grid = document.getElementById('live-matches-grid');
    const matches = appState.liveMatches || [];
    const displayDate = appState.liveMatchesSearchDate || 'Hoy';

    let filteredMatches = matches;
    const subfilterContainer = document.getElementById('sofascore-subfilter-container');
    if (subfilterContainer && subfilterContainer.style.display !== 'none') {
        const selectedSubLeague = document.getElementById('sofascore-league-select').value;
        if (selectedSubLeague !== 'ALL') {
            filteredMatches = matches.filter((m) => m.league === selectedSubLeague);
        }
    }

    const countEl = document.getElementById('sofascore-match-count');
    if (countEl) countEl.textContent = `${filteredMatches.length} partidos`;

    let headerHtml = `
        <div class="live-date-header glass-card">
            <div class="live-date-main">
                <span class="live-date-icon">&#128197;</span>
                <div>
                    <div class="live-date-title">${escapeHtml(displayDate)}</div>
                    <div class="live-date-subtitle">${filteredMatches.length} partido(s) mostrado(s)</div>
                </div>
            </div>
            <div class="live-date-actions">
                <button class="btn btn-sm btn-secondary" onclick="changeScoreboardDate(-1)">â—€</button>
                <button class="btn btn-sm btn-accent" onclick="setScoreboardToday()">Hoy</button>
                <button class="btn btn-sm btn-secondary" onclick="changeScoreboardDate(1)">â–¶</button>
            </div>
        </div>
    `;

    let matchesByLeague = {};
    filteredMatches.forEach((m) => {
        const leagueName = m.league || 'Otra Liga';
        if (!matchesByLeague[leagueName]) matchesByLeague[leagueName] = [];
        matchesByLeague[leagueName].push(m);
    });

    let html = headerHtml;
    Object.keys(matchesByLeague).forEach((leagueName) => {
        html += `
            <div class="live-league-divider">
                <h3>&#127942; ${escapeHtml(leagueName)}</h3>
                <span>${matchesByLeague[leagueName].length} partidos</span>
            </div>
        `;
        html += matchesByLeague[leagueName].map(renderLiveMatchCard).join('');
    });

    grid.innerHTML = html;
}

async function openSofascoreMatchCenter(eventId) {
    if (!eventId) {
        showToast('No se encontro el evento de SofaScore', 'error');
        return;
    }

    showLoading(true);
    const data = await apiCall(buildSofascoreMatchCenterPath(eventId, { noCache: true }), 'GET', null, { noCache: true });
    showLoading(false);

    if (!data || data.status !== 'success') {
        showToast('No se pudo cargar el Match Center', 'error');
        return;
    }

    const overlay = document.createElement('div');
    overlay.className = 'context-modal-overlay sofascore-center-overlay';
    overlay.dataset.eventId = String(eventId);
    overlay.onclick = (e) => {
        if (e.target === overlay) {
            closeSofascoreCenterOverlay(overlay);
        }
    };

    overlay.innerHTML = renderSofascoreCenterModal(data);
    document.body.appendChild(overlay);
    startSofascoreCenterAutoRefresh(overlay, eventId);
}

function buildSofascoreMatchCenterPath(eventId, options = {}) {
    const params = new URLSearchParams({
        history_limit: '10',
        enrich_history_stats: 'true',
        refresh_history_stats: options.refreshHistoryStats ? 'true' : 'false',
        include_history_statistics: options.includeHistoryStatistics ? 'true' : 'false',
        force_fresh_history: options.forceFreshHistory ? 'true' : 'false',
    });
    if (options.noCache) {
        params.set('_ts', String(Date.now()));
    }
    return `/sofascore/event/${eventId}/match-center?${params.toString()}`;
}

function getActiveCenterTabName(overlayEl) {
    if (!overlayEl) return 'summary';
    return overlayEl.querySelector('.center-tab-panel.active')?.dataset?.tab || 'summary';
}

function getActiveCenterStatsPeriod(overlayEl) {
    if (!overlayEl) return '';
    return overlayEl.querySelector('.stats-period-btn.active')?.dataset?.period || '';
}

function clearSofascoreCenterRefresh(overlayEl) {
    const timerId = Number(overlayEl?.dataset?.centerRefreshTimer);
    if (Number.isFinite(timerId) && timerId > 0) {
        window.clearInterval(timerId);
    }
    if (overlayEl?.dataset) {
        delete overlayEl.dataset.centerRefreshTimer;
        delete overlayEl.dataset.centerRefreshBusy;
    }
}

function closeSofascoreCenterOverlay(targetEl) {
    const overlay = targetEl?.closest
        ? targetEl.closest('.context-modal-overlay')
        : targetEl;
    if (!overlay) return;

    clearSofascoreCenterRefresh(overlay);
    overlay.remove();
}

async function refreshSofascoreCenterOverlay(overlayEl, eventId) {
    if (!overlayEl || !document.body.contains(overlayEl)) {
        clearSofascoreCenterRefresh(overlayEl);
        return;
    }

    if (overlayEl.dataset.centerRefreshBusy === '1') {
        return;
    }

    overlayEl.dataset.centerRefreshBusy = '1';

    const activeTab = getActiveCenterTabName(overlayEl);
    const activeStatsPeriod = getActiveCenterStatsPeriod(overlayEl);
    try {
        const latest = await apiCall(buildSofascoreMatchCenterPath(eventId, { noCache: true }), 'GET', null, { noCache: true });
        if (!latest || latest.status !== 'success') {
            return;
        }

        const center = overlayEl.querySelector('.sofascore-match-center');
        if (!center) {
            return;
        }

        center.outerHTML = renderSofascoreCenterModal(latest);
        const restoredCenter = overlayEl.querySelector('.sofascore-match-center');
        const restoreBtn = restoredCenter?.querySelector(`.center-tab-btn[data-tab="${activeTab}"]`);
        if (restoreBtn) {
            switchCenterTab(restoreBtn, activeTab);
        }

        if (activeTab === 'stats' && activeStatsPeriod) {
            const restoreStatsBtn = restoredCenter?.querySelector(`.stats-period-btn[data-period="${activeStatsPeriod}"]`);
            if (restoreStatsBtn) {
                switchCenterStatsPeriod(restoreStatsBtn, activeStatsPeriod);
            }
        }
    } finally {
        overlayEl.dataset.centerRefreshBusy = '0';
    }
}

function startSofascoreCenterAutoRefresh(overlayEl, eventId) {
    clearSofascoreCenterRefresh(overlayEl);

    const timerId = window.setInterval(() => {
        void refreshSofascoreCenterOverlay(overlayEl, eventId);
    }, MATCH_CENTER_REFRESH_MS);

    overlayEl.dataset.centerRefreshTimer = String(timerId);
}

function switchCenterTab(buttonEl, tabName) {
    const modal = buttonEl.closest('.sofascore-match-center');
    if (!modal) return;

    modal.querySelectorAll('.center-tab-btn').forEach((btn) => btn.classList.remove('active'));
    modal.querySelectorAll('.center-tab-panel').forEach((panel) => panel.classList.remove('active'));

    buttonEl.classList.add('active');
    const panel = modal.querySelector(`.center-tab-panel[data-tab="${tabName}"]`);
    if (panel) panel.classList.add('active');
}

function formatCountdownMinutes(countdownMinutes) {
    const value = Number(countdownMinutes);
    if (!Number.isFinite(value)) return '';
    if (value > 0) {
        const hours = Math.floor(value / 60);
        const minutes = value % 60;
        return hours > 0 ? `${hours}h ${minutes}m para iniciar` : `${minutes}m para iniciar`;
    }
    if (value === 0) return 'Comienza ahora';
    return `Inicio hace ${Math.abs(value)}m`;
}

function getIncidentIcon(type) {
    const incidentType = String(type || '').toLowerCase();
    if (incidentType.includes('goal')) return '&#9917;';
    if (incidentType.includes('yellow')) return '🟨';
    if (incidentType.includes('red')) return '🟥';
    if (incidentType.includes('card')) return '🟨';
    if (incidentType.includes('substitution')) return '&#128259;';
    if (incidentType.includes('penalty')) return '&#127919;';
    if (incidentType.includes('var')) return '📺';
    if (incidentType.includes('period')) return '⏱';
    if (incidentType.includes('injury')) return '+';
    return '•';
}

function formatIncidentMinute(incident) {
    const minuteValue = Number(incident?.time);
    if (!Number.isFinite(minuteValue) || minuteValue <= 0) {
        return "-'";
    }

    const addedTime = Number(incident?.added_time);
    if (Number.isFinite(addedTime) && addedTime > 0 && addedTime < 100) {
        return `${Math.round(minuteValue)}+${Math.round(addedTime)}'`;
    }

    return `${Math.round(minuteValue)}'`;
}

function describeIncidentType(incident) {
    const incidentType = String(incident?.incident_type || '').toLowerCase();
    const text = String(incident?.text || '').trim();
    const textLower = text.toLowerCase();

    if (incidentType.includes('period')) {
        if (textLower.includes('second')) return 'Comienza 2T';
        if (textLower.includes('first')) return 'Comienza 1T';
        if (textLower.includes('ht')) return 'Descanso';
        return text || 'Cambio de periodo';
    }

    if (incidentType.includes('injury')) return 'Tiempo agregado';
    if (incidentType.includes('substitution')) return 'Cambio';
    if (incidentType.includes('goal')) return 'Gol';

    if (incidentType.includes('card')) {
        if (textLower.includes('red')) return 'Roja';
        if (textLower.includes('yellow')) return 'Amarilla';
        return 'Tarjeta';
    }

    if (incidentType.includes('penalty') && textLower.includes('miss')) return 'Penal fallado';
    if (incidentType.includes('penalty')) return 'Penal';
    if (incidentType.includes('var')) return 'Revision VAR';
    if (text) return text;
    return String(incident?.incident_type || 'Evento');
}

function buildIncidentMeta(incident) {
    const incidentType = String(incident?.incident_type || '').toLowerCase();
    const label = describeIncidentType(incident);
    const player = String(incident?.player || '').trim();
    const playerIn = String(incident?.player_in || '').trim();
    const playerOut = String(incident?.player_out || '').trim();
    const assist = String(incident?.assist || '').trim();

    if (incidentType.includes('period') || incidentType.includes('injury')) {
        return {
            title: label,
            subtitle: '',
            category: 'period',
            marker: true,
        };
    }

    if (incidentType.includes('substitution')) {
        return {
            title: playerIn ? `Entra ${playerIn}` : (playerOut ? `Sale ${playerOut}` : label),
            subtitle: playerIn && playerOut ? `Sale ${playerOut}` : label,
            category: 'substitution',
            marker: false,
        };
    }

    if (incidentType.includes('goal')) {
        const detail = assist ? `${label} | Asistencia: ${assist}` : label;
        return {
            title: player || label,
            subtitle: detail,
            category: 'goal',
            marker: false,
        };
    }

    if (incidentType.includes('card')) {
        return {
            title: player || label,
            subtitle: label,
            category: 'card',
            marker: false,
        };
    }

    if (incidentType.includes('var')) {
        return {
            title: player || label,
            subtitle: label,
            category: 'var',
            marker: false,
        };
    }

    return {
        title: player || label,
        subtitle: player && label !== player ? label : '',
        category: 'other',
        marker: false,
    };
}

function renderIncidentBreakRow(incident, meta) {
    const minute = formatIncidentMinute(incident);
    const textLabel = meta?.title || 'Evento';
    const minuteBadge = minute === "-'" ? '' : `<strong>${escapeHtml(minute)}</strong>`;

    return `
        <div class="incident-break-row">
            <span class="incident-break-line"></span>
            <span class="incident-break-pill">${minuteBadge}<em>${escapeHtml(textLabel)}</em></span>
            <span class="incident-break-line"></span>
        </div>
    `;
}

function renderIncidentTimeline(incidents, homeLabel = 'Local', awayLabel = 'Visitante') {
    if (!Array.isArray(incidents) || incidents.length === 0) {
        return '<div class="center-empty">No hay eventos relevantes todavia.</div>';
    }

    const timelineRows = incidents.slice(0, 36).map((incident) => {
        const meta = buildIncidentMeta(incident);
        if (meta.marker) {
            return renderIncidentBreakRow(incident, meta);
        }

        const minute = formatIncidentMinute(incident);
        const scoreText = (
            incident.home_score !== null && incident.home_score !== undefined
            && incident.away_score !== null && incident.away_score !== undefined
        ) ? `${incident.home_score}-${incident.away_score}` : '';
        const isHome = Boolean(incident.is_home);
        const icon = getIncidentIcon(incident.incident_type);

        const eventBlock = `
            <span class="incident-icon">${icon}</span>
            <div class="incident-content">
                <strong>${escapeHtml(meta.title || 'Evento')}</strong>
                ${meta.subtitle ? `<span>${escapeHtml(meta.subtitle)}</span>` : ''}
            </div>
        `;

        const homeBlock = isHome
            ? `<div class="incident-side home filled">${eventBlock}</div>`
            : '<div class="incident-side home"></div>';

        const awayBlock = !isHome
            ? `<div class="incident-side away filled">${eventBlock}</div>`
            : '<div class="incident-side away"></div>';

        return `
            <div class="incident-row ${meta.category} ${isHome ? 'home' : 'away'}">
                ${homeBlock}
                <div class="incident-center">
                    <span class="incident-minute-badge">${escapeHtml(minute)}</span>
                    ${scoreText ? `<span class="incident-score-badge">${escapeHtml(scoreText)}</span>` : ''}
                </div>
                ${awayBlock}
            </div>
        `;
    }).join('');

    return `
        <div class="incident-table-head">
            <span class="incident-side-label home">${escapeHtml(homeLabel)}</span>
            <span class="incident-side-label center">MIN</span>
            <span class="incident-side-label away">${escapeHtml(awayLabel)}</span>
        </div>
        ${timelineRows}
    `;
}

function normalizeMomentumPoint(point) {
    if (!point || typeof point !== 'object') {
        return null;
    }

    const minute = Number(point.minute ?? point.time ?? point.x);
    const value = Number(point.value ?? point.y ?? point.intensity);
    if (!Number.isFinite(minute) || !Number.isFinite(value)) {
        return null;
    }

    return {
        minute: Math.max(0, Math.round(minute)),
        value,
    };
}

function summarizeMomentumTrend(points, homeLabel, awayLabel) {
    if (!Array.isArray(points) || points.length === 0) {
        return 'Sin tendencia clara todavia.';
    }

    const recent = points.slice(-5);
    const recentAvg = recent.reduce((sum, row) => sum + row.value, 0) / recent.length;
    if (Math.abs(recentAvg) < 6) {
        return 'Ultimos minutos equilibrados.';
    }

    if (recentAvg > 0) {
        return `Ultimos minutos: presion alta de ${homeLabel}.`;
    }

    return `Ultimos minutos: presion alta de ${awayLabel}.`;
}

function renderAttackMomentum(graphPoints, homeLabel = 'Local', awayLabel = 'Visitante', statusType = '') {
    if (!Array.isArray(graphPoints) || graphPoints.length === 0) {
        return '<div class="center-empty small">Sin grafico de impulso disponible por ahora.</div>';
    }

    const normalized = graphPoints
        .map((point) => normalizeMomentumPoint(point))
        .filter((point) => point !== null)
        .sort((a, b) => a.minute - b.minute);

    if (normalized.length === 0) {
        return '<div class="center-empty small">Sin grafico de impulso disponible por ahora.</div>';
    }

    const maxBars = 84;
    let sampled = normalized;
    if (normalized.length > maxBars) {
        const step = Math.ceil(normalized.length / maxBars);
        sampled = normalized.filter((_, idx) => idx % step === 0);
        const last = normalized[normalized.length - 1];
        if (sampled[sampled.length - 1]?.minute !== last.minute || sampled[sampled.length - 1]?.value !== last.value) {
            sampled.push(last);
        }
    }

    const maxMinute = Math.max(1, ...sampled.map((point) => point.minute));
    const maxAbs = Math.max(10, ...sampled.map((point) => Math.abs(point.value)));
    const homePressure = sampled.reduce((sum, point) => sum + (point.value > 0 ? point.value : 0), 0);
    const awayPressure = sampled.reduce((sum, point) => sum + (point.value < 0 ? Math.abs(point.value) : 0), 0);
    const pressureTotal = homePressure + awayPressure;
    const homeShare = pressureTotal > 0 ? Math.round((homePressure / pressureTotal) * 100) : 50;
    const awayShare = 100 - homeShare;
    const trendText = summarizeMomentumTrend(sampled, homeLabel, awayLabel);
    const isLive = ['inprogress', 'halftime'].includes(String(statusType || '').toLowerCase());

    const barsHtml = sampled.map((point) => {
        const left = (point.minute / maxMinute) * 100;
        const barHeight = Math.max(4, (Math.abs(point.value) / maxAbs) * 46);
        const sideClass = point.value >= 0 ? 'home' : 'away';
        const barPosition = point.value >= 0
            ? `left:${left}%;bottom:50%;height:${barHeight}%;`
            : `left:${left}%;top:50%;height:${barHeight}%;`;
        const tipTeam = point.value >= 0 ? homeLabel : awayLabel;
        const title = `${point.minute}' ${tipTeam} ${Math.round(Math.abs(point.value))}`;

        return `<span class="momentum-bar ${sideClass}" style="${barPosition}" title="${escapeHtml(title)}"></span>`;
    }).join('');

    const tickCandidates = [0, 15, 30, 45, 60, 75, 90, 105, 120].filter((value) => value <= maxMinute);
    if (!tickCandidates.includes(maxMinute)) {
        tickCandidates.push(maxMinute);
    }

    const ticks = [...new Set(tickCandidates)].sort((a, b) => a - b);
    const ticksHtml = ticks.map((tick) => {
        const left = (tick / maxMinute) * 100;
        const label = tick === 0 ? '0' : `${tick}'`;
        return `<span style="left:${left}%">${escapeHtml(label)}</span>`;
    }).join('');

    return `
        <div class="momentum-card">
            <div class="momentum-head">
                <h5>Impulso de ataque</h5>
                <span class="momentum-live ${isLive ? 'live' : ''}">${isLive ? 'LIVE' : 'Snapshot'}</span>
            </div>
            <div class="momentum-chart">
                <span class="momentum-team-tag home">${escapeHtml(homeLabel)}</span>
                <span class="momentum-team-tag away">${escapeHtml(awayLabel)}</span>
                <div class="momentum-midline"></div>
                ${barsHtml}
            </div>
            <div class="momentum-scale">${ticksHtml}</div>
            <div class="momentum-stats">
                <span class="momentum-stat home">${escapeHtml(homeLabel)} ${homeShare}%</span>
                <span class="momentum-stat neutral">${escapeHtml(trendText)}</span>
                <span class="momentum-stat away">${escapeHtml(awayLabel)} ${awayShare}%</span>
            </div>
        </div>
    `;
}

function isMatchStartedStatus(statusType) {
    const normalized = String(statusType || '').toLowerCase();
    return ['inprogress', 'halftime', 'finished', 'afterpens', 'aet'].includes(normalized);
}

function parseNumericRating(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) {
        return null;
    }
    return numeric;
}

function getPlayerDisplayRating(player) {
    return parseNumericRating(player?.display_rating)
        ?? parseNumericRating(player?.rating)
        ?? parseNumericRating(player?.avg_rating);
}

function getPlayerMetricBadge(player, statusType) {
    const ratingRaw = getPlayerDisplayRating(player);
    if (ratingRaw !== null) {
        const ratingClass = ratingRaw >= 7.2 ? 'good' : (ratingRaw >= 6.7 ? 'mid' : 'low');
        return `<span class="player-rating ${ratingClass}">${ratingRaw.toFixed(1)}</span>`;
    }

    if (isMatchStartedStatus(statusType)) {
        return '<span class="player-rating muted">-</span>';
    }

    return '<span class="player-rating pending">N/R</span>';
}

function resolvePlayerPhoto(player) {
    if (player?.photo) return String(player.photo);
    if (player?.id) return `https://api.sofascore.app/api/v1/player/${player.id}/image`;
    return '';
}

function formatPitchPlayerTag(player) {
    const rawShortName = String(player?.short_name || '').trim();
    let label = rawShortName;

    if (!label) {
        const fullName = String(player?.name || 'Jugador').trim();
        const parts = fullName.split(/\s+/).filter(Boolean);
        if (parts.length >= 2) {
            label = `${parts[0].slice(0, 1)}. ${parts.slice(1).join(' ')}`;
        } else {
            label = fullName;
        }
    }

    if (label.length > 18) {
        label = `${label.slice(0, 17)}.`;
    }

    const shirt = player?.shirt_number !== null && player?.shirt_number !== undefined && player?.shirt_number !== ''
        ? String(player.shirt_number)
        : '';

    return shirt ? `${shirt} ${label}` : label;
}

function buildPitchPlayerStatLine(player) {
    const chunks = [];
    const goals = Number(player?.goals);
    const assists = Number(player?.assists);
    const yellow = Number(player?.yellow_cards);
    const red = Number(player?.red_cards);
    const minutes = Number(player?.minutes_played);

    if (Number.isFinite(goals) && goals > 0) chunks.push(`G ${goals}`);
    if (Number.isFinite(assists) && assists > 0) chunks.push(`A ${assists}`);
    if (Number.isFinite(yellow) && yellow > 0) chunks.push(`Y ${yellow}`);
    if (Number.isFinite(red) && red > 0) chunks.push(`R ${red}`);
    if (Number.isFinite(minutes) && minutes > 0) chunks.push(`${minutes}'`);

    return chunks.join(' · ');
}

function parseFormationParts(formation) {
    const tokens = String(formation || '')
        .split(/[^0-9]+/)
        .map((chunk) => Number(chunk))
        .filter((value) => Number.isFinite(value) && value > 0);

    if (tokens.length === 0) return [];

    const total = tokens.reduce((sum, n) => sum + n, 0);
    if (total === 10) return tokens;

    if (tokens[0] === 1) {
        const outfield = tokens.slice(1);
        const outfieldTotal = outfield.reduce((sum, n) => sum + n, 0);
        if (outfieldTotal === 10) return outfield;
    }

    return tokens;
}

function getPlayerRole(player) {
    const pos = String(player?.position || '').toUpperCase();
    if (pos.startsWith('G')) return 'gk';
    if (pos.startsWith('D')) return 'def';
    if (pos.startsWith('M')) return 'mid';
    if (pos.startsWith('F') || pos.startsWith('A') || pos.startsWith('S') || pos === 'W') return 'att';
    return 'mid';
}

function getNumericShirt(player) {
    const value = Number(player?.shirt_number);
    return Number.isFinite(value) ? value : 999;
}

function sortPlayersForLineup(players) {
    return [...players].sort((a, b) => {
        const slotA = Number(a?.formation_slot);
        const slotB = Number(b?.formation_slot);
        if (Number.isFinite(slotA) && Number.isFinite(slotB) && slotA !== slotB) {
            return slotA - slotB;
        }

        const orderA = Number(a?.player_order);
        const orderB = Number(b?.player_order);
        if (Number.isFinite(orderA) && Number.isFinite(orderB) && orderA !== orderB) {
            return orderA - orderB;
        }

        return getNumericShirt(a) - getNumericShirt(b);
    });
}

function lineupRowsByRoleFallback(starters, mirror = false) {
    const gk = [];
    const def = [];
    const mid = [];
    const att = [];
    const misc = [];

    sortPlayersForLineup(Array.isArray(starters) ? starters : []).forEach((player) => {
        const role = getPlayerRole(player);
        if (role === 'gk') gk.push(player);
        else if (role === 'def') def.push(player);
        else if (role === 'mid') mid.push(player);
        else if (role === 'att') att.push(player);
        else misc.push(player);
    });

    const rows = [gk, def, mid, att, misc].filter((row) => row.length > 0);
    if (mirror) {
        return [...rows]
            .reverse()
            .map((row) => [...row].reverse());
    }
    return rows;
}

function lineupRowsByFormation(starters, formation, mirror = false) {
    const allStarters = sortPlayersForLineup(Array.isArray(starters) ? starters : []);
    if (allStarters.length === 0) {
        return [];
    }

    const formationParts = parseFormationParts(formation);
    if (formationParts.length === 0) {
        return lineupRowsByRoleFallback(allStarters, mirror);
    }

    const gkCandidates = allStarters.filter((player) => getPlayerRole(player) === 'gk');
    const goalkeeper = gkCandidates.length > 0 ? gkCandidates[0] : allStarters[0];
    const outfield = allStarters.filter((player) => player !== goalkeeper);
    const rows = [];

    let cursor = 0;
    formationParts.forEach((lineCount) => {
        const rowSize = Number(lineCount);
        if (!Number.isFinite(rowSize) || rowSize <= 0) {
            return;
        }
        const rowPlayers = outfield.slice(cursor, cursor + rowSize);
        if (rowPlayers.length > 0) {
            rows.push(rowPlayers);
        }
        cursor += rowSize;
    });

    const remaining = outfield.slice(cursor);
    if (remaining.length > 0) {
        if (rows.length === 0) {
            rows.push(remaining);
        } else {
            rows[rows.length - 1] = rows[rows.length - 1].concat(remaining);
        }
    }

    if (rows.length === 0) {
        return lineupRowsByRoleFallback(allStarters, mirror);
    }

    if (mirror) {
        const mirroredRows = [...rows]
            .reverse()
            .map((row) => [...row].reverse());
        return mirroredRows.concat([[goalkeeper]]);
    }

    return [[goalkeeper]].concat(rows);
}

function renderPitchPlayer(player, statusType) {
    const photo = resolvePlayerPhoto(player);
    const shirt = player?.shirt_number ?? '-';
    const playerName = player?.name || 'Jugador';
    const playerTag = formatPitchPlayerTag(player);
    const playerStatLine = buildPitchPlayerStatLine(player);

    return `
        <div class="pitch-player-node">
            <div class="pitch-player-avatar-wrap">
                ${photo
                    ? `<img src="${photo}" alt="${escapeHtml(playerName)}" class="pitch-player-avatar" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">`
                    : ''
                }
                <div class="pitch-player-fallback" style="display:${photo ? 'none' : 'flex'}">${escapeHtml(String(shirt))}</div>
                ${getPlayerMetricBadge(player, statusType)}
            </div>
            <div class="pitch-player-tag">${escapeHtml(playerTag)}</div>
            ${playerStatLine ? `<div class="pitch-player-stats">${escapeHtml(playerStatLine)}</div>` : ''}
        </div>
    `;
}

function renderPitchTeamRows(rows, statusType, sideClass) {
    if (!Array.isArray(rows) || rows.length === 0) {
        return '<div class="pitch-row empty"></div>';
    }

    return rows.map((rowPlayers) => {
        const rowCount = Math.max(1, Array.isArray(rowPlayers) ? rowPlayers.length : 0);
        return `
        <div class="pitch-row ${sideClass}" style="--row-count:${rowCount};">
            ${rowPlayers.map((player) => renderPitchPlayer(player, statusType)).join('')}
        </div>
    `;
    }).join('');
}

function computeLineupTeamRating(starters) {
    const ratings = (Array.isArray(starters) ? starters : [])
        .map((player) => getPlayerDisplayRating(player))
        .filter((value) => value !== null);

    if (ratings.length === 0) {
        return null;
    }

    const avg = ratings.reduce((sum, value) => sum + value, 0) / ratings.length;
    return Math.round(avg * 100) / 100;
}

function renderTeamRatingChip(rating) {
    if (rating === null) {
        return '<span class="team-rating-chip pending">Sin rating</span>';
    }

    const ratingClass = rating >= 7.2 ? 'good' : (rating >= 6.7 ? 'mid' : 'low');
    return `<span class="team-rating-chip ${ratingClass}"><i></i>${rating.toFixed(2)}</span>`;
}

function renderLineupPitch(homeName, awayName, homeLineup, awayLineup, statusType) {
    const homeStarters = homeLineup?.starters || [];
    const awayStarters = awayLineup?.starters || [];

    if ((!Array.isArray(homeStarters) || homeStarters.length === 0) && (!Array.isArray(awayStarters) || awayStarters.length === 0)) {
        return '<div class="center-empty">Sin once inicial para dibujar la cancha todavia.</div>';
    }

    const homeRows = lineupRowsByFormation(homeStarters, homeLineup?.formation, false);
    const awayRows = lineupRowsByFormation(awayStarters, awayLineup?.formation, true);
    const homeTeamRating = computeLineupTeamRating(homeStarters);
    const awayTeamRating = computeLineupTeamRating(awayStarters);
    const formationLabel = `${homeLineup?.formation || '--'} vs ${awayLineup?.formation || '--'}`;

    return `
        <div class="lineup-pitch-block">
            <div class="pitch-title-row">
                <span>${escapeHtml(homeName || 'Local')}</span>
                <span class="pitch-system-tag">${escapeHtml(`Sistema ${formationLabel}`)}</span>
                <span>${escapeHtml(awayName || 'Visitante')}</span>
            </div>
            <div class="lineup-pitch-canvas">
                <div class="pitch-team-banner top">
                    <div class="pitch-team-badge home">
                        <span class="pitch-team-name">${escapeHtml(homeName || 'Local')}</span>
                        ${renderTeamRatingChip(homeTeamRating)}
                    </div>
                </div>
                <div class="pitch-half home-half">
                    ${renderPitchTeamRows(homeRows, statusType, 'home')}
                </div>
                <div class="pitch-midline"></div>
                <div class="pitch-center-circle"></div>
                <div class="pitch-half away-half">
                    ${renderPitchTeamRows(awayRows, statusType, 'away')}
                </div>
                <div class="pitch-team-banner bottom">
                    <div class="pitch-team-badge away">
                        <span class="pitch-team-name">${escapeHtml(awayName || 'Visitante')}</span>
                        ${renderTeamRatingChip(awayTeamRating)}
                    </div>
                </div>
            </div>
            <div class="pitch-legend-row">
                <span><b>Verde</b>: forma alta</span>
                <span><b>Amarillo</b>: forma media</span>
                <span><b>Naranja</b>: por debajo del promedio</span>
                <span><b>N/A</b>: sin valoracion disponible</span>
            </div>
        </div>
    `;
}

function renderLineupPlayers(players, statusType = '') {
    if (!Array.isArray(players) || players.length === 0) {
        return '<div class="center-empty small">Sin jugadores confirmados.</div>';
    }

    return `
        <ul class="lineup-players-list">
            ${players.slice(0, 18).map((player, idx) => `
                <li>
                    <span class="shirt-number">${escapeHtml(String(player.shirt_number || idx + 1))}</span>
                    <span class="player-name">${escapeHtml(player.name || 'Jugador')}</span>
                    <span class="player-pos">${escapeHtml(player.position || '')}</span>
                    ${getPlayerMetricBadge(player, statusType)}
                </li>
            `).join('')}
        </ul>
    `;
}

function renderMissingPlayers(missing) {
    if (!Array.isArray(missing) || missing.length === 0) {
        return '<div class="center-empty small">Sin bajas reportadas.</div>';
    }

    return `
        <div class="missing-players-list">
            ${missing.slice(0, 10).map((player) => {
                const typeLabel = player.injury_type || player.description || 'Baja';
                const statusClass = player.status === 'Suspendido' ? 'suspended' : (player.status === 'Duda' ? 'doubtful' : 'out');
                return `
                    <div class="missing-player-row">
                        <div class="missing-player-main">
                            <span class="missing-player-name">${escapeHtml(player.name || 'Jugador')}</span>
                            <span class="missing-player-type">${escapeHtml(typeLabel)}</span>
                        </div>
                        <span class="missing-player-status ${statusClass}">${escapeHtml(player.status || 'Baja')}</span>
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function renderLineupColumn(teamLabel, sideLineup, statusType = '') {
    const formation = sideLineup?.formation ? `Sistema ${escapeHtml(String(sideLineup.formation))}` : 'Sistema por confirmar';
    return `
        <div class="lineup-column">
            <h4>${escapeHtml(teamLabel)}</h4>
            <span class="lineup-formation">${formation}</span>
            <div class="lineup-block">
                <h5>Titulares</h5>
                ${renderLineupPlayers(sideLineup?.starters || [], statusType)}
            </div>
            <div class="lineup-block">
                <h5>Suplentes</h5>
                ${renderLineupPlayers(sideLineup?.bench || [], statusType)}
            </div>
            <div class="lineup-block">
                <h5>Bajas / Dudas</h5>
                ${renderMissingPlayers(sideLineup?.missing || [])}
            </div>
        </div>
    `;
}

function renderLineupPanel(home, away, lineup, statusType) {
    return `
        <div class="lineup-main-grid">
            ${renderLineupPitch(home?.name || 'Local', away?.name || 'Visitante', lineup?.home || {}, lineup?.away || {}, statusType)}
            <div class="center-lineups-grid">
                ${renderLineupColumn(home?.name || 'Local', lineup?.home || {}, statusType)}
                ${renderLineupColumn(away?.name || 'Visitante', lineup?.away || {}, statusType)}
            </div>
        </div>
    `;
}

const STATS_GROUP_TRANSLATIONS = {
    'match overview': 'Resumen del partido',
    shots: 'Tiros',
    attack: 'Ataque',
    passes: 'Pases',
    duels: 'Duelos',
    defending: 'Defensa',
    goalkeeping: 'Porteria',
    discipline: 'Disciplina',
};

const STATS_ITEM_TRANSLATIONS = {
    'accurate passes': 'Pases precisos',
    'aerial duels': 'Duelos aereos',
    'ball possession': 'Posesion de balon',
    'big chances': 'Grandes ocasiones',
    'big chances scored': 'Grandes ocasiones convertidas',
    'big saves': 'Grandes paradas',
    'blocked shots': 'Tiros bloqueados',
    clearances: 'Despejes',
    'corner kicks': 'Saques de esquina',
    crosses: 'Centros',
    dispossessed: 'Perdidas de balon',
    dribbles: 'Regates',
    duels: 'Duelos',
    'errors lead to a shot': 'Errores que terminaron en tiro',
    'expected goals': 'Goles esperados (xG)',
    'final third entries': 'Entradas al ultimo tercio',
    'final third phase': 'Posesion en ultimo tercio',
    'fouled in final third': 'Faltas recibidas en ultimo tercio',
    fouls: 'Faltas',
    'free kicks': 'Tiros libres',
    'goal kicks': 'Saques de puerta',
    'goalkeeper saves': 'Paradas',
    'goals prevented': 'Goles evitados',
    'ground duels': 'Duelos en el suelo',
    'high claims': 'Balones aereos atrapados',
    'hit woodwork': 'Tiros al palo',
    interceptions: 'Intercepciones',
    'long balls': 'Balones largos',
    passes: 'Pases',
    recoveries: 'Recuperaciones',
    'shots inside box': 'Tiros dentro del area',
    'shots off target': 'Tiros fuera',
    'shots on target': 'Tiros a puerta',
    'shots outside box': 'Tiros fuera del area',
    tackles: 'Entradas',
    'tackles won': 'Entradas ganadas',
    'through balls': 'Pases filtrados',
    'throw-ins': 'Saques de banda',
    'total saves': 'Paradas totales',
    'total shots': 'Tiros totales',
    'total tackles': 'Entradas totales',
    'touches in penalty area': 'Toques en el area rival',
    'yellow cards': 'Tarjetas amarillas',
};

function normalizeStatsLookupKey(value) {
    return String(value || '')
        .toLowerCase()
        .replace(/\s+/g, ' ')
        .trim();
}

function translateStatsGroupLabel(name) {
    const normalized = normalizeStatsLookupKey(name);
    return STATS_GROUP_TRANSLATIONS[normalized] || String(name || 'General');
}

function translateStatsItemLabel(name) {
    const normalized = normalizeStatsLookupKey(name);
    return STATS_ITEM_TRANSLATIONS[normalized] || String(name || '');
}

function normalizeStatsPeriodKey(periodRaw) {
    const normalized = String(periodRaw || '').trim().toUpperCase();
    if (!normalized || normalized === 'ALL' || normalized === 'FULL' || normalized === 'FT') return 'ALL';
    if (normalized.includes('1') || normalized.includes('FIRST')) return '1ST';
    if (normalized.includes('2') || normalized.includes('SECOND')) return '2ND';
    return normalized;
}

function getStatsPeriodSortOrder(periodKey) {
    const order = {
        ALL: 0,
        '1ST': 1,
        '2ND': 2,
    };
    return order[periodKey] ?? 9;
}

function getStatsPeriodLabel(periodKey) {
    const labels = {
        ALL: 'TODOS',
        '1ST': '1T',
        '2ND': '2T',
    };
    return labels[periodKey] || periodKey;
}

function parseStatsNumericValue(value) {
    if (typeof value === 'number' && Number.isFinite(value)) {
        return { text: String(value), numeric: value };
    }

    const raw = String(value ?? '').trim();
    if (!raw) {
        return { text: '0', numeric: 0 };
    }

    const clean = raw.replace(',', '.');
    const match = clean.match(/-?\d+(?:\.\d+)?/);
    const numeric = match ? Number(match[0]) : null;
    return {
        text: raw,
        numeric: Number.isFinite(numeric) ? numeric : null,
    };
}

function toStatsBarWidth(share) {
    if (!Number.isFinite(share) || share <= 0) return 0;
    const clamped = Math.max(0, Math.min(100, share));
    return clamped > 0 && clamped < 6 ? 6 : clamped;
}

function computeStatsBarShares(homeNumeric, awayNumeric) {
    if (!Number.isFinite(homeNumeric) || !Number.isFinite(awayNumeric)) {
        return { homeWidth: 0, awayWidth: 0 };
    }

    const homeValue = Math.max(0, homeNumeric);
    const awayValue = Math.max(0, awayNumeric);
    const total = homeValue + awayValue;
    if (total <= 0) {
        return { homeWidth: 0, awayWidth: 0 };
    }

    return {
        homeWidth: toStatsBarWidth((homeValue / total) * 100),
        awayWidth: toStatsBarWidth((awayValue / total) * 100),
    };
}

function renderSofascoreStatRow(item) {
    const home = parseStatsNumericValue(item?.home);
    const away = parseStatsNumericValue(item?.away);
    const translatedName = translateStatsItemLabel(item?.name || '');
    const { homeWidth, awayWidth } = computeStatsBarShares(home.numeric, away.numeric);
    const homeBetter = Number.isFinite(home.numeric) && Number.isFinite(away.numeric) && home.numeric > away.numeric;
    const awayBetter = Number.isFinite(home.numeric) && Number.isFinite(away.numeric) && away.numeric > home.numeric;

    return `
        <div class="sofa-stat-row">
            <div class="sofa-stat-side home ${homeBetter ? 'better' : ''}">
                <span class="sofa-stat-value">${escapeHtml(home.text)}</span>
                <span class="sofa-stat-track home">
                    <span class="sofa-stat-fill home" style="width:${homeWidth.toFixed(2)}%"></span>
                </span>
            </div>
            <div class="sofa-stat-meta">
                <span class="sofa-stat-name">${escapeHtml(translatedName)}</span>
            </div>
            <div class="sofa-stat-side away ${awayBetter ? 'better' : ''}">
                <span class="sofa-stat-value">${escapeHtml(away.text)}</span>
                <span class="sofa-stat-track away">
                    <span class="sofa-stat-fill away" style="width:${awayWidth.toFixed(2)}%"></span>
                </span>
            </div>
        </div>
    `;
}

function renderStatisticsPeriodContent(groups) {
    const groupsList = Array.isArray(groups) ? groups : [];
    return groupsList.map((group) => {
        const items = Array.isArray(group?.items) ? group.items : [];
        if (items.length === 0) {
            return '';
        }

        return `
            <section class="sofa-stat-group">
                <h5>${escapeHtml(translateStatsGroupLabel(group.group_name || 'General'))}</h5>
                <div class="sofa-stat-grid">
                    ${items.map((item) => renderSofascoreStatRow(item)).join('')}
                </div>
            </section>
        `;
    }).join('');
}

function switchCenterStatsPeriod(buttonEl, periodKey) {
    const shell = buttonEl?.closest('.stats-period-shell');
    if (!shell) return;

    shell.querySelectorAll('.stats-period-btn').forEach((btn) => btn.classList.remove('active'));
    shell.querySelectorAll('.stats-period-panel').forEach((panel) => panel.classList.remove('active'));

    buttonEl.classList.add('active');
    const target = shell.querySelector(`.stats-period-panel[data-period="${periodKey}"]`);
    if (target) {
        target.classList.add('active');
    }
}

function renderStatisticsPanel(statistics, statusType = '', homeLabel = 'Local', awayLabel = 'Visitante') {
    if (!Array.isArray(statistics) || statistics.length === 0) {
        const started = isMatchStartedStatus(statusType);
        return `
            <div class="center-empty">
                ${started
                    ? 'SofaScore aun no publica el bloque estadistico completo para este evento. Puede tardar unos minutos tras el inicio.'
                    : 'Antes de iniciar, SofaScore normalmente no muestra estadisticas de partido. Aparecen cuando arranca.'}
                <br><br>
                Si luego sigue vacio: ejecuta Sync SofaScore en Pipeline para reforzar historico local.
            </div>
        `;
    }

    const periodMap = new Map();
    statistics.forEach((periodBlock) => {
        if (!periodBlock || typeof periodBlock !== 'object') return;
        const periodKey = normalizeStatsPeriodKey(periodBlock.period);
        if (!periodMap.has(periodKey)) {
            periodMap.set(periodKey, {
                key: periodKey,
                period: periodBlock.period || periodKey,
                groups: [],
            });
        }

        const entry = periodMap.get(periodKey);
        if (entry && Array.isArray(periodBlock.groups)) {
            entry.groups.push(...periodBlock.groups.filter((row) => row && typeof row === 'object'));
        }
    });

    const periodEntries = Array.from(periodMap.values())
        .filter((entry) => Array.isArray(entry.groups) && entry.groups.length > 0)
        .sort((a, b) => getStatsPeriodSortOrder(a.key) - getStatsPeriodSortOrder(b.key));

    if (periodEntries.length === 0) {
        return '<div class="center-empty">SofaScore aun no publica estadisticas estructuradas para este partido.</div>';
    }

    const defaultPeriod = periodEntries.find((entry) => entry.key === 'ALL')?.key || periodEntries[0].key;

    return `
        <div class="stats-period-shell">
            <div class="stubet-stats-hero">
                <div class="stubet-stats-hero-copy">
                    <span class="stubet-stats-kicker">STUBET Match Lens</span>
                    <p>Lectura limpia por periodos con barras relativas por equipo.</p>
                </div>
                <div class="stats-period-switch">
                    ${periodEntries.map((entry) => `
                        <button
                            class="stats-period-btn ${entry.key === defaultPeriod ? 'active' : ''}"
                            data-period="${escapeHtml(entry.key)}"
                            onclick="switchCenterStatsPeriod(this, '${escapeHtml(entry.key)}')"
                        >
                            ${escapeHtml(getStatsPeriodLabel(entry.key))}
                        </button>
                    `).join('')}
                </div>
            </div>

            <div class="stubet-stats-columns">
                <span class="stubet-team-pill home"><i></i>${escapeHtml(homeLabel)}</span>
                <span class="stubet-team-pill metric">Metricas</span>
                <span class="stubet-team-pill away">${escapeHtml(awayLabel)}<i></i></span>
            </div>

            ${periodEntries.map((entry) => `
                <div class="stats-period-panel ${entry.key === defaultPeriod ? 'active' : ''}" data-period="${escapeHtml(entry.key)}">
                    ${renderStatisticsPeriodContent(entry.groups)}
                </div>
            `).join('')}
        </div>
    `;
}

function renderHistoryTableRows(matches) {
    if (!Array.isArray(matches) || matches.length === 0) {
        return '<div class="center-empty small">Sin historico disponible. Se llena con sync historico o fallback live de SofaScore cuando el endpoint lo permite.</div>';
    }

    return `
        <table class="history-table">
            <thead>
                <tr>
                    <th>Fecha</th>
                    <th>Partido</th>
                    <th>Marcador</th>
                    <th>Torneo</th>
                </tr>
            </thead>
            <tbody>
                ${matches.slice(0, 10).map((match) => {
                    const date = match.start_timestamp
                        ? new Date(Number(match.start_timestamp) * 1000).toLocaleDateString('es', { day: '2-digit', month: 'short' })
                        : (match.match_date ? new Date(match.match_date).toLocaleDateString('es', { day: '2-digit', month: 'short' }) : '-');
                    const matchup = `${match.home_team_name || '?'} vs ${match.away_team_name || '?'}`;
                    const score = `${match.home_score ?? '-'}:${match.away_score ?? '-'}`;
                    return `
                        <tr>
                            <td>${escapeHtml(date)}</td>
                            <td>${escapeHtml(matchup)}</td>
                            <td>${escapeHtml(score)}</td>
                            <td>${escapeHtml(match.league_name || '-')}</td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;
}

function renderTeamFormRows(matches, teamId) {
    if (!Array.isArray(matches) || matches.length === 0) {
        return '<div class="center-empty small">Sin ultimos 10 guardados. Si no aparece, corre sync historico para poblar base local.</div>';
    }

    return `
        <div class="form-rows-list">
            ${matches.slice(0, 10).map((match) => {
                const isHome = Number(match.home_team_id) === Number(teamId);
                const ownGoalsRaw = isHome ? Number(match.home_score) : Number(match.away_score);
                const rivalGoalsRaw = isHome ? Number(match.away_score) : Number(match.home_score);
                const ownGoals = Number.isFinite(ownGoalsRaw) ? ownGoalsRaw : 0;
                const rivalGoals = Number.isFinite(rivalGoalsRaw) ? rivalGoalsRaw : 0;

                let outcome = 'D';
                if (ownGoals > rivalGoals) outcome = 'W';
                if (ownGoals < rivalGoals) outcome = 'L';

                const outcomeClass = outcome === 'W' ? 'win' : (outcome === 'L' ? 'loss' : 'draw');
                const rivalName = isHome ? match.away_team_name : match.home_team_name;

                return `
                    <div class="form-row-item">
                        <span class="form-chip ${outcomeClass}">${outcome}</span>
                        <span class="form-opponent">vs ${escapeHtml(rivalName || '?')}</span>
                        <span class="form-score">${escapeHtml(String(ownGoals))}-${escapeHtml(String(rivalGoals))}</span>
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function renderSummaryChecklist(eventStatusType, hasStats, hasHistory) {
    const started = isMatchStartedStatus(eventStatusType);
    return `
        <div class="summary-checklist">
            <h5>Que deberia aparecer en Resumen</h5>
            <ul>
                <li>Timeline de eventos clave (goles, tarjetas, cambios).</li>
                <li>Estado de alineaciones (probables o confirmadas).</li>
                <li>Countdown al inicio y fuente del dato.</li>
                <li>${started ? (hasStats ? 'Estadisticas generales activas.' : 'Estadisticas en proceso de publicacion en SofaScore.') : 'Estadisticas se habilitan cuando inicia el partido.'}</li>
                <li>${hasHistory ? 'Historico H2H/Last10 disponible en su tab.' : 'Si H2H/Last10 vacio, reforzar con sync historico.'}</li>
            </ul>
        </div>
    `;
}

function formatAiRate(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
        return 'N/D';
    }
    return `${numeric.toFixed(1)}%`;
}

function renderAiContextInsights(aiContext) {
    if (!aiContext || !aiContext.enabled) {
        return '';
    }

    const homeForm = aiContext?.home_last10?.form || {};
    const awayForm = aiContext?.away_last10?.form || {};
    const h2hForm = aiContext?.h2h?.form || {};
    const notes = Array.isArray(aiContext?.analysis_notes) ? aiContext.analysis_notes.slice(0, 6) : [];
    const statSources = aiContext?.statistics_sources || {};
    const sourceText = Object.entries(statSources)
        .map(([k, v]) => `${k}: ${v}`)
        .join(' | ');

    return `
        <div class="ai-context-card">
            <h5>Contexto IA (SofaScore Last10 + H2H)</h5>
            <div class="ai-context-grid">
                <div class="ai-context-metric">
                    <span>Local Over 2.5</span>
                    <strong>${escapeHtml(formatAiRate(homeForm.over25_rate))}</strong>
                </div>
                <div class="ai-context-metric">
                    <span>Visitante Over 2.5</span>
                    <strong>${escapeHtml(formatAiRate(awayForm.over25_rate))}</strong>
                </div>
                <div class="ai-context-metric">
                    <span>H2H Over 2.5</span>
                    <strong>${escapeHtml(formatAiRate(h2hForm.over25_rate))}</strong>
                </div>
                <div class="ai-context-metric">
                    <span>H2H BTTS</span>
                    <strong>${escapeHtml(formatAiRate(h2hForm.btts_rate))}</strong>
                </div>
            </div>
            ${notes.length > 0 ? `
                <ul class="ai-context-notes">
                    ${notes.map((note) => `<li>${escapeHtml(note)}</li>`).join('')}
                </ul>
            ` : ''}
            ${sourceText ? `<p class="ai-context-source">${escapeHtml(sourceText)}</p>` : ''}
        </div>
    `;
}

function renderSofascoreCenterModal(data) {
    const event = data.event_summary || {};
    const lineup = data.lineup || {};
    const history = data.history || {};
    const sources = data.sources || {};

    const home = event.home_team || {};
    const away = event.away_team || {};
    const homeScore = home.score !== null && home.score !== undefined ? home.score : '—';
    const awayScore = away.score !== null && away.score !== undefined ? away.score : '—';

    const kickoffLabel = event.start_timestamp
        ? new Date(Number(event.start_timestamp) * 1000).toLocaleString('es', {
            weekday: 'short',
            day: '2-digit',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit',
        })
        : 'Horario por confirmar';

    const lineupStatusClass = lineup.status || 'probable';
    const eventStatusType = String(event.status_type || '');
    const lineupCountdown = formatCountdownMinutes(lineup.countdown_minutes);
    const sourceText = Object.entries(sources)
        .map(([key, value]) => `${key}: ${value}`)
        .join(' | ');
    const hasStats = Array.isArray(data.statistics) && data.statistics.length > 0;
    const hasHistory = (
        (Array.isArray(history.h2h) && history.h2h.length > 0)
        || (Array.isArray(history.home_last10) && history.home_last10.length > 0)
        || (Array.isArray(history.away_last10) && history.away_last10.length > 0)
    );

    return `
        <div class="context-modal glass-card sofascore-match-center">
            <div class="context-modal-header sofascore-center-header">
                <div class="center-scoreboard">
                    <div class="center-team-block">
                        ${home.logo ? `<img src="${home.logo}" alt="${escapeHtml(home.name || '')}" class="center-team-logo" onerror="this.style.display='none'">` : '<div class="center-team-logo placeholder"></div>'}
                        <span>${escapeHtml(home.name || 'Local')}</span>
                    </div>
                    <div class="center-score-main">
                        <div class="center-scoreline">${escapeHtml(String(homeScore))}<span>:</span>${escapeHtml(String(awayScore))}</div>
                        <div class="center-status ${escapeHtml(event.status_type || 'scheduled')}">${escapeHtml(event.status || 'Programado')}</div>
                    </div>
                    <div class="center-team-block away">
                        ${away.logo ? `<img src="${away.logo}" alt="${escapeHtml(away.name || '')}" class="center-team-logo" onerror="this.style.display='none'">` : '<div class="center-team-logo placeholder"></div>'}
                        <span>${escapeHtml(away.name || 'Visitante')}</span>
                    </div>
                </div>
                <button class="btn btn-sm" onclick="closeSofascoreCenterOverlay(this)">✕</button>
            </div>

            <div class="center-meta-row">
                <span class="meta-pill">${escapeHtml(event.category || 'Internacional')}</span>
                <span class="meta-pill">${escapeHtml(event.tournament || 'Torneo')}</span>
                <span class="meta-pill">${escapeHtml(kickoffLabel)}</span>
                ${event.round ? `<span class="meta-pill">${escapeHtml(String(event.round))}</span>` : ''}
                <span class="lineup-state ${lineupStatusClass}">${escapeHtml(lineup.label || 'Alineaciones')}</span>
                ${lineupCountdown ? `<span class="meta-pill">${escapeHtml(lineupCountdown)}</span>` : ''}
            </div>

            <div class="center-tabs-wrap">
                <button class="center-tab-btn active" data-tab="summary" onclick="switchCenterTab(this, 'summary')">Resumen</button>
                <button class="center-tab-btn" data-tab="lineups" onclick="switchCenterTab(this, 'lineups')">Alineaciones</button>
                <button class="center-tab-btn" data-tab="stats" onclick="switchCenterTab(this, 'stats')">Estadisticas</button>
                <button class="center-tab-btn" data-tab="h2h" onclick="switchCenterTab(this, 'h2h')">H2H & Last10</button>
            </div>

            <div class="center-tab-panel active" data-tab="summary">
                <div class="center-panel-grid">
                    <div class="center-panel-card">
                        <h4>Flujo del partido</h4>
                        ${renderAttackMomentum(
                            data.graph || [],
                            home.short_name || home.name || 'Local',
                            away.short_name || away.name || 'Visitante',
                            eventStatusType,
                        )}
                        <div class="incident-timeline">
                            ${renderIncidentTimeline(
                                data.incidents || [],
                                home.short_name || home.name || 'Local',
                                away.short_name || away.name || 'Visitante',
                            )}
                        </div>
                    </div>
                    <div class="center-panel-card">
                        <h4>Contexto de alineaciones</h4>
                        <p>${escapeHtml(lineup.label || 'Sin estado')}</p>
                        <p style="opacity:0.75; margin-top:0.5rem;">${escapeHtml(lineupCountdown || 'El estado se actualiza con feed en vivo de SofaScore.')}</p>
                        ${renderSummaryChecklist(eventStatusType, hasStats, hasHistory)}
                        ${renderAiContextInsights(data.ai_context || {})}
                        <p style="opacity:0.6; margin-top:0.75rem; font-size:0.8rem;">${escapeHtml(sourceText || 'Sin detalle de fuentes')}</p>
                    </div>
                </div>
            </div>

            <div class="center-tab-panel" data-tab="lineups">
                ${renderLineupPanel(home, away, lineup, eventStatusType)}
            </div>

            <div class="center-tab-panel" data-tab="stats">
                ${renderStatisticsPanel(
                    data.statistics || [],
                    eventStatusType,
                    home.short_name || home.name || 'Local',
                    away.short_name || away.name || 'Visitante',
                )}
            </div>

            <div class="center-tab-panel" data-tab="h2h">
                <div class="center-history-grid">
                    <div class="history-block">
                        <h4>Enfrentamientos directos</h4>
                        ${renderHistoryTableRows(history.h2h || [])}
                    </div>
                    <div class="history-block">
                        <h4>Ultimos 10 ${escapeHtml(home.short_name || home.name || 'Local')}</h4>
                        ${renderTeamFormRows(history.home_last10 || [], home.id)}
                    </div>
                    <div class="history-block">
                        <h4>Ultimos 10 ${escapeHtml(away.short_name || away.name || 'Visitante')}</h4>
                        ${renderTeamFormRows(history.away_last10 || [], away.id)}
                    </div>
                </div>
            </div>
        </div>
    `;
}

// ==================== PATTERNS ====================
async function discoverPatternsLegacy() {
    showLoading(true);
    showToast('🔍 Analizando datos históricos para descubrir patrones...', 'info');

    const data = await apiCall('/patterns/discover', 'POST');
    showLoading(false);

    const grid = document.getElementById('patterns-grid');

    if (!data || !data.patterns || data.patterns.length === 0) {
        grid.innerHTML = `
            <div class="empty-state glass-card">
                <span style="font-size:3rem;">&#128202;</span>
                <p>No se encontraron patrones con suficiente confianza</p>
                <p style="opacity:0.6;">Se necesitan más datos históricos. Ejecuta el pipeline o recopila partidos reales.</p>
            </div>`;
        showToast('ℹ️ No se encontraron patrones significativos todavía', 'info');
        return;
    }

    appState.patterns = data.patterns;
    showToast(`&#9989; ${data.patterns_found} patrones descubiertos!`, 'success');

    const categoryEmojis = {
        form: '&#128200;', statistical: '&#128202;', h2h: '🤝', league: '&#127942;',
        scoring: '&#9917;', team_statistical: '📋', situational: '🎲'
    };

    const categoryNames = {
        form: 'Forma', statistical: 'Estadístico', h2h: 'Head to Head',
        league: 'Liga', scoring: 'Goles', team_statistical: 'Equipo',
        situational: 'Situacional'
    };

    grid.innerHTML = data.patterns.map(p => {
        const catEmoji = categoryEmojis[p.category] || '🔍';
        const catName = categoryNames[p.category] || p.category;
        const hitPct = Math.round((p.hit_rate || 0) * 100);
        const confPct = Math.round((p.confidence || 0) * 100);
        const confClass = confPct >= 80 ? 'premium' : (confPct >= 65 ? 'strong' : 'normal');
        const hitColor = hitPct >= 70 ? '#10b981' : (hitPct >= 55 ? '#f59e0b' : '#ef4444');

        return `
            <div class="pattern-card glass-card ${confClass}">
                <div class="pattern-header">
                    <span class="pattern-category">${catEmoji} ${catName}</span>
                    <span class="pattern-confidence badge badge-${confPct >= 80 ? 'success' : (confPct >= 65 ? 'warning' : 'info')}">${confPct}% conf</span>
                </div>
                <h4 class="pattern-name">${p.name}</h4>
                <p class="pattern-desc">${p.description}</p>
                <div class="pattern-stats">
                    <div class="pattern-stat">
                        <span class="pattern-stat-label">Hit Rate</span>
                        <span class="pattern-stat-value" style="color:${hitColor}">${hitPct}%</span>
                    </div>
                    <div class="pattern-stat">
                        <span class="pattern-stat-label">Muestra</span>
                        <span class="pattern-stat-value">${p.sample_size}</span>
                    </div>
                    <div class="pattern-stat">
                        <span class="pattern-stat-label">Precisión Live</span>
                        <span class="pattern-stat-value">${Math.round((p.live_accuracy || 0) * 100)}%</span>
                    </div>
                </div>
                <div class="pattern-prediction">
                    &#127919; <strong>${p.prediction?.expected || '—'}</strong>
                    <span style="opacity:0.6;">| ${p.prediction?.market || '—'}</span>
                </div>
            </div>
        `;
    }).join('');
}

// ==================== NEWS & INJURIES ====================
async function loadNews() {
    const league = document.getElementById('news-league-filter')?.value || 'eng.1';
    const newsList = document.getElementById('news-list');

    newsList.innerHTML = '<div class="loading-inline"><div class="spinner-sm"></div> Cargando noticias de ESPN...</div>';

    const data = await apiCall(`/news/${league}`);

    if (!data || !data.news || data.news.length === 0) {
        newsList.innerHTML = '<div class="empty-state glass-card"><p>No hay noticias disponibles</p></div>';
        return;
    }

    newsList.innerHTML = data.news.slice(0, 15).map(article => {
        const date = article.published
            ? new Date(article.published).toLocaleDateString('es', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
            : '';

        const categories = (article.categories || []).slice(0, 3).map(c =>
            `<span class="news-tag">${c}</span>`
        ).join('');

        return `
            <div class="news-card glass-card">
                <div class="news-type">${article.type === 'HeadlineNews' ? '&#128293;' : '📰'} ${article.type || 'Story'}</div>
                <h4 class="news-headline">${article.headline || ''}</h4>
                <p class="news-description">${article.description || ''}</p>
                <div class="news-footer">
                    <span class="news-date">&#128197; ${date}</span>
                    ${categories}
                    ${article.link ? `<a href="${article.link}" target="_blank" class="news-link">Leer más →</a>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

async function searchInjuries() {
    const teamName = document.getElementById('injury-team-search')?.value?.trim();
    if (!teamName) {
        showToast('Ingresa el nombre de un equipo', 'error');
        return;
    }
    searchInjuriesFor(teamName);
}

async function searchInjuriesFor(teamName) {
    const injList = document.getElementById('injuries-list');
    injList.innerHTML = `<div class="loading-inline"><div class="spinner-sm"></div> Buscando lesiones de ${teamName}...</div>`;

    // Also switch to news tab if not there
    if (appState.currentSection !== 'news') {
        switchSection('news');
    }

    const league = document.getElementById('news-league-filter')?.value || 'eng.1';
    const data = await apiCall(`/injuries/${encodeURIComponent(teamName)}?league_key=${encodeURIComponent(league)}`);

    if (!data || !data.injuries || data.injuries.length === 0) {
        injList.innerHTML = `
            <div class="empty-state glass-card">
                <span style="font-size:2rem;">&#9989;</span>
                <p>No se encontraron lesiones para <strong>${teamName}</strong></p>
                <p style="opacity:0.6;">El equipo parece estar completo o no hay datos disponibles</p>
            </div>`;
        return;
    }

    injList.innerHTML = `
        <div class="injuries-header glass-card">
            <h4>🏥 ${teamName} — ${data.injuries.length} jugador(es) afectado(s)</h4>
        </div>
        ${data.injuries.map(inj => {
        const statusEmoji = inj.status === 'Out' ? '🔴' : (inj.status === 'Doubtful' ? '🟡' : '🟢');
        return `
                <div class="injury-card glass-card">
                    <div class="injury-player">
                        ${statusEmoji} <strong>${inj.player || 'Desconocido'}</strong>
                        <span class="injury-position">${inj.position || '?'}</span>
                    </div>
                    <div class="injury-details">
                        <span>🤕 ${inj.injury_type || 'Lesión'}</span>
                        <span>📋 ${inj.status || 'Unknown'}</span>
                        ${inj.details ? `<span>ℹ️ ${inj.details}</span>` : ''}
                        ${inj.return_date ? `<span>&#128197; Retorno: ${inj.return_date}</span>` : ''}
                    </div>
                </div>
            `;
    }).join('')}
    `;
}

function fmtContextStat(value, decimals = 1) {
    if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) {
        return decimals === 0 ? '0' : (0).toFixed(decimals);
    }
    return Number(value).toFixed(decimals);
}

async function getMatchContext(homeTeam, awayTeam) {
    showLoading(true);
    showToast(`🔍 Analizando contexto: ${homeTeam} vs ${awayTeam}...`, 'info');

    const league = document.getElementById('live-league-filter')?.value || 'eng.1';
    const data = await apiCall(`/match-context?home_team=${encodeURIComponent(homeTeam)}&away_team=${encodeURIComponent(awayTeam)}&league_key=${league}`);
    showLoading(false);

    if (!data) {
        showToast('Error al obtener contexto del partido', 'error');
        return;
    }

    // Create a modal with match context
    const modal = document.createElement('div');
    modal.className = 'context-modal-overlay';
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

    const impact = data.impact_analysis || {};
    const homeInj = data.injuries?.home || [];
    const awayInj = data.injuries?.away || [];
    const relevantNews = data.relevant_news || [];

    const advantageEmoji = impact.injury_advantage === 'home' ? '🟢 Local' :
        (impact.injury_advantage === 'away' ? '🟢 Visitante' : '🟡 Neutral');

    const stats = data.detailed_stats || null;
    const homeStats = stats?.home_recent_form || {};
    const awayStats = stats?.away_recent_form || {};
    const aiSummary = data.ai_tactical_summary || '';

    const normalizeInjuryText = (value) => (value || '')
        .toString()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase();

    const getInjuryBadge = (inj) => {
        const statusText = normalizeInjuryText(inj?.status);
        const injuryText = normalizeInjuryText(inj?.injury_type);
        const detailsText = normalizeInjuryText(inj?.details);
        const combined = `${statusText} ${injuryText} ${detailsText}`;

        if (combined.includes('suspend') || combined.includes('red card') || combined.includes('roja') || combined.includes('amarilla')) {
            return { label: '[Suspendido]', icon: '🟥', style: 'color:#fb7185;' };
        }
        if (combined.includes('doubtful') || combined.includes('duda') || combined.includes('questionable') || combined.includes('gtd')) {
            return { label: '[Duda]', icon: '🟡', style: 'color:#fbbf24;' };
        }
        return { label: '[Fuera]', icon: '🔴', style: 'color:#ef4444;' };
    };

    modal.innerHTML = `
        <div class="context-modal glass-card" style="max-width: 800px;">
            <div class="context-modal-header">
                <h2>🧠 Análisis IA: ${homeTeam} vs ${awayTeam}</h2>
                <button class="btn btn-sm" onclick="this.closest('.context-modal-overlay').remove()">✕</button>
            </div>
            <div class="context-modal-body">
                
                ${aiSummary ? `
                <div class="context-section" style="background: rgba(99, 102, 241, 0.08); border-left: 3px solid var(--accent-primary);">
                    <h3>📝 Resumen Táctico IA (Estilo Sofascore)</h3>
                    <div style="font-size: 0.95rem; line-height: 1.6; color: var(--text-primary); white-space: pre-wrap; margin-top: 1rem;">${aiSummary}</div>
                </div>` : ''}

                ${stats ? `
                <div class="context-section">
                    <h3>&#128202; Estadísticas Detalladas (Promedios Recientes)</h3>
                    <div class="context-grid" style="grid-template-columns: 1fr 1fr;">
                        <div class="context-stat" style="align-items: flex-start; padding: 1rem;">
                            <h4 style="color: var(--text-primary); margin-bottom: 0.5rem;">${homeTeam}</h4>
                            <div style="font-size: 0.82rem; color: var(--text-secondary); line-height: 1.6;">
                                Goles a favor: <strong>${fmtContextStat(homeStats.goals_for_avg, 2)}</strong><br>
                                Goles en contra: <strong>${fmtContextStat(homeStats.goals_against_avg, 2)}</strong><br>
                                Posesión Promedio: <strong>${fmtContextStat(homeStats.avg_possession, 1)}%</strong><br>
                                Promedio Corners: <strong>${fmtContextStat(homeStats.avg_corners, 1)}</strong><br>
                                Tiros al Arco: <strong>${fmtContextStat(homeStats.avg_shots_on_target, 1)}</strong><br>
                                Vallas Invictas: <strong>${fmtContextStat(homeStats.clean_sheets, 0)}</strong>
                            </div>
                        </div>
                        <div class="context-stat" style="align-items: flex-start; padding: 1rem;">
                            <h4 style="color: var(--text-primary); margin-bottom: 0.5rem;">${awayTeam}</h4>
                            <div style="font-size: 0.82rem; color: var(--text-secondary); line-height: 1.6;">
                                Goles a favor: <strong>${fmtContextStat(awayStats.goals_for_avg, 2)}</strong><br>
                                Goles en contra: <strong>${fmtContextStat(awayStats.goals_against_avg, 2)}</strong><br>
                                Posesión Promedio: <strong>${fmtContextStat(awayStats.avg_possession, 1)}%</strong><br>
                                Promedio Corners: <strong>${fmtContextStat(awayStats.avg_corners, 1)}</strong><br>
                                Tiros al Arco: <strong>${fmtContextStat(awayStats.avg_shots_on_target, 1)}</strong><br>
                                Vallas Invictas: <strong>${fmtContextStat(awayStats.clean_sheets, 0)}</strong>
                            </div>
                        </div>
                    </div>
                </div>` : ''}

                <div class="context-section">
                    <h3>🏥 Impacto de Lesiones & Suspensiones</h3>
                    <div class="context-grid">
                        <div class="context-stat"><span class="context-stat-label">Bajas Local</span><span class="context-stat-value" style="color:#ef4444;">${impact.home_players_out || 0}</span></div>
                        <div class="context-stat"><span class="context-stat-label">Bajas Visitante</span><span class="context-stat-value" style="color:#ef4444;">${impact.away_players_out || 0}</span></div>
                        <div class="context-stat"><span class="context-stat-label">Ventaja</span><span class="context-stat-value">${advantageEmoji}</span></div>
                        <div class="context-stat"><span class="context-stat-label">Nivel Impacto</span><span class="context-stat-value">${impact.severity?.impact_level || 'BAJO'}</span></div>
                    </div>
                    <div class="context-recommendation">${impact.severity?.recommendation || 'Sin impacto mayor en el partido'}</div>
                </div>
                
                ${homeInj.length > 0 ? `
                <div class="context-section">
                    <h3>🏥 Bajas / Dudas: ${homeTeam}</h3>
                    ${homeInj.map(i => {
                        const badge = getInjuryBadge(i);
                        return `<div class="injury-mini">${badge.icon} <strong>${i.player}</strong> <span style="opacity:0.7">(${i.position})</span> — ${i.injury_type} <span style="${badge.style} font-weight:bold; font-size:0.7rem; margin-left:5px;">${badge.label}</span></div>`;
                    }).join('')}
                </div>` : ''}
                
                ${awayInj.length > 0 ? `
                <div class="context-section">
                    <h3>🏥 Bajas / Dudas: ${awayTeam}</h3>
                    ${awayInj.map(i => {
                        const badge = getInjuryBadge(i);
                        return `<div class="injury-mini">${badge.icon} <strong>${i.player}</strong> <span style="opacity:0.7">(${i.position})</span> — ${i.injury_type} <span style="${badge.style} font-weight:bold; font-size:0.7rem; margin-left:5px;">${badge.label}</span></div>`;
                    }).join('')}
                </div>` : ''}
                
                ${relevantNews.length > 0 ? `
                <div class="context-section">
                    <h3>📰 Noticias Relevantes</h3>
                    ${relevantNews.map(n => `<div class="news-mini"><strong>${n.headline}</strong><p>${n.description || ''}</p></div>`).join('')}
                </div>` : ''}
            </div>
        </div>
    `;

    document.body.appendChild(modal);
}

// ==================== TELEGRAM ====================
async function testTelegramLegacy() {
    showToast('📲 Probando conexión con Telegram...', 'info');
    const data = await apiCall('/telegram/test', 'POST');
    const statusEl = document.getElementById('telegram-status');

    if (data && data.success) {
        statusEl.textContent = '&#9989; Conectado!';
        statusEl.style.color = '#10b981';
        showToast('&#9989; Telegram conectado! Revisa tu chat.', 'success');
    } else {
        statusEl.textContent = '&#10060; Error';
        statusEl.style.color = '#ef4444';
        showToast('&#10060; Error: ' + (data?.message || 'Configura el token y chat ID'), 'error');
    }
}

async function sendValueBetsTelegram() {
    showToast('📲 Enviando value bets por Telegram...', 'info');
    const data = await apiCall('/telegram/notify-value-bets', 'POST');

    if (data) {
        showToast(`&#9989; ${data.sent || 0} alertas enviadas por Telegram`, 'success');
    } else {
        showToast('&#10060; Error al enviar', 'error');
    }
}

async function sendDailyReportLegacy() {
    showToast('&#128202; Enviando reporte diario...', 'info');
    const data = await apiCall('/telegram/daily-report', 'POST');

    if (data && data.sent) {
        showToast('&#9989; Reporte enviado por Telegram', 'success');
    } else {
        showToast('&#10060; Error al enviar reporte', 'error');
    }
}

// ==================== CHARTS (Canvas) ====================
// drawMarketChart and drawDailyChart have been replaced by
// renderBookmakerChart and drawProfitChart (defined in the DASHBOARD section above).

function roundedRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
}

// ==================== PREDICTIONS ====================
async function loadPredictions() {
    const date = document.getElementById('global-date-filter')?.value;
    let url = '/predictions?upcoming_only=false';
    if (date) url += `&date=${date}`;

    const data = await apiCall(url);
    if (!data || !data.predictions) {
        document.getElementById('predictions-grid').innerHTML = `
            <div class="empty-state"><div class="empty-state-icon">&#127919;</div>
            <div class="empty-state-text">No hay predicciones disponibles</div>
            <div class="empty-state-sub">Entrena los modelos y genera predicciones para próximos partidos</div></div>`;
        return;
    }

    const matchPreds = {};
    data.predictions.forEach(p => {
        const key = p.match_id;
        if (!matchPreds[key]) {
            matchPreds[key] = {
                match_id: p.match_id, home_team: p.home_team_name || 'Local',
                away_team: p.away_team_name || 'Visitante', league: p.league_name || 'Liga',
                match_date: p.match_date, status: p.status, home_goals: p.home_goals,
                away_goals: p.away_goals, markets: [],
            };
        }
        matchPreds[key].markets.push(p);
    });

    document.getElementById('predictions-grid').innerHTML = Object.values(matchPreds).map(match => renderPredictionCard(match)).join('');
}

function renderPredictionCard(match) {
    const dateStr = match.match_date ? new Date(match.match_date).toLocaleDateString('es', {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    }) : '—';

    const statusBadge = match.status === 'FT'
        ? `<span class="badge badge-success">FT ${match.home_goals}-${match.away_goals}</span>`
        : `<span class="badge badge-info">Próximo</span>`;

    const marketsHtml = match.markets.map(m => {
        const confClass = m.confidence === 'HIGH' ? 'success' : (m.confidence === 'MEDIUM' ? 'warning' : 'danger');
        const resultIcon = m.is_correct === 1 ? '&#9989;' : (m.is_correct === 0 ? '&#10060;' : '⏳');
        return `
            <div class="market-pred">
                <span class="market-name">${formatMarketName(m.market)}</span>
                <span class="market-value">${m.prediction}</span>
                <span class="market-prob">${Math.round((m.probability || 0) * 100)}%</span>
                <span class="badge badge-${confClass}">${m.confidence || 'N/A'}</span>
                <span>${resultIcon}</span>
            </div>
        `;
    }).join('');

    return `
        <div class="prediction-card glass-card">
            <div class="prediction-card-header">
                <div class="match-info">
                    <div class="match-teams">${match.home_team} <span class="vs">vs</span> ${match.away_team}</div>
                    <div class="match-meta"><span>&#128197; ${dateStr}</span><span>&#127942; ${match.league}</span></div>
                </div>
                ${statusBadge}
            </div>
            <div class="prediction-markets">${marketsHtml}</div>
        </div>
    `;
}

// ==================== VALUE BETS ====================
async function loadValueBets() {
    const data = await apiCall('/value-bets');
    const container = document.getElementById('value-bets-list');

    if (!data || !data.value_bets || data.value_bets.length === 0) {
        container.innerHTML = `
            <div class="empty-state glass-card" style="padding: 3rem;">
                <div class="empty-state-icon">💎</div>
                <div class="empty-state-text">No hay value bets detectados</div>
                <div class="empty-state-sub">El sistema comparará las probabilidades del modelo con las cuotas del bookmaker</div>
            </div>`;
        return;
    }

    container.innerHTML = data.value_bets.map(vb => {
        const edge = (vb.value_edge || 0) * 100;
        const tierClass = edge >= 15 ? 'premium' : (edge >= 10 ? 'strong' : 'normal');
        const tierLabel = edge >= 15 ? '⚡ PREMIUM' : (edge >= 10 ? '&#128293; FUERTE' : '&#9989; VALUE');

        return `
            <div class="value-bet-card glass-card ${tierClass}">
                <div class="vb-header">
                    <div>
                        <div class="vb-match">${vb.home_team_name || 'Local'} vs ${vb.away_team_name || 'Visitante'}</div>
                        <div class="match-meta">
                            <span>&#128197; ${vb.match_date ? new Date(vb.match_date).toLocaleDateString('es') : '—'}</span>
                            <span>&#127919; ${formatMarketName(vb.market)}: ${vb.prediction}</span>
                        </div>
                    </div>
                    <span class="vb-tier badge badge-premium">${tierLabel}</span>
                </div>
                <div class="vb-details">
                    <div class="vb-detail"><div class="vb-detail-label">Prob. Modelo</div><div class="vb-detail-value" style="color: #10b981;">${Math.round((vb.probability || 0) * 100)}%</div></div>
                    <div class="vb-detail"><div class="vb-detail-label">Value Edge</div><div class="vb-detail-value" style="color: #f59e0b;">${edge.toFixed(1)}%</div></div>
                    <div class="vb-detail"><div class="vb-detail-label">Stake Rec.</div><div class="vb-detail-value">${((vb.recommended_stake || 0) * 100).toFixed(1)}%</div></div>
                    <div class="vb-detail"><div class="vb-detail-label">Confianza</div><div class="vb-detail-value">${vb.confidence || 'N/A'}</div></div>
                </div>
            </div>
        `;
    }).join('');

    document.getElementById('value-badge').textContent = data.value_bets.length;
}

// ==================== PERFORMANCE ====================
async function loadPerformance() {
    const data = await apiCall('/performance');
    if (!data) return;

    const streak = data.streak || {};
    const streakEl = document.getElementById('streak-display');
    if (streak.count > 0) {
        streakEl.textContent = `${streak.count} ${streak.type === 'winning' ? '🟢 Ganadas' : '🔴 Perdidas'}`;
        streakEl.style.color = streak.type === 'winning' ? '#10b981' : '#ef4444';
    } else { streakEl.textContent = '—'; }

    const roi = data.roi || {};
    const profitEl = document.getElementById('profit-display');
    profitEl.textContent = `$${(roi.profit || 0).toFixed(0)}`;
    profitEl.style.color = (roi.profit || 0) >= 0 ? '#10b981' : '#ef4444';
    document.getElementById('bankroll-display')?.textContent; // Handled by loadBankrollData()

    const byMarket = data.by_market || [];
    const breakdownEl = document.getElementById('market-breakdown');

    breakdownEl.innerHTML = byMarket.map(m => {
        const accuracy = m.accuracy || 0;
        const color = accuracy >= 60 ? '#10b981' : (accuracy >= 50 ? '#f59e0b' : '#ef4444');
        const circumference = 2 * Math.PI * 18;
        const offset = circumference - (accuracy / 100) * circumference;

        return `
            <div class="market-card">
                <div class="market-card-header">
                    <h4>${formatMarketName(m.market)}</h4>
                    <div class="accuracy-ring">
                        <svg viewBox="0 0 40 40">
                            <circle cx="20" cy="20" r="18" fill="none" stroke="rgba(255,255,255,0.05)" stroke-width="3"/>
                            <circle cx="20" cy="20" r="18" fill="none" stroke="${color}" stroke-width="3" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" stroke-linecap="round"/>
                        </svg>
                        <span class="accuracy-ring-text" style="color: ${color};">${accuracy}%</span>
                    </div>
                </div>
                <div class="market-stats-row"><span class="market-stats-label">Total</span><span class="market-stats-value">${m.total || 0}</span></div>
                <div class="market-stats-row"><span class="market-stats-label">Ganadas</span><span class="market-stats-value" style="color: #10b981;">${m.wins || 0}</span></div>
                <div class="market-stats-row"><span class="market-stats-label">Perdidas</span><span class="market-stats-value" style="color: #ef4444;">${m.losses || 0}</span></div>
                <div class="market-stats-row"><span class="market-stats-label">Value Bets</span><span class="market-stats-value" style="color: #f59e0b;">${m.value_bets || 0}</span></div>
                <div class="progress-bar"><div class="progress-fill" style="width: ${accuracy}%; background: ${color};"></div></div>
            </div>
        `;
    }).join('');
}

// ==================== MODELS ====================
async function loadModels() {
    const data = await apiCall('/model/info');
    const grid = document.getElementById('models-grid');

    if (!data) {
        grid.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🧠</div><div class="empty-state-text">No hay modelos cargados</div></div>';
        return;
    }

    const metadata = data.training_metadata || {};
    const models = metadata.models || {};

    if (Object.keys(models).length === 0) {
        grid.innerHTML = `<div class="empty-state glass-card" style="grid-column: 1/-1; padding: 3rem;">
            <div class="empty-state-icon">🧠</div><div class="empty-state-text">No hay modelos entrenados</div>
            <div class="empty-state-sub">Primero genera datos demo, luego entrena los modelos</div></div>`;
        return;
    }

    const marketIcons = { 'match_result': '&#127919;', 'over_under_25': '&#9917;', 'btts': '🥅', 'corners': '&#128259;', 'cards': '🟨' };
    const marketColors = {
        'match_result': 'linear-gradient(135deg, #6366f1, #8b5cf6)',
        'over_under_25': 'linear-gradient(135deg, #10b981, #059669)',
        'btts': 'linear-gradient(135deg, #f59e0b, #d97706)',
        'corners': 'linear-gradient(135deg, #3b82f6, #2563eb)',
        'cards': 'linear-gradient(135deg, #ef4444, #dc2626)',
    };

    grid.innerHTML = Object.entries(models).map(([market, info]) => `
        <div class="model-card glass-card">
            <div class="model-card-header">
                <div class="model-icon" style="background: ${marketColors[market] || marketColors.match_result}">${marketIcons[market] || '&#129302;'}</div>
                <div><div class="model-name">${formatMarketName(market)}</div><div class="model-type">${info.model_name || 'N/A'}</div></div>
            </div>
            <div class="model-metrics">
                <div class="metric"><div class="metric-value">${((info.accuracy || 0) * 100).toFixed(1)}%</div><div class="metric-label">Test Accuracy</div></div>
                <div class="metric"><div class="metric-value">${((info.cv_mean || 0) * 100).toFixed(1)}%</div><div class="metric-label">CV Mean</div></div>
                <div class="metric"><div class="metric-value">${info.feature_count || 0}</div><div class="metric-label">Features</div></div>
                <div class="metric"><div class="metric-value">${info.train_size || 0}</div><div class="metric-label">Train Size</div></div>
            </div>
        </div>
    `).join('');
}

async function testTelegram() {
    const sts = document.getElementById('telegram-status');
    sts.textContent = 'Enviando...';
    
    // We try to call the Telegram API Endpoint
    const data = await apiCall('/telegram/test', 'POST');
    if (data && data.success) {
        sts.textContent = '✓ Mensaje enviado';
        sts.style.color = '#10b981';
        showToast('Mensaje de prueba enviado por Telegram', 'success');
    } else {
        sts.textContent = '&#10060; Error de conexión';
        sts.style.color = '#ef4444';
        showToast('Error al enviar test de Telegram. Verifica tu Token y Chat ID.', 'error');
    }
}

async function sendDailyReport() {
    showToast('Generando reporte...', 'info');
    const data = await apiCall('/telegram/daily-report', 'POST');
    if (data && data.status === 'success') {
        showToast('Reporte diario enviado por Telegram', 'success');
    } else {
        showToast('Error al enviar reporte', 'error');
    }
}

async function discoverPatternsLegacy2() {
    showLoading(true);
    showToast('Buscando patrones rentables...', 'info');
    const data = await apiCall('/patterns/discover', 'POST');
    showLoading(false);
    if (data && data.status === 'success') {
        showToast(`Se descubrieron ${data.patterns_found} patrones!`, 'success');
        if(document.getElementById('section-patterns').style.display === 'block') {
            loadPatterns();
        }
    } else {
        showToast('Error al descubrir patrones', 'error');
    }
}

// ==================== SETTINGS (FASE 1: SAVE/LOAD) ====================
function loadSettings() {
    loadDBStats();
    loadSettingsFromServer();
}

async function loadSettingsFromServer() {
    const data = await apiCall('/settings/load');
    if (!data || !data.settings) return;
    const s = data.settings;
    
    // Show status indicators
    if (s.FOOTBALL_API_KEY_SET) {
        const el = document.getElementById('status-football-key');
        if (el) el.textContent = '&#9989; Configurado';
    }
    if (s.TELEGRAM_BOT_TOKEN_SET) {
        const el = document.getElementById('status-telegram-token');
        if (el) el.textContent = '&#9989; Configurado';
    }
}

async function saveAllSettings() {
    const data = {};
    
    const footballKey = document.getElementById('setting-football-key')?.value?.trim();
    const oddsKey = document.getElementById('setting-odds-key')?.value?.trim();
    const fdKey = document.getElementById('setting-footballdata-key')?.value?.trim();
    const tgToken = document.getElementById('setting-telegram-token')?.value?.trim();
    const tgChat = document.getElementById('setting-telegram-chat')?.value?.trim();
    
    if (footballKey) data.FOOTBALL_API_KEY = footballKey;
    if (oddsKey) data.ODDS_API_KEY = oddsKey;
    if (fdKey) data.FOOTBALL_DATA_API_KEY = fdKey;
    if (tgToken) data.TELEGRAM_BOT_TOKEN = tgToken;
    if (tgChat) data.TELEGRAM_CHAT_ID = tgChat;
    
    if (Object.keys(data).length === 0) {
        showToast('No hay cambios para guardar', 'info');
        return;
    }
    
    const result = await apiCall('/settings/save', 'POST', data);
    if (result && result.status === 'success') {
        showToast('Configuracion guardada! Reinicia el servidor para aplicar.', 'success');
        document.getElementById('save-status').textContent = 'Guardado correctamente';
    } else {
        showToast('Error al guardar configuracion', 'error');
    }
}

async function loadDBStats() {
    const data = await apiCall('/health');
    if (!data || !data.database) return;

    const stats = data.database;
    document.getElementById('db-stats').innerHTML = Object.entries(stats).map(([key, value]) => `
        <div class="db-stat"><div class="db-stat-value">${value.toLocaleString()}</div><div class="db-stat-label">${key.replace(/_/g, ' ')}</div></div>
    `).join('');
}

function initSettings() {
    const confidence = document.getElementById('setting-confidence');
    const edge = document.getElementById('setting-value-edge');
    const kelly = document.getElementById('setting-kelly');

    if (confidence) confidence.addEventListener('input', () => document.getElementById('confidence-value').textContent = confidence.value + '%');
    if (edge) edge.addEventListener('input', () => document.getElementById('edge-value').textContent = edge.value + '%');
    if (kelly) kelly.addEventListener('input', () => document.getElementById('kelly-value').textContent = kelly.value + '%');
}

// ==================== PIPELINE FROM DASHBOARD (FASE 1) ====================
async function runPipeline() {
    showLoading(true);
    showToast('Ejecutando Pipeline STUBET... consumiendo tokens API-Football', 'info');
    
    const outputDiv = document.getElementById('pipeline-output');
    const logPre = document.getElementById('pipeline-log');
    if (outputDiv) outputDiv.style.display = 'block';
    if (logPre) logPre.textContent = 'Iniciando pipeline...\n';
    
    const data = await apiCall('/pipeline/run', 'POST');
    showLoading(false);
    
    if (data) {
        if (logPre) logPre.textContent = data.output || 'Sin output';
        if (data.status === 'success') {
            showToast('Pipeline ejecutado exitosamente! Dashboard actualizado.', 'success');
            loadDashboard();
        } else {
            showToast('Pipeline termino con errores. Revisa el log.', 'error');
        }
    } else {
        showToast('Error al ejecutar pipeline', 'error');
    }
}

async function loadScraperStatus() {
    const el = document.getElementById('scraper-status');
    if (!el) return;
    const data = await apiCall('/scraper/status');
    if (data && data.running) {
        el.textContent = 'activo';
        el.style.color = '#10b981';
    } else {
        el.textContent = 'detenido';
        el.style.color = '#f59e0b';
    }
}

async function startLiveScraper() {
    showToast('Iniciando scraper live de LasPlatas...', 'info');
    const data = await apiCall('/scraper/start', 'POST');
    if (data && data.status === 'success') {
        showToast('Scraper live iniciado. Las alertas market-aware quedan activas.', 'success');
    } else {
        showToast('No se pudo iniciar el scraper live.', 'error');
    }
    loadScraperStatus();
}

async function stopLiveScraper() {
    showToast('Deteniendo scraper live...', 'info');
    const data = await apiCall('/scraper/stop', 'POST');
    if (data && data.status === 'success') {
        showToast('Scraper live detenido.', 'success');
    } else {
        showToast('No se pudo detener el scraper live.', 'error');
    }
    loadScraperStatus();
}

// ==================== MULTI-SPORT: NBA & TENNIS (FASE 2) ====================
let currentSport = 'soccer';

function switchSport(sport) {
    currentSport = sport;
    
    // Update tab styling
    document.querySelectorAll('.sport-tab').forEach(tab => {
        tab.classList.remove('active', 'btn-primary');
        tab.classList.add('btn-secondary');
    });
    const activeTab = document.getElementById('tab-' + sport);
    if (activeTab) {
        activeTab.classList.add('active', 'btn-primary');
        activeTab.classList.remove('btn-secondary');
    }
    
    // Update filters UI display
    const soccerFilters = document.getElementById('soccer-filters');
    const sofascoreSubfilter = document.getElementById('sofascore-subfilter-container');
    const leagueFilter = document.getElementById('live-league-filter');
    
    if (sport === 'soccer') {
        if (soccerFilters) soccerFilters.style.display = 'flex';
        if (leagueFilter) leagueFilter.parentElement.style.display = 'block'; // Show league drilldown
        loadLiveScoreboard();
    } else {
        clearLiveScoreboardAutoRefresh();
        clearLiveClockTicker();
        if (soccerFilters) soccerFilters.style.display = 'flex'; // Keep the bar for Date
        if (leagueFilter) leagueFilter.parentElement.style.display = 'none'; // Hide league box
        if (sofascoreSubfilter) sofascoreSubfilter.style.display = 'none';
        loadMultisportScoreboard(sport);
    }
}

async function loadMultisportScoreboard(sport) {
    const grid = document.getElementById('live-matches-grid');
    grid.innerHTML = '<div class="loading-inline"><div class="spinner-sm"></div> Cargando partidos...</div>';
    
    // Check if there is a selected date
    const dateInput = document.getElementById('live-date-filter');
    let dateParam = '';
    if (dateInput && dateInput.value) {
        // Date input is YYYY-MM-DD. ESPN wants YYYYMMDD
        dateParam = `&date=${dateInput.value.replace(/-/g, '')}`;
    }
    
    // Pass upcoming_only=true so it doesn't show finished matches
    const data = await apiCall(`/multisport/scoreboard/${sport}?upcoming_only=true${dateParam}`);
    
    if (!data || !data.matches || data.matches.length === 0) {
        grid.innerHTML = `<div class="empty-state glass-card">
            <span style="font-size:3rem;">${sport === 'nba' ? '🏀' : '🎾'}</span>
            <p>No hay partidos disponibles ahora</p>
        </div>`;
        return;
    }
    
    const sportEmoji = sport === 'nba' ? '🏀' : '🎾';
    
    grid.innerHTML = data.matches.map(m => {
        const isLive = m.isLive;
        const statusClass = isLive ? 'live-badge' : '';
        const bgGlow = isLive ? 'border: 1px solid rgba(239,68,68,0.4); box-shadow: 0 0 15px rgba(239,68,68,0.1);' : '';
        
        const imageStyle = 'width:44px; height:44px; object-fit:contain; border-radius:50%; background:white; padding:4px; box-shadow:0 4px 6px -1px rgba(0,0,0,0.1); margin-bottom:0.5rem;';
        
        return `
            <div class="match-card glass-card" style="${bgGlow}; padding:1.5rem; border-radius:12px;">
                <div class="match-card-header" style="justify-content:center; position:relative;">
                    <span class="match-league" style="position:absolute; left:0; font-size:0.7rem; letter-spacing:0.5px;">${sportEmoji} ${m.sport?.toUpperCase() || ''}</span>
                    ${isLive ? '<span class="live-badge-sm">🔴 EN JUEGO</span>' : `<span class="match-time" style="background:rgba(255,255,255,0.1); padding:0.2rem 0.6rem; border-radius:12px; font-weight:600;">${new Date(m.date).toLocaleString('es', {hour:'2-digit', minute:'2-digit'})}</span>`}
                </div>
                <div class="match-card-teams" style="display:flex; justify-content:space-between; align-items:center; padding:1.2rem 0;">
                    <div class="team" style="text-align:center; flex:1; display:flex; flex-direction:column; align-items:center;">
                        ${m.home.logo ? `<img src="${m.home.logo}" style="${imageStyle}" alt="">` : '<div style="width:44px;height:44px;border-radius:50%;background:#374151;margin-bottom:0.5rem"></div>'}
                        <div style="font-weight:700; font-size:0.9rem; color:#f3f4f6; text-align:center;">${m.home.abbreviation || m.home.name}</div>
                    </div>
                    <div class="score" style="font-size:2.2rem; font-weight:800; padding:0 1.5rem; color:${isLive ? '#ef4444' : '#e5e7eb'}; letter-spacing:2px;">
                        ${m.home.score} - ${m.away.score}
                    </div>
                    <div class="team" style="text-align:center; flex:1; display:flex; flex-direction:column; align-items:center;">
                        ${m.away.logo ? `<img src="${m.away.logo}" style="${imageStyle}" alt="">` : '<div style="width:44px;height:44px;border-radius:50%;background:#374151;margin-bottom:0.5rem"></div>'}
                        <div style="font-weight:700; font-size:0.9rem; color:#f3f4f6; text-align:center;">${m.away.abbreviation || m.away.name}</div>
                    </div>
                </div>
                <div class="match-card-footer" style="font-size:0.75rem; opacity:0.6; text-align:center;">
                    ${m.status} ${m.venue ? '| ' + m.venue : ''} ${m.broadcast ? '| 📺 ' + m.broadcast : ''}
                </div>
                <div style="margin-top:0.75rem; border-top:1px solid rgba(255,255,255,0.05); padding-top:0.75rem;">
                    <button class="btn btn-secondary btn-sm" style="width:100%; font-size:0.75rem;" onclick="analyzeMultisportMatch('${sport}', '${m.id}')" id="btn-analyze-${m.id}">🔍 Analizar con IA</button>
                    <div id="ai-results-${m.id}" style="margin-top:0.5rem; display:none;"></div>
                </div>
            </div>
        `;
    }).join('');
    
    // Almacenar data en global scope para uso en botones
    window.currentMultisportData = data.matches;
}

window.analyzeMultisportMatch = async function(sport, matchId) {
    const btn = document.getElementById(`btn-analyze-${matchId}`);
    if(btn) btn.innerHTML = '<div class="spinner-sm"></div> Analizando...';
    
    const matchData = window.currentMultisportData.find(m => m.id == matchId);
    if(!matchData) return;
    
    const res = await apiCall('/multisport/predict', 'POST', { sport: sport, match: matchData });
    if(btn) btn.innerHTML = '🔍 Analizar con IA';
    
    if(res && res.status === 'success' && res.predictions.length > 0) {
        const container = document.getElementById(`ai-results-${matchId}`);
        container.style.display = 'block';
        container.innerHTML = `
            <div style="background:rgba(0,0,0,0.3); padding:0.75rem; border-radius:6px; border-left:3px solid #06b6d4;">
                <div style="margin-bottom:0.75rem; font-weight:600; color:#a5f3fc; font-size:0.85rem; display:flex; align-items:center;">
                    <span style="margin-right:0.4rem;">&#129302;</span> Análisis Tipster Profesional
                </div>
                <div style="display:flex; flex-direction:column; gap:0.6rem;">
                    ${res.predictions.map(p => `
                        <div style="background:rgba(255,255,255,0.03); padding:0.5rem; border-radius:4px;">
                            <div style="display:flex; justify-content:space-between; font-size:0.75rem; margin-bottom:0.3rem;">
                                <span style="opacity:0.9; font-weight:500;">${p.market}</span>
                                <span style="font-weight:700; color:${p.confidence === 'HIGH' ? '#34d399' : '#fbbf24'};">${p.prediction}</span>
                            </div>
                            <div style="font-size:0.65rem; color:#9ca3af; line-height:1.4;">
                                <i>${p.rationale || 'Análisis algorítmico basado en métricas recientes.'}</i>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }
}

// ==================== NEWS MULTI-SPORT (FASE 3) ====================
function onNewsSportChange() {
    const sport = document.getElementById('news-sport-filter')?.value;
    const leagueGroup = document.getElementById('news-league-group');
    
    if (sport === 'soccer') {
        if (leagueGroup) leagueGroup.style.display = '';
    } else {
        if (leagueGroup) leagueGroup.style.display = 'none';
        loadMultisportNews(sport);
    }
}

async function loadMultisportNews(sport) {
    const newsList = document.getElementById('news-list');
    newsList.innerHTML = '<div class="loading-inline"><div class="spinner-sm"></div> Cargando noticias...</div>';
    
    const data = await apiCall(`/multisport/news/${sport}`);
    
    if (!data || !data.news || data.news.length === 0) {
        newsList.innerHTML = '<div class="empty-state glass-card"><p>No hay noticias disponibles</p></div>';
        return;
    }
    
    newsList.innerHTML = data.news.map(article => {
        const date = article.published
            ? new Date(article.published).toLocaleDateString('es', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
            : '';
        const imgHtml = article.images && article.images[0]
            ? `<img src="${article.images[0]}" style="width:100%; max-height:150px; object-fit:cover; border-radius:8px; margin-bottom:0.5rem;" alt="">`
            : '';
        return `
            <div class="news-card glass-card">
                ${imgHtml}
                <div class="news-type">${article.type === 'HeadlineNews' ? '&#128293;' : '📰'} ${article.type || 'Story'}</div>
                <h4 class="news-headline">${article.headline || ''}</h4>
                <p class="news-description">${article.description || ''}</p>
                <div class="news-footer">
                    <span class="news-date">&#128197; ${date}</span>
                    ${article.link ? `<a href="${article.link}" target="_blank" class="news-link">Leer mas</a>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

// ==================== ACTIONS ====================
async function trainModels() {
    showLoading(true);
    showToast('Entrenando modelos... esto puede tomar un momento', 'info');
    const data = await apiCall('/train', 'POST');
    showLoading(false);
    if (data && data.status === 'success') { showToast('Modelos entrenados exitosamente!', 'success'); loadModels(); }
    else showToast('Error: ' + (data?.message || 'Error al entrenar. Primero ejecuta el Pipeline para obtener datos.'), 'error');
}

async function collectData() {
    showLoading(true);
    showToast('Recopilando datos de la liga...', 'info');
    const data = await apiCall('/collect/fixtures?league_id=39&season=2025', 'POST');
    showLoading(false);
    if (data) { showToast('Datos recopilados!', 'success'); loadDashboard(); }
    else showToast('Error al recopilar datos. Verifica tus API keys en Configuracion.', 'error');
}

async function settleResults() {
    const data = await apiCall('/settle', 'POST');
    if (data && data.status === 'success') { showToast(`${data.settled} predicciones liquidadas`, 'success'); loadDashboard(); }
    else showToast('Error al liquidar', 'error');
}

async function generateDemo() {
    showToast('Demo data desactivada. Usa solo pipeline y datos reales.', 'info');
}

async function discoverPatterns() {
    showLoading(true);
    showToast('Buscando patrones rentables...', 'info');
    const data = await apiCall('/patterns/discover', 'POST');
    showLoading(false);
    if (data && data.status === 'success') {
        showToast(`Se descubrieron ${data.patterns_found} patrones!`, 'success');
        if(document.getElementById('section-patterns').style.display === 'block') {
            loadPatterns();
        }
    } else showToast('Error al descubrir patrones', 'error');
}



async function refreshData() {
    showToast('Actualizando...', 'info');
    await loadDashboard();
    showToast('Dashboard actualizado', 'success');
}

function filterPredictions() { loadPredictions(); }

// ==================== RENDERING HELPERS ====================
function renderRecentPredictions(predictions) {
    const tbody = document.getElementById('recent-predictions-body');
    if (!predictions || predictions.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty-state"><div style="padding: 2rem;">Sin predicciones aún — Ejecuta pipeline o espera alertas reales</div></td></tr>`;
        return;
    }

    tbody.innerHTML = predictions.slice(0, 15).map(p => {
        const date = p.match_date ? new Date(p.match_date).toLocaleDateString('es', { month: 'short', day: 'numeric' }) : '—';
        const confClass = p.confidence === 'HIGH' ? 'success' : (p.confidence === 'MEDIUM' ? 'warning' : 'danger');
        let resultHtml = '<span class="badge badge-info">Pendiente</span>';
        if (p.is_correct === 1) resultHtml = '<span class="badge badge-success">Acertada</span>';
        else if (p.is_correct === 0) resultHtml = '<span class="badge badge-danger">Fallida</span>';
        const valueBadge = p.is_value_bet ? '<span class="badge badge-premium">Value</span>' : '<span class="badge" style="opacity: 0.3;">—</span>';

        return `<tr>
            <td>${date}</td>
            <td style="font-weight: 600;">${p.home_team || '?'} vs ${p.away_team || '?'}</td>
            <td><span style="color: var(--text-muted);">${p.league || '—'}</span></td>
            <td>${formatMarketName(p.market)}</td>
            <td style="font-weight: 600;">${p.prediction}</td>
            <td><span class="badge badge-${confClass}">${Math.round((p.probability || 0) * 100)}%</span></td>
            <td>${valueBadge}</td>
            <td>${resultHtml}</td>
        </tr>`;
    }).join('');
}

// ==================== UTILITIES ====================
function formatMarketName(market) {
    const names = {
        'match_result': '1X2', 'over_under_25': 'O/U 2.5', 'btts': 'BTTS',
        'corners': 'Corners', 'corners_total': 'Corners Total',
        'corners_home': 'Corners Local', 'corners_away': 'Corners Visita',
        'cards': 'Tarjetas', 'cards_total': 'Cards Total',
        'cards_home': 'Cards Local', 'cards_away': 'Cards Visita',
        'shots_on_target': 'SOT', 'shots_on_target_total': 'SOT Total',
        'shots_total': 'Remates Total',
        'goalkeeper_saves': 'Atajadas', 'fouls_total': 'Faltas',
        'offsides_total': 'Offsides', 'asian_handicap': 'Asian HC',
        'O/U 2.5': 'O/U 2.5',
    };
    return names[market] || market;
}

function animateValue(elementId, start, end, duration) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const range = end - start;
    const startTime = performance.now();
    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(start + range * eased).toLocaleString();
        if (progress < 1) requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
}

function showLoading(show) {
    const overlay = document.getElementById('loading-overlay');
    if (show) overlay.classList.add('active');
    else overlay.classList.remove('active');
}

async function loadBankrollData() {
    try {
        const dateFilter = document.getElementById('filter-pick-date')?.value || '';
        const bkFilter = document.getElementById('filter-bookmaker')?.value || '';
        let url = '/api/picks';
        const params = new URLSearchParams();
        if (dateFilter) params.append('date', dateFilter);
        if (bkFilter) params.append('bookmaker', bkFilter);
        if (params.toString()) url += `?${params.toString()}`;

        const [bankrollRes, picksRes] = await Promise.all([
            apiCall('/bankroll', 'GET'),
            apiCall(url, 'GET')
        ]);
        
        const lpData = bankrollRes?.lasplatas;
        const lpVal = lpData && lpData.starting > 0 ? `Bs ${lpData.current.toFixed(2)}` : 'Por fijar';
        const lpDiff = lpData && lpData.starting > 0 ? lpData.current - lpData.starting : 0;
        const lpProfitStr = `Bs ${lpDiff >= 0 ? '+' : ''}${lpDiff.toFixed(2)}`;
        
        const setEl = (id, val, color = null) => {
            const el = document.getElementById(id);
            if (el) {
                el.textContent = val;
                if (color) el.style.color = color;
            }
        };

        setEl('bankroll-lp', lpVal);
        setEl('header-bankroll-lp', lpVal);
        setEl('lp-monthly-profit', lpProfitStr, lpDiff >= 0 ? '#10b981' : '#ef4444');
        setEl('header-profit-lp', lpProfitStr, lpDiff >= 0 ? '#10b981' : '#ef4444');
        
        const mbData = bankrollRes?.metabet;
        const mbVal = mbData && mbData.starting > 0 ? `Bs ${mbData.current.toFixed(2)}` : 'Por fijar';
        const mbDiff = mbData && mbData.starting > 0 ? mbData.current - mbData.starting : 0;
        const mbProfitStr = `Bs ${mbDiff >= 0 ? '+' : ''}${mbDiff.toFixed(2)}`;

        setEl('bankroll-mb', mbVal);
        setEl('header-bankroll-mb', mbVal);
        setEl('mb-monthly-profit', mbProfitStr, mbDiff >= 0 ? '#f59e0b' : '#ef4444');
        setEl('header-profit-mb', mbProfitStr, mbDiff >= 0 ? '#f59e0b' : '#ef4444');
        
        const totalStarting = (lpData?.starting || 0) + (mbData?.starting || 0);
        const totalCurrent = (lpData?.current || 0) + (mbData?.current || 0);
        const profitEl = document.getElementById('profit-display');
        if (profitEl && totalStarting > 0) {
            const diff = totalCurrent - totalStarting;
            profitEl.textContent = `Bs ${diff >= 0 ? '+' : ''}${diff.toFixed(0)}`;
            profitEl.style.color = diff >= 0 ? '#10b981' : '#ef4444';
        }
        
        renderManualPicks(picksRes);
        renderDailyReport(picksRes, dateFilter);
    } catch (e) {
        console.error("Error loading bankroll", e);
    }
}

function renderManualPicks(picks) {
    const tbody = document.getElementById('manual-picks-body');
    if (!picks || picks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #64748b;">No hay apuestas en este periodo.</td></tr>';
        return;
    }

    tbody.innerHTML = picks.map(p => {
        const isParlay = p.bet_type === 'parlay';
        const dateObj = new Date(p.date + 'Z');
        const formattedDate = dateObj.toLocaleDateString('es-ES', { day: '2-digit', month: 'short' }) + ' ' + 
                              dateObj.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
        
        let resultLabel = '';
        if (p.result === 'PENDING') resultLabel = '<span style="color:#fbbf24; background:rgba(251,191,36,0.1); padding:2px 6px; border-radius:4px;">PENDIENTE</span>';
        else if (p.result === 'WON') resultLabel = '<span style="color:#10b981; background:rgba(16,185,129,0.1); padding:2px 6px; border-radius:4px;">GANADA</span>';
        else if (p.result === 'LOST') resultLabel = '<span style="color:#ef4444; background:rgba(239,68,68,0.1); padding:2px 6px; border-radius:4px;">PERDIDA</span>';
        else if (p.result === 'VOID') resultLabel = '<span style="color:#94a3b8; background:rgba(148,163,184,0.1); padding:2px 6px; border-radius:4px;">ANULADA</span>';
        else if (p.result === 'CASHOUT') resultLabel = '<span style="color:#3b82f6; background:rgba(59,130,246,0.1); padding:2px 6px; border-radius:4px;">CASH OUT</span>';
        else if (p.result === 'HALF_WON') resultLabel = '<span style="color:#34d399; background:rgba(52,211,153,0.1); padding:2px 6px; border-radius:4px;">1/2 GANA</span>';
        else if (p.result === 'HALF_LOST') resultLabel = '<span style="color:#f87171; background:rgba(248,113,113,0.1); padding:2px 6px; border-radius:4px;">1/2 PIERDE</span>';

        const bkIcon = p.bookmaker === 'metabet' ? '🟡' : '🟢';
        const actions = getSettleActionContent(p);

        return `
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                <td style="font-size:0.8rem; color:#94a3b8;">${formattedDate}</td>
                <td style="font-size:0.9rem;">${bkIcon}</td>
                <td style="font-size:0.9rem; font-weight:500;">
                    ${p.match}
                    ${p.is_draw_no_bet ? '<span style="font-size:0.7rem; color:#f59e0b; margin-left:4px;">(DNB)</span>' : ''}
                </td>
                <td style="font-size:0.85rem; color:#cbd5e1; max-width:200px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${p.market}">${p.market}</td>
                <td style="font-weight:700; color:#f59e0b;">@${p.odds.toFixed(2)}</td>
                <td style="font-weight:500;">Bs ${p.stake.toFixed(2)}</td>
                <td>${resultLabel} ${p.profit ? `<br><small style="color:${p.profit>0?'#10b981':'#ef4444'}">${p.profit>0?'+':''}Bs ${p.profit.toFixed(2)}</small>` : ''}</td>
                <td>
                    <div style="display:flex; flex-direction:column; gap:4px;">
                        ${actions}
                    </div>
                </td>
            </tr>
            ${isParlay && p.result === 'PENDING' ? `<tr><td colspan="8" style="padding:0; border:0;"><div id="parlay-legs-${p.id}" style="display:none; background:rgba(0,0,0,0.2); padding:10px; margin:0 20px 10px 20px; border-radius:8px; border-left:2px solid #3b82f6;"></div></td></tr>` : ''}
        `;
    }).join('');
}

function getSettleActionContent(p) {
    if (p.result !== 'PENDING') {
        return `<button onclick="deletePick(${p.id})" style="background:none; border:none; color:#ef4444; cursor:pointer;" title="Eliminar">🗑️</button>`;
    }

    if (p.bet_type === 'parlay') {
        return `
            <div style="display:flex; gap:4px;">
                <button class="btn btn-primary btn-sm" onclick="toggleParlayLegs(${p.id})">👁️ Patas</button>
                <button class="btn btn-secondary btn-sm" onclick="deletePick(${p.id})" title="Eliminar">🗑️</button>
            </div>
            <div style="display:flex; gap:4px; margin-top:4px;">
                <input type="number" id="co-${p.id}" style="width:50px; font-size:10px; padding:2px;" placeholder="CO Bs">
                <button class="btn btn-secondary btn-sm" style="font-size:10px; padding:2px 4px; background:#3b82f6; border:none;" onclick="settlePick(${p.id}, 'CASHOUT')">Cobrar</button>
            </div>
        `;
    }

    return `
        <div style="display:flex; gap:4px; justify-content:flex-start;">
            <button class="btn btn-secondary btn-sm" style="font-size:10px; padding:2px 4px; background:rgba(16,185,129,0.2); color:#10b981; border:1px solid #10b981;" onclick="settlePick(${p.id}, 'WON')">✅</button>
            <button class="btn btn-secondary btn-sm" style="font-size:10px; padding:2px 4px; background:rgba(239,68,68,0.2); color:#ef4444; border:1px solid #ef4444;" onclick="settlePick(${p.id}, 'LOST')">❌</button>
            <button class="btn btn-secondary btn-sm" style="font-size:10px; padding:2px 4px; background:rgba(148,163,184,0.2); color:#94a3b8; border:1px solid #94a3b8;" onclick="settlePick(${p.id}, 'VOID')" title="Anulada/VOID">🔄</button>
            <button onclick="editPick(${p.id})" style="background:none; border:none; color:#3b82f6; cursor:pointer; font-size:12px;" title="Editar">✏️</button>
            <button onclick="deletePick(${p.id})" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:12px;" title="Eliminar">🗑️</button>
        </div>
        <div style="display:flex; gap:4px; margin-top:4px;">
            <button class="btn btn-secondary btn-sm" style="font-size:10px; padding:2px 4px; color:#34d399;" onclick="settlePick(${p.id}, 'HALF_WON')" title="Medio Gana">½ G</button>
            <button class="btn btn-secondary btn-sm" style="font-size:10px; padding:2px 4px; color:#f87171;" onclick="settlePick(${p.id}, 'HALF_LOST')" title="Medio Pierde">½ P</button>
            <input type="number" id="co-${p.id}" style="width:50px; font-size:10px; padding:2px;" placeholder="CO Bs">
            <button class="btn btn-secondary btn-sm" style="font-size:10px; padding:2px 4px; background:#3b82f6; border:none;" onclick="settlePick(${p.id}, 'CASHOUT')">CO</button>
        </div>
    `;
}

async function settlePick(id, result) {
    let payload = { result: result };
    if (result === 'CASHOUT') {
        const amt = parseFloat(document.getElementById(`co-${id}`)?.value);
        if (isNaN(amt)) {
            showToast("Ingresa el monto de Cash Out", "error");
            return;
        }
        payload.cashout_amount = amt;
    } else {
        if (!confirm(`¿Estás seguro de marcar esta apuesta como ${result}?`)) return;
    }

    const res = await apiCall(`/picks/${id}/settle`, 'POST', payload);
    if (res && res.status === 'success') {
        showToast("Apuesta liquidada correctamente", "success");
        loadBankrollData();
    }
}

async function toggleParlayLegs(pickId) {
    const div = document.getElementById(`parlay-legs-${pickId}`);
    if (div.style.display === 'block') {
        div.style.display = 'none';
        return;
    }
    
    div.innerHTML = '<div style="color:#94a3b8; font-size:12px;">Cargando...</div>';
    div.style.display = 'block';
    
    const res = await apiCall(`/picks/${pickId}/legs`, 'GET');
    if (res && res.legs) {
        div.innerHTML = res.legs.map(leg => {
            let resLabel = '';
            if (leg.result === 'PENDING') resLabel = `
                <button onclick="settleParlayLeg(${leg.id}, 'WON')" style="background:#10b981; border:none; border-radius:3px; padding:2px 5px; color:white; font-size:10px; cursor:pointer;">✅</button>
                <button onclick="settleParlayLeg(${leg.id}, 'LOST')" style="background:#ef4444; border:none; border-radius:3px; padding:2px 5px; color:white; font-size:10px; cursor:pointer;">❌</button>
                <button onclick="settleParlayLeg(${leg.id}, 'VOID')" style="background:#64748b; border:none; border-radius:3px; padding:2px 5px; color:white; font-size:10px; cursor:pointer;">🔄</button>
                <button onclick="settleParlayLeg(${leg.id}, 'HALF_WON')" style="background:#34d399; border:none; border-radius:3px; padding:2px 5px; color:white; font-size:10px; cursor:pointer;">½G</button>
                <button onclick="settleParlayLeg(${leg.id}, 'HALF_LOST')" style="background:#f87171; border:none; border-radius:3px; padding:2px 5px; color:white; font-size:10px; cursor:pointer;">½P</button>
            `;
            else resLabel = `<span style="font-size:10px; font-weight:bold; color:${leg.result==='WON'?'#10b981':(leg.result==='LOST'?'#ef4444':'#94a3b8')}">${leg.result}</span>`;
            
            return `
            <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05);">
                <span style="font-size:11px;">
                    <b>${leg.match_name}</b> ${leg.is_draw_no_bet?'(DNB)':''} <br>
                    <span style="color:#a5f3fc;">${leg.market}</span> <span style="color:#f59e0b;">@${leg.odds}</span>
                </span>
                <div style="display:flex; gap:4px;">${resLabel}</div>
            </div>
            `;
        }).join('');
    } else {
        div.innerHTML = '<div style="color:#ef4444; font-size:12px;">Error al cargar patas</div>';
    }
}

async function settleParlayLeg(legId, result) {
    if (!confirm(`¿Marcar esta pata como ${result}?`)) return;
    const res = await apiCall(`/picks/parlay/leg/${legId}/settle`, 'POST', { result: result });
    if (res && res.status === 'success') {
        showToast("Pata resuelta", "success");
        loadBankrollData();
    }
}

const BK_COLORS = {
    lasplatas: { bg: 'rgba(16,185,129,0.15)', border: '#10b981', text: '#10b981', label: '🟢 LP' },
    metabet:   { bg: 'rgba(245,158,11,0.15)', border: '#f59e0b', text: '#f59e0b', label: '🟡 MB' }
};

function resetPickFilter() {
    const filterInput = document.getElementById('filter-pick-date');
    if (filterInput) filterInput.value = '';
    loadBankrollData();
}

function renderDailyReport(picks, filterDate) {
    const reportContainer = document.getElementById('daily-report');
    if (!reportContainer) return;

    const dateLabel = document.getElementById('daily-report-date');
    if (dateLabel) {
        dateLabel.textContent = filterDate ? `Día: ${filterDate}` : 'Global del Mes';
    }

    const stats = {
        lasplatas: { invested: 0, wins: 0, losses: 0, profit: 0 },
        metabet: { invested: 0, wins: 0, losses: 0, profit: 0 }
    };
    
    let pendingCount = 0;

    picks.forEach(p => {
        const bk = (p.bookmaker || 'lasplatas').toLowerCase();
        if (!stats[bk]) return;

        stats[bk].invested += p.stake;
        if (p.result === 'WON') {
            stats[bk].wins++;
            stats[bk].profit += (p.stake * p.odds) - p.stake;
        } else if (p.result === 'LOST') {
            stats[bk].losses++;
            stats[bk].profit -= p.stake;
        } else {
            pendingCount++;
        }
    });

    const setVal = (id, val, color = null) => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = val;
            if (color) el.style.color = color;
        }
    };

    setVal('lp-daily-invested', `Bs ${stats.lasplatas.invested.toFixed(0)}`);
    setVal('lp-daily-wl', `${stats.lasplatas.wins}-${stats.lasplatas.losses}`);
    setVal('lp-daily-net', `Bs ${stats.lasplatas.profit >= 0 ? '+' : ''}${stats.lasplatas.profit.toFixed(0)}`, 
           stats.lasplatas.profit >= 0 ? '#10b981' : '#ef4444');

    setVal('mb-daily-invested', `Bs ${stats.metabet.invested.toFixed(0)}`);
    setVal('mb-daily-wl', `${stats.metabet.wins}-${stats.metabet.losses}`);
    setVal('mb-daily-net', `Bs ${stats.metabet.profit >= 0 ? '+' : ''}${stats.metabet.profit.toFixed(0)}`, 
           stats.metabet.profit >= 0 ? '#10b981' : '#ef4444');

    const pendingNote = document.getElementById('daily-pending-note');
    const pendingCountSpan = document.getElementById('daily-pending-count');
    if (pendingNote && pendingCountSpan) {
        if (pendingCount > 0) {
            pendingNote.style.display = 'block';
            pendingCountSpan.textContent = pendingCount;
        } else {
            pendingNote.style.display = 'none';
        }
    }
}

async function addManualPick() {
    const match = document.getElementById('manual-match').value.trim();
    const market = document.getElementById('manual-market').value.trim();
    const odds = parseFloat(document.getElementById('manual-odds').value);
    const stake = parseFloat(document.getElementById('manual-stake').value);
    const dateStr = document.getElementById('manual-placed-at').value;
    const bookmaker = document.getElementById('manual-bookmaker').value;
    const isDNB = document.getElementById('manual-dnb').checked;

    if (!match || !market || !odds || !stake) {
        showToast("Por favor llena partido, mercado, cuota e inversión", "error");
        return;
    }

    const payload = {
        match: match,
        market: market,
        odds: odds,
        stake: stake,
        bookmaker: bookmaker,
        bet_type: 'single',
        is_draw_no_bet: isDNB
    };
    
    const res = await apiCall('/picks', 'POST', payload);
    
    if (res && res.status === 'success') {
        const label = bookmaker === 'metabet' ? 'Metabet' : 'LasPlatas';
        showToast(`Pick registrado en ${label}.`, "success");
        document.getElementById('manual-match').value = '';
        document.getElementById('manual-market').value = '';
        document.getElementById('manual-odds').value = '';
        document.getElementById('manual-stake').value = '';
        loadBankrollData();
    }
}

async function addCombiLeg() {
    const match = document.getElementById('combi-match').value.trim();
    const market = document.getElementById('combi-market').value.trim();
    const odds = parseFloat(document.getElementById('combi-leg-odds').value);
    const isDNB = document.getElementById('combi-dnb').checked;

    if (!match || !market || !odds || odds <= 1) {
        showToast("Llena partido, mercado y cuota (>1.00)", "error");
        return;
    }

    combiLegs.push({ match_name: match, market, odds, is_draw_no_bet: isDNB });
    document.getElementById('combi-match').value = '';
    document.getElementById('combi-market').value = '';
    document.getElementById('combi-leg-odds').value = '';
    document.getElementById('combi-dnb').checked = false;
    renderCombiLegs();
    showToast(`Selección agregada: ${match} — ${market} @${odds}`, "success");
}

function renderCombiLegs() {
    const container = document.getElementById('combi-legs-list');
    const oddsDisplay = document.getElementById('combi-odds-value');
    const countDisplay = document.getElementById('combi-legs-count');

    if (combiLegs.length === 0) {
        container.innerHTML = '<div style="text-align: center; padding: 12px; color: #64748b; font-size: 0.85rem; border: 1px dashed #334155; border-radius: 8px;">Agrega selecciones con el botón ➕ de arriba</div>';
        oddsDisplay.textContent = '—';
        countDisplay.textContent = '0 selecciones';
        return;
    }

    const combinedOdds = combiLegs.reduce((acc, leg) => acc * leg.odds, 1);
    oddsDisplay.textContent = `@${combinedOdds.toFixed(4)}`;
    countDisplay.textContent = `${combiLegs.length} seleccion${combiLegs.length > 1 ? 'es' : ''}`;

    container.innerHTML = combiLegs.map((leg, i) => `
        <div style="display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: rgba(255,255,255,0.03); border-radius: 6px; margin-bottom: 4px; border-left: 3px solid ${i === 0 ? '#10b981' : (i === 1 ? '#3b82f6' : '#f59e0b')};">
            <span style="font-weight: 700; color: #94a3b8; font-size: 0.8rem; min-width: 20px;">#${i + 1}</span>
            <span style="flex: 2; font-weight: 500; font-size: 0.85rem;">${leg.match_name} ${leg.is_draw_no_bet ? '<span style="color:#f59e0b;font-size:0.7rem;">(DNB)</span>' : ''}</span>
            <span style="flex: 1; color: #a5f3fc; font-size: 0.85rem;">${leg.market}</span>
            <span style="font-weight: 700; color: #f59e0b; min-width: 60px; text-align: right;">@${leg.odds.toFixed(2)}</span>
            <button onclick="removeCombiLeg(${i})" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:1rem; padding:2px 6px;" title="Quitar">✕</button>
        </div>
    `).join('');
}

function clearCombiLegs() {
    combiLegs = [];
    renderCombiLegs();
}

async function saveCombiPick() {
    if (combiLegs.length < 2) {
        showToast("Agrega al menos 2 selecciones para una combinada", "error");
        return;
    }

    const stake = parseFloat(document.getElementById('combi-stake').value);
    if (!stake || stake <= 0) {
        showToast("Ingresa la inversión total", "error");
        return;
    }

    const bookmaker = document.getElementById('manual-bookmaker').value;

    const res = await apiCall('/picks/parlay', 'POST', {
        stake: stake,
        bookmaker: bookmaker,
        legs: combiLegs
    });

    if (res && res.status === 'success') {
        const label = bookmaker === 'metabet' ? 'Metabet' : 'LasPlatas';
        showToast(`Combinada de ${combiLegs.length} patas guardada en ${label}`, "success");
        clearCombiLegs();
        document.getElementById('combi-stake').value = '';
        loadBankrollData();
    }
}

function removeCombiLeg(index) {
    combiLegs.splice(index, 1);
    renderCombiLegs();
}

async function scanTicket() {
    const ticketId = document.getElementById('ticket-id').value;
    const bookmaker = document.getElementById('scanner-bookmaker').value;
    
    if (!ticketId) {
        showToast("Ingresa el código o link", "error");
        return;
    }
    
    document.getElementById('ticket-id').value = "Escaneando...";
    
    try {
        const res = await apiCall('/scraper/ticket', 'POST', { ticket_id: ticketId, bookmaker });
        if (res && res.status === 'success') {
            const bkDetected = res.bookmaker || bookmaker;
            const label = bkDetected === 'metabet' ? 'Metabet' : 'LasPlatas';
            
            if (res.note) {
                showToast(`Datos extraidos de ${label}. Verifica y ajusta.`, "warning");
                document.getElementById('manual-bookmaker').value = bkDetected;
                document.getElementById('manual-match').value = res.match || '';
                document.getElementById('manual-market').value = res.market || '';
                document.getElementById('manual-odds').value = res.odds || '';
                document.getElementById('manual-stake').value = res.stake || '';
                document.getElementById('ticket-id').value = "";
            } else {
                showToast(`Cupón de ${label} escaneado!`, "success");
                await addManualPick();
                document.getElementById('ticket-id').value = "";
            }
        } else {
            showToast(res?.message || "Error leyendo cupón/link", "error");
            document.getElementById('ticket-id').value = ticketId;
        }
    } catch (e) {
        showToast("Error de red", "error");
        document.getElementById('ticket-id').value = ticketId;
    }
}

async function deletePick(pickId) {
    if (!confirm("¿Seguro que deseas eliminar esta apuesta? El dinero invertido volverá al Bankroll de esa casa.")) return;
    
    try {
        const res = await apiCall(`/picks/${pickId}`, 'DELETE');
        if (res && res.status === 'success') {
            showToast("Apuesta eliminada. Dinero devuelto.", "success");
            loadBankrollData();
        } else {
            showToast("No se pudo eliminar la apuesta.", "error");
        }
    } catch (e) {
        showToast("Error al eliminar", "error");
    }
}

async function autoResolvePicks() {
    showLoading(true);
    const loadingText = document.querySelector('#loading-overlay p');
    if (loadingText) loadingText.textContent = 
        'Buscando resultados en SofaScore...';
    
    try {
        const res = await apiCall('/picks/auto-resolve', 'POST');
        showLoading(false);
        if (loadingText) loadingText.textContent = 
            'Procesando datos con IA...';
        
        if (res && res.status === 'success') {
            let msg = res.message;
            if (res.details && res.details.length > 0) {
                const won  = res.details.filter(d => d.result === 'WON').length;
                const lost = res.details.filter(d => d.result === 'LOST').length;
                const skip = res.skipped || 0;
                msg = `✅ ${won} ganadas, ❌ ${lost} perdidas, ⏭️ ${skip} manuales`;
            }
            showToast(msg, 'success');
            
            const manual = (res.details || [])
                .filter(d => d.status === 'skipped' && d.score);
            
            if (manual.length > 0) {
                const manualList = manual.map(d => 
                    `• ${d.pick}: ${d.score} → ${d.reason}`
                ).join('\n');
                console.log('[AutoResolve] Resolución manual requerida:\n' 
                    + manualList);
                showToast(
                    `${manual.length} pick(s) necesitan resolución manual`, 
                    'info'
                );
            }
            
            loadBankrollData();
            loadDashboard();
        } else {
            showToast(res?.message || 
                'Error en auto-resolver', 'error');
        }
    } catch (e) {
        showLoading(false);
        showToast('Error de conexión', 'error');
    }
}

async function openEditModal(pickId) {
    const pick = await apiCall(`/picks/${pickId}`);
    if (!pick) return;
    
    document.getElementById('edit-pick-id').value = pick.id;
    document.getElementById('edit-match').value = pick.match;
    document.getElementById('edit-market').value = pick.market;
    document.getElementById('edit-odds').value = pick.odds;
    document.getElementById('edit-stake').value = pick.stake;
    document.getElementById('edit-bookmaker').value = pick.bookmaker;
    
    if (pick.date) {
        const dt = new Date(pick.date);
        const pad = (n) => n.toString().padStart(2, '0');
        const formattedDate = `${dt.getFullYear()}-${pad(dt.getMonth()+1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
        document.getElementById('edit-placed-at').value = formattedDate;
    }
    
    document.getElementById('edit-pick-modal').style.display = 'flex';
}

function closeEditModal() {
    document.getElementById('edit-pick-modal').style.display = 'none';
}

async function submitUpdatePick() {
    const pickId = document.getElementById('edit-pick-id').value;
    const match = document.getElementById('edit-match').value;
    const market = document.getElementById('edit-market').value;
    const odds = parseFloat(document.getElementById('edit-odds').value);
    const stake = parseFloat(document.getElementById('edit-stake').value);
    const bookmaker = document.getElementById('edit-bookmaker').value;
    const dateValue = document.getElementById('edit-placed-at').value;
    
    let placed_at = null;
    if (dateValue) {
        placed_at = dateValue.replace('T', ' ') + ':00';
    }
    
    const res = await apiCall(`/picks/${pickId}`, 'PUT', {
        match, market, odds, stake, bookmaker, placed_at
    });
    
    if (res && res.status === 'success') {
        showToast("Apuesta actualizada correctamente.", "success");
        closeEditModal();
        loadBankrollData();
    } else {
        showToast(res?.message || "No se pudo actualizar la apuesta.", "error");
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const ticketInput = document.getElementById('ticket-id');
    const scannerSelect = document.getElementById('scanner-bookmaker');
    if (ticketInput && scannerSelect) {
        ticketInput.addEventListener('input', () => {
            const val = ticketInput.value.trim();
            if (val.startsWith('http') || val.includes('metabet')) {
                scannerSelect.value = 'metabet';
            } else if (val.length > 0 && !val.startsWith('http')) {
                scannerSelect.value = 'lasplatas';
            }
        });
    }
});

function setBetType(type) {
    const singleForm = document.getElementById('single-bet-form');
    const combiForm = document.getElementById('combi-bet-form');
    const btnSingle = document.getElementById('btn-type-single');
    const btnCombi = document.getElementById('btn-type-combi');
    const combiDisplay = document.getElementById('combi-odds-display');

    if (type === 'single') {
        singleForm.style.display = 'block';
        combiForm.style.display = 'none';
        combiDisplay.style.display = 'none';
        btnSingle.classList.replace('btn-secondary', 'btn-primary');
        btnCombi.classList.replace('btn-primary', 'btn-secondary');
    } else {
        singleForm.style.display = 'none';
        combiForm.style.display = 'block';
        combiDisplay.style.display = 'block';
        btnCombi.classList.replace('btn-secondary', 'btn-primary');
        btnSingle.classList.replace('btn-primary', 'btn-secondary');
        renderCombiLegs();
    }
}

setTimeout(loadBankrollData, 1500);

let lastDeepAnalysisData = null;

async function getDeepAnalysis(eventId, homeTeamId, awayTeamId, homeName, awayName) {
    console.log('[Analizar Top]', { eventId, homeTeamId, awayTeamId, homeName, awayName });
    
    if (!eventId || !homeTeamId || !awayTeamId ||
        homeTeamId === 0 || awayTeamId === 0 ||
        isNaN(homeTeamId) || isNaN(awayTeamId)) {
        showToast('IDs de equipo no disponibles para este partido', 'error');
        return;
    }

    const loadingText = document.querySelector('#loading-overlay p');
    const originalText = loadingText ? loadingText.textContent : 'Procesando datos con IA...';
    if (loadingText) loadingText.textContent = 'Recopilando estadísticas de SofaScore...';
    
    showLoading(true);
    
    const bodyPayload = {
        event_id: eventId,
        home_team_id: homeTeamId,
        away_team_id: awayTeamId,
        home_name: homeName,
        away_name: awayName
    };

    const data = await apiCall('/analyze/match', 'POST', bodyPayload, { noCache: true });
    
    showLoading(false);
    if (loadingText) loadingText.textContent = originalText;

    if (!data || Object.keys(data).length === 0) {
        showToast('No se pudo recopilar la información', 'error');
        return;
    }

    lastDeepAnalysisData = { req: bodyPayload, data: data };
    renderDeepAnalysisModal(homeName, awayName, data);
}

function renderDeepAnalysisModal(homeName, awayName, data) {
    document.getElementById('da-modal-title').innerHTML = `&#128293; Análisis Profundo: ${homeName} vs ${awayName}`;
    const body = document.getElementById('da-modal-body');
    body.innerHTML = '';

    function renderMatchesSection(title, matches) {
        if (!matches || matches.length === 0) return '';
        let html = `<h4 style="margin-top:20px; margin-bottom:10px; color:var(--accent-color); border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:5px;">${title}</h4>`;
        
        matches.forEach(m => {
            const info = m.match_info || {};
            const stats = m.statistics || [];
            
            html += `<div style="background:rgba(0,0,0,0.3); border-radius:8px; padding:12px; margin-bottom:15px; border:1px solid rgba(255,255,255,0.05);">`;
            html += `<div style="font-weight:bold; margin-bottom:8px;">${info.date || ''} | ${info.competition || ''} | ${info.home || '?'} ${info.home_score ?? '-'} - ${info.away_score ?? '-'} ${info.away || '?'}</div>`;
            
            stats.forEach(period => {
                html += `<div style="margin-top:10px; font-size:0.9rem; color:#cbd5e1; font-weight:bold;">--- ${period.period || 'Periodo'} ---</div>`;
                const groups = period.groups || [];
                groups.forEach(group => {
                    html += `<div style="margin-top:5px; font-size:0.85rem; color:#94a3b8;">[${group.groupName || 'Stats'}]</div>`;
                    const items = group.statisticsItems || [];
                    html += `<table style="width:100%; font-size:0.8rem; margin-bottom:5px;">`;
                    items.forEach(item => {
                        html += `<tr>
                            <td style="width:20%; text-align:right; color:#a5f3fc;">${item.home ?? '-'}</td>
                            <td style="width:60%; text-align:center;">${item.name || ''}</td>
                            <td style="width:20%; text-align:left; color:#a5f3fc;">${item.away ?? '-'}</td>
                        </tr>`;
                    });
                    html += `</table>`;
                });
            });
            html += `</div>`;
        });
        return html;
    }

    body.innerHTML += renderMatchesSection(`Últimos 10 — ${homeName}`, data.home_last10);
    body.innerHTML += renderMatchesSection(`Últimos 10 — ${awayName}`, data.away_last10);
    body.innerHTML += renderMatchesSection('H2H (Cara a Cara)', data.h2h);

    document.getElementById('deep-analysis-modal').style.display = 'flex';
}

function closeDeepAnalysisModal() {
    document.getElementById('deep-analysis-modal').style.display = 'none';
}

async function downloadDeepAnalysisPDF() {
    if (!lastDeepAnalysisData) {
        showToast("No hay datos para generar el PDF", "error");
        return;
    }
    
    showToast("Generando PDF...", "info");
    try {
        const response = await fetch(API_BASE + '/analyze/match/pdf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                home_name: lastDeepAnalysisData.req.home_name,
                away_name: lastDeepAnalysisData.req.away_name,
                data: lastDeepAnalysisData.data
            })
        });
        
        if (!response.ok) throw new Error("Network response was not ok");
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `Analysis_${lastDeepAnalysisData.req.home_name}_vs_${lastDeepAnalysisData.req.away_name}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
    } catch (e) {
        console.error("PDF download error:", e);
        showToast("Error al descargar PDF", "error");
    }
}

// ==================== LIVE ALERT ENGINE ====================
async function startLiveAlerts() {
    const res = await apiCall('/alerts/live/start', 'POST');
    if (res && res.status === 'success') {
        showToast('Motor de alertas iniciado. Recibirás alertas en Telegram.', 'success');
        updateLiveAlertStatus();
    } else {
        showToast('Error al iniciar alertas', 'error');
    }
}

async function stopLiveAlerts() {
    const res = await apiCall('/alerts/live/stop', 'POST');
    if (res && res.status === 'success') {
        showToast('Motor de alertas detenido', 'info');
        updateLiveAlertStatus();
    }
}

async function updateLiveAlertStatus() {
    const res = await apiCall('/alerts/live/status');
    if (!res) return;

    const badge = document.getElementById('live-alert-status-badge');
    const count = document.getElementById('alerts-sent-count');

    if (badge) {
        if (res.running) {
            badge.textContent = '● ACTIVO';
            badge.style.background = 'rgba(16,185,129,0.2)';
            badge.style.color = '#10b981';
        } else {
            badge.textContent = 'DETENIDO';
            badge.style.background = 'rgba(239,68,68,0.2)';
            badge.style.color = '#ef4444';
        }
    }
    if (count) {
        count.textContent = res.alerts_sent_today || 0;
    }
}

// Intercept loadModels to update alert status
if (typeof loadModels === 'function') {
    const _origLoadModels = loadModels;
    window.loadModels = async function() {
        await _origLoadModels();
        updateLiveAlertStatus();
    };
}

// Update status every 30 seconds if on models section
setInterval(() => {
    if (appState && appState.currentSection === 'models') {
        updateLiveAlertStatus();
    }
}, 30000);
