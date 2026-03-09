const app = document.getElementById('app');
const tabBtns = document.querySelectorAll('.tab-btn');
const validTabs = new Set(['home', 'burnout', 'chatbot']);

let activeTab = null;
let cleanupActiveSection = null;
let chatbotScriptPromise = null;

function setActiveTabButton(tabName) {
    tabBtns.forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
}

function setLoadingState() {
    if (app) {
        app.innerHTML = '<div class="loading">Loading section...</div>';
    }
}

async function loadSectionMarkup(tabName) {
    const response = await fetch(`sections/${tabName}.html`);
    if (!response.ok) {
        throw new Error(`Failed to load ${tabName} section (HTTP ${response.status})`);
    }
    return response.text();
}

function showSectionError(message) {
    if (app) {
        app.innerHTML = `<div class="error">${message}</div>`;
    }
}

async function ensureChatbotScriptLoaded() {
    if (window.initChatbot) {
        return;
    }

    if (!chatbotScriptPromise) {
        chatbotScriptPromise = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'chatbot.js';
            script.async = true;
            script.onload = resolve;
            script.onerror = () => reject(new Error('Could not load chatbot.js'));
            document.body.appendChild(script);
        });
    }

    await chatbotScriptPromise;
}

async function activateSection(tabName) {
    if (!validTabs.has(tabName)) {
        return;
    }

    if (!app || activeTab === tabName) {
        return;
    }

    if (typeof cleanupActiveSection === 'function') {
        cleanupActiveSection();
        cleanupActiveSection = null;
    }

    activeTab = tabName;
    setActiveTabButton(tabName);
    setLoadingState();

    try {
        const html = await loadSectionMarkup(tabName);
        app.innerHTML = html;
        if (window.location.hash !== `#${tabName}`) {
            window.history.replaceState(null, '', `#${tabName}`);
        }

        if (tabName === 'burnout') {
            cleanupActiveSection = initBurnoutSection();
        }

        if (tabName === 'chatbot') {
            await ensureChatbotScriptLoaded();
            if (window.initChatbot) {
                window.initChatbot();
            }
        }
    } catch (error) {
        showSectionError(`Unable to load section: ${error.message}`);
    }
}

for (const btn of tabBtns) {
    btn.addEventListener('click', () => {
        const tabName = btn.dataset.tab;
        activateSection(tabName);
    });
}

window.addEventListener('hashchange', () => {
    const requestedTab = window.location.hash.replace('#', '');
    if (validTabs.has(requestedTab)) {
        activateSection(requestedTab);
    }
});

const initialTab = window.location.hash.replace('#', '');
activateSection(validTabs.has(initialTab) ? initialTab : 'home');

function initBurnoutSection() {
    const burnoutForm = document.getElementById('burnoutForm');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const debugStatus = document.getElementById('debugStatus');
    const syncStatusPanel = document.getElementById('syncStatusPanel');
    const syncStatusText = document.getElementById('syncStatusText');
    const metricsSourceSelect = document.getElementById('metrics_source');
    const manualMetricsSection = document.getElementById('manualMetrics');
    const restingHrInput = document.getElementById('resting_hr');
    const hrvAvgInput = document.getElementById('hrv_avg');

    let syncStatusTimer = null;
    let lastResolvedWatchMetrics = {
        restingHr: null,
        hrvAvg: null,
        dataDate: null,
    };

    function setStatus(text) {
        if (debugStatus) {
            debugStatus.textContent = `Status: ${text}`;
        }
    }

    function formatUtcToLocal(isoText) {
        if (!isoText) {
            return 'never';
        }
        const d = new Date(isoText);
        if (Number.isNaN(d.getTime())) {
            return isoText;
        }
        return d.toLocaleString();
    }

    async function refreshSyncStatus() {
        if (!syncStatusPanel || !syncStatusText) {
            return;
        }

        const backendUrlInput = document.getElementById('backend_url');
        const backendUrl = backendUrlInput?.value?.trim()?.replace(/\/$/, '');
        if (!backendUrl) {
            syncStatusPanel.classList.remove('ok', 'warn', 'error');
            syncStatusPanel.classList.add('warn');
            syncStatusText.textContent = 'Set Backend URL to read server auto-sync status.';
            return;
        }

        try {
            const response = await fetch(`${backendUrl}/sync/status`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            const sync = data?.sync || {};
            const enabled = !!sync.enabled;
            const success = sync.last_run_success;
            const running = !!sync.task_running;
            const finishedAt = formatUtcToLocal(sync.last_run_finished_at);

            syncStatusPanel.classList.remove('ok', 'warn', 'error');

            if (!enabled) {
                syncStatusPanel.classList.add('warn');
                syncStatusText.textContent = 'Auto-sync is disabled on server (set GARMIN_AUTO_SYNC_ENABLED=true).';
                return;
            }

            if (success === true) {
                syncStatusPanel.classList.add('ok');
                syncStatusText.textContent = `Auto-sync is ON (${sync.interval_minutes} min). Last success: ${finishedAt}.${running ? ' Sync currently running.' : ''}`;
                return;
            }

            if (success === false) {
                syncStatusPanel.classList.add('error');
                syncStatusText.textContent = `Auto-sync last run failed at ${finishedAt}. ${sync.last_error || ''}`.trim();
                return;
            }

            syncStatusPanel.classList.add('warn');
            syncStatusText.textContent = `Auto-sync is ON (${sync.interval_minutes} min). Waiting for first completed run...`;
        } catch (error) {
            syncStatusPanel.classList.remove('ok', 'warn', 'error');
            syncStatusPanel.classList.add('error');
            syncStatusText.textContent = `Cannot read /sync/status: ${error.message}`;
        }
    }

    function setManualMetricsVisibility() {
        if (!manualMetricsSection || !metricsSourceSelect) {
            return;
        }

        const isManual = metricsSourceSelect.value === 'manual';
        manualMetricsSection.classList.toggle('hidden', !isManual);
    }

    async function resolveWatchMetrics(backendUrl, userId) {
        let restingHr = null;
        let hrvAvg = null;
        let dataDate = null;
        let summaryDate = null;

        try {
            const summaryResponse = await fetch(`${backendUrl}/summary/latest?user_id=${encodeURIComponent(userId)}`);
            if (summaryResponse.ok) {
                const summary = await summaryResponse.json();
                if (Number.isFinite(summary?.resting_hr)) {
                    restingHr = Number(summary.resting_hr);
                }
                if (typeof summary?.date === 'string' && summary.date) {
                    summaryDate = summary.date;
                }
            }
        } catch (error) {
            console.warn('Could not load summary/latest for watch metrics', error);
        }

        try {
            const syncResponse = await fetch(`${backendUrl}/sync/status`);
            if (syncResponse.ok) {
                const syncData = await syncResponse.json();
                const latestDayData = syncData?.sync?.last_result?.latest_day_data || {};
                const daySnapshots = Array.isArray(syncData?.sync?.last_result?.garmin_day_snapshots)
                    ? syncData.sync.last_result.garmin_day_snapshots
                    : [];

                const latestValidSnapshot = [...daySnapshots]
                    .reverse()
                    .find((day) => Number.isFinite(day?.hrv_avg) && day.hrv_avg > 0);

                if (latestValidSnapshot) {
                    if (Number.isFinite(latestValidSnapshot?.hrv_avg)) {
                        hrvAvg = Number(latestValidSnapshot.hrv_avg);
                    }
                    if (Number.isFinite(latestValidSnapshot?.resting_hr)) {
                        restingHr = Number(latestValidSnapshot.resting_hr);
                    }
                    if (typeof latestValidSnapshot?.date === 'string' && latestValidSnapshot.date) {
                        dataDate = latestValidSnapshot.date;
                    }
                }

                if (Number.isFinite(latestDayData?.hrv_avg)) {
                    hrvAvg = Number(latestDayData.hrv_avg);
                }
                if (!Number.isFinite(restingHr) && Number.isFinite(latestDayData?.resting_hr)) {
                    restingHr = Number(latestDayData.resting_hr);
                }
                if (!dataDate && typeof latestDayData?.date === 'string' && latestDayData.date) {
                    dataDate = latestDayData.date;
                }
            }
        } catch (error) {
            console.warn('Could not load sync/status for watch metrics', error);
        }

        const resolved = {
            restingHr: Number.isFinite(restingHr) ? restingHr : null,
            hrvAvg: Number.isFinite(hrvAvg) ? hrvAvg : null,
            dataDate: dataDate || summaryDate || null,
        };

        lastResolvedWatchMetrics = resolved;
        return resolved;
    }

    async function prefillManualMetricsFromWatch() {
        const backendUrl = document.getElementById('backend_url')?.value?.trim()?.replace(/\/$/, '');
        const userId = document.getElementById('user_id')?.value?.trim();

        if (!backendUrl || !userId) {
            return;
        }

        let watchMetrics = lastResolvedWatchMetrics;
        if (!Number.isFinite(watchMetrics?.restingHr) || !Number.isFinite(watchMetrics?.hrvAvg)) {
            watchMetrics = await resolveWatchMetrics(backendUrl, userId);
        }

        if (restingHrInput && Number.isFinite(watchMetrics.restingHr)) {
            restingHrInput.value = String(watchMetrics.restingHr);
        }

        if (hrvAvgInput && Number.isFinite(watchMetrics.hrvAvg)) {
            hrvAvgInput.value = String(watchMetrics.hrvAvg);
        }
    }

    function showError(message) {
        const resultSection = document.getElementById('resultSection');
        const resultBox = document.getElementById('resultBox');
        const recommendationsBox = document.getElementById('recommendations');

        if (!resultSection || !resultBox || !recommendationsBox) {
            return;
        }

        resultSection.style.display = 'block';
        resultBox.className = 'result-box high';
        resultBox.innerHTML = '<br> Burnout Risk: <strong>UNAVAILABLE</strong>';
        recommendationsBox.innerHTML = `<div class="error">${message}</div>`;
    }

    function getTopDrivers(riskResult, summaryResult) {
        const drivers = [];

        const addDriver = (label) => {
            if (!drivers.includes(label) && drivers.length < 3) {
                drivers.push(label);
            }
        };

        const factors = Array.isArray(riskResult?.explanation) ? riskResult.explanation : [];
        factors.forEach((factor) => {
            const text = String(factor).toLowerCase();
            if (text.includes('low hrv') || text.includes('hrv below')) {
                addDriver('low HRV');
            } else if (text.includes('high resting hr') || text.includes('resting heart rate')) {
                addDriver('high resting HR');
            } else if (text.includes('sleep')) {
                addDriver('sleep drop');
            }
        });

        const sleepMinutes = summaryResult?.sleep_minutes;
        if (Number.isFinite(sleepMinutes) && sleepMinutes > 0 && sleepMinutes < 420) {
            addDriver('sleep drop');
        }

        const restingHr = summaryResult?.resting_hr;
        if (Number.isFinite(restingHr) && restingHr >= 75) {
            addDriver('high resting HR');
        }

        return drivers.slice(0, 3);
    }

    function getRecommendations(riskResult, summaryResult, riskLevel) {
        let html = '<h3>Recommendations:</h3><ul>';

        const sleepMinutes = summaryResult?.sleep_minutes || 0;
        const steps = summaryResult?.steps || 0;
        const restingHr = summaryResult?.resting_hr || 0;

        if (sleepMinutes > 0 && sleepMinutes < 420) {
            html += '<li>Aim for 7-9 hours of quality sleep each night</li>';
        }

        if (restingHr > 75) {
            html += '<li>Resting HR is elevated. Prioritize recovery and reduce high-intensity load for a day or two</li>';
        }

        if (steps < 8000) {
            html += '<li>Increase daily activity to at least 8,000 steps</li>';
        }

        if (Array.isArray(riskResult?.explanation) && riskResult.explanation.length) {
            html += `<li>Model factors: ${riskResult.explanation.join('; ')}</li>`;
        }

        if (riskLevel === 'HIGH') {
            html += '<li>Consider speaking with a mental health professional</li>';
        }

        if (riskLevel === 'LOW') {
            html += '<li>Great job maintaining your well-being! Keep up the healthy habits</li>';
        }

        html += '</ul>';
        return html;
    }

    function displayResults(riskResult, summaryResult) {
        const resultSection = document.getElementById('resultSection');
        const resultBox = document.getElementById('resultBox');
        const recommendationsBox = document.getElementById('recommendations');

        if (!resultSection || !resultBox || !recommendationsBox) {
            return;
        }

        resultSection.style.display = 'block';

        const riskScore = riskResult.risk_score || 0;
        let riskLevel;
        let riskClass;
        let icon;

        if (riskScore < 40) {
            riskLevel = 'LOW';
            riskClass = 'low';
            icon = '[LOW]';
        } else if (riskScore < 70) {
            riskLevel = 'MODERATE';
            riskClass = 'moderate';
            icon = '[WARN]';
        } else {
            riskLevel = 'HIGH';
            riskClass = 'high';
            icon = '[HIGH]';
        }

        const confidenceSuffix = Number.isFinite(riskResult?.confidence)
            ? `<br><small>Model confidence: ${Number(riskResult.confidence).toFixed(2)}%</small>`
            : '';
        const assessedDate = riskResult?.date || summaryResult?.date || null;
        const assessedDateSuffix = assessedDate
            ? `<br><small>Data date assessed: ${assessedDate}</small>`
            : '';
        const topDrivers = getTopDrivers(riskResult, summaryResult);
        const topDriversText = topDrivers.length
            ? topDrivers.join('; ')
            : 'insufficient signal in current data';
        const topDriversSuffix = `<br><small>Top drivers: ${topDriversText}</small>`;

        resultBox.className = `result-box ${riskClass}`;
        resultBox.innerHTML = `${icon} <br> Burnout Risk: <strong>${riskLevel}</strong> (${Number(riskScore).toFixed(1)}%)${confidenceSuffix}${assessedDateSuffix}${topDriversSuffix}`;
        recommendationsBox.innerHTML = getRecommendations(riskResult, summaryResult, riskLevel);
    }

    async function runBurnoutAnalysis(event) {
        setStatus('analyzing...');

        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }

        const userId = document.getElementById('user_id')?.value?.trim();
        const backendUrl = document.getElementById('backend_url')?.value?.trim()?.replace(/\/$/, '');
        const metricSource = metricsSourceSelect?.value || 'watch';

        const manualRestingHr = parseFloat(document.getElementById('resting_hr')?.value);
        const manualHrvAvg = parseFloat(document.getElementById('hrv_avg')?.value);

        if (!userId) {
            setStatus('missing user_id');
            showError('Please enter a user_id.');
            return;
        }

        if (!backendUrl) {
            setStatus('missing backend_url');
            showError('Please enter a backend URL.');
            return;
        }

        let restingHr = metricSource === 'manual' && Number.isFinite(manualRestingHr)
            ? manualRestingHr
            : null;
        let hrvAvg = metricSource === 'manual' && Number.isFinite(manualHrvAvg)
            ? manualHrvAvg
            : null;
        let watchDataDate = null;

        if (metricSource === 'watch') {
            setStatus('reading watch metrics');
            const watchMetrics = await resolveWatchMetrics(backendUrl, userId);
            restingHr = watchMetrics.restingHr ?? restingHr;
            hrvAvg = watchMetrics.hrvAvg ?? hrvAvg;
            watchDataDate = watchMetrics.dataDate || null;

            if (restingHrInput && Number.isFinite(restingHr)) {
                restingHrInput.value = String(restingHr);
            }

            if (hrvAvgInput && Number.isFinite(hrvAvg)) {
                hrvAvgInput.value = String(hrvAvg);
            }
        }

        if (!Number.isFinite(hrvAvg) || hrvAvg <= 0) {
            setStatus('missing hrv_avg');
            showError(
                metricSource === 'watch'
                    ? 'No watch HRV found. Switch Metrics Source to "Enter metrics manually" and provide HRV Average.'
                    : 'Please enter a valid HRV Average (RMSSD).'
            );
            return;
        }

        try {
            if (analyzeBtn) {
                analyzeBtn.disabled = true;
            }

            const today = new Date().toISOString().slice(0, 10);
            const analysisDate = metricSource === 'watch' ? watchDataDate : today;

            if (metricSource === 'manual') {
                setStatus('sending ingest');
                const ingestPayload = {
                    user_id: userId,
                    date: analysisDate,
                    steps: null,
                    sleep_minutes: null,
                    resting_hr: Number.isFinite(restingHr) ? restingHr : null,
                    avg_hr: null,
                    hr_samples_count: null,
                };

                const ingestResponse = await fetch(`${backendUrl}/ingest/healthkit`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(ingestPayload),
                });

                if (!ingestResponse.ok) {
                    const body = await ingestResponse.text();
                    throw new Error(`Ingest failed (${ingestResponse.status})${body ? `: ${body}` : ''}`);
                }
            }

            setStatus('requesting notebook-model risk');
            const notebookPayload = {
                user_id: userId,
                date: analysisDate,
                resting_hr: Number.isFinite(restingHr) ? restingHr : null,
                avg_hr: null,
                hrv_avg: hrvAvg,
            };

            const riskResponse = await fetch(`${backendUrl}/risk/notebook`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(notebookPayload),
            });

            let riskResult;
            if (riskResponse.ok) {
                riskResult = await riskResponse.json();
            } else {
                const fallbackResponse = await fetch(`${backendUrl}/risk/latest?user_id=${encodeURIComponent(userId)}`);
                if (!fallbackResponse.ok) {
                    const body = await riskResponse.text();
                    throw new Error(`Risk request failed (${riskResponse.status})${body ? `: ${body}` : ''}`);
                }
                riskResult = await fallbackResponse.json();
                if (!Array.isArray(riskResult.explanation)) {
                    riskResult.explanation = [];
                }
                riskResult.explanation.unshift('notebook model unavailable, showing latest baseline risk');
            }

            setStatus('requesting summary');
            const summaryResponse = await fetch(`${backendUrl}/summary/latest?user_id=${encodeURIComponent(userId)}`);
            let summaryResult = null;
            if (summaryResponse.ok) {
                summaryResult = await summaryResponse.json();
            }

            displayResults(riskResult, summaryResult);
            setStatus('done');
            await refreshSyncStatus();
        } catch (error) {
            console.error('Error:', error);
            setStatus(`error: ${error.message}`);
            showError(`Error: ${error.message}. Make sure FastAPI is running on ${backendUrl}.`);
            await refreshSyncStatus();
        } finally {
            if (analyzeBtn) {
                analyzeBtn.disabled = false;
            }
        }
    }

    if (burnoutForm) {
        burnoutForm.addEventListener('submit', (event) => {
            event.preventDefault();
            event.stopPropagation();
        });
    }

    if (analyzeBtn) {
        analyzeBtn.addEventListener('click', runBurnoutAnalysis);
    }

    if (metricsSourceSelect) {
        metricsSourceSelect.addEventListener('change', async () => {
            setManualMetricsVisibility();
            if (metricsSourceSelect.value === 'manual') {
                await prefillManualMetricsFromWatch();
            }
        });
    }

    const backendUrlInput = document.getElementById('backend_url');
    if (backendUrlInput) {
        backendUrlInput.addEventListener('change', refreshSyncStatus);
        backendUrlInput.addEventListener('blur', refreshSyncStatus);
    }

    setManualMetricsVisibility();
    refreshSyncStatus();
    syncStatusTimer = window.setInterval(refreshSyncStatus, 60000);

    return () => {
        if (syncStatusTimer) {
            window.clearInterval(syncStatusTimer);
            syncStatusTimer = null;
        }
    };
}
