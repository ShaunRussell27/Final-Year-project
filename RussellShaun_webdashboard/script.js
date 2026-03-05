// Tab switching logic
const tabBtns = document.querySelectorAll('.tab-btn');
const tabContents = document.querySelectorAll('.tab-content');

function activateTab(tabName) {
    tabContents.forEach(content => content.classList.remove('active'));
    tabBtns.forEach(b => b.classList.remove('active'));

    const targetTab = document.getElementById(tabName);
    const targetBtn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
    if (targetTab) {
        targetTab.classList.add('active');
    }
    if (targetBtn) {
        targetBtn.classList.add('active');
    }
}

tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const tabName = btn.getAttribute('data-tab');
        activateTab(tabName);
    });
});

activateTab('burnout');

// BURNOUT DETECTION Tab
const burnoutForm = document.getElementById('burnoutForm');
const analyzeBtn = document.getElementById('analyzeBtn');
const debugStatus = document.getElementById('debugStatus');
const syncStatusPanel = document.getElementById('syncStatusPanel');
const syncStatusText = document.getElementById('syncStatusText');
const metricsSourceSelect = document.getElementById('metrics_source');
const manualMetricsSection = document.getElementById('manualMetrics');
const restingHrInput = document.getElementById('resting_hr');
const hrvAvgInput = document.getElementById('hrv_avg');

let lastResolvedWatchMetrics = {
    restingHr: null,
    hrvAvg: null,
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

if (metricsSourceSelect) {
    metricsSourceSelect.addEventListener('change', async () => {
        setManualMetricsVisibility();
        if (metricsSourceSelect.value === 'manual') {
            await prefillManualMetricsFromWatch();
        }
    });
}

setManualMetricsVisibility();

async function resolveWatchMetrics(backendUrl, userId) {
    let restingHr = null;
    let hrvAvg = null;

    try {
        const summaryResponse = await fetch(`${backendUrl}/summary/latest?user_id=${encodeURIComponent(userId)}`);
        if (summaryResponse.ok) {
            const summary = await summaryResponse.json();
            if (Number.isFinite(summary?.resting_hr)) {
                restingHr = Number(summary.resting_hr);
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
            if (Number.isFinite(latestDayData?.hrv_avg)) {
                hrvAvg = Number(latestDayData.hrv_avg);
            }
            if (!Number.isFinite(restingHr) && Number.isFinite(latestDayData?.resting_hr)) {
                restingHr = Number(latestDayData.resting_hr);
            }
        }
    } catch (error) {
        console.warn('Could not load sync/status for watch metrics', error);
    }

    const resolved = {
        restingHr: Number.isFinite(restingHr) ? restingHr : null,
        hrvAvg: Number.isFinite(hrvAvg) ? hrvAvg : null,
    };

    lastResolvedWatchMetrics = resolved;
    return resolved;
}

if (burnoutForm) {
    burnoutForm.addEventListener('submit', (e) => {
        e.preventDefault();
        e.stopPropagation();
        return false;
    });
}

window.runBurnoutAnalysis = async (e) => {
        setStatus('analyzing...');
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }

        activateTab('burnout');
        refreshSyncStatus();
        setInterval(refreshSyncStatus, 60000);

        const userId = document.getElementById('user_id').value.trim();
        const backendUrl = document.getElementById('backend_url').value.trim().replace(/\/$/, '');
        const metricSource = metricsSourceSelect?.value || 'watch';

        const manualRestingHr = parseFloat(document.getElementById('resting_hr').value);
        const manualHrvAvg = parseFloat(document.getElementById('hrv_avg').value);

        if (!userId) {
            setStatus('missing user_id');
            showError('Please enter a user_id.');
            return;
        }

        let restingHr = Number.isFinite(manualRestingHr) ? manualRestingHr : null;
        let hrvAvg = Number.isFinite(manualHrvAvg) ? manualHrvAvg : null;

        if (metricSource === 'watch') {
            setStatus('reading watch metrics');
            const watchMetrics = await resolveWatchMetrics(backendUrl, userId);
            restingHr = watchMetrics.restingHr ?? restingHr;
            hrvAvg = watchMetrics.hrvAvg ?? hrvAvg;

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
            analyzeBtn.disabled = true;
            setStatus('sending ingest');
        // Optional manual ingest so dashboard can work without iOS upload.
        const today = new Date().toISOString().slice(0, 10);
        const ingestPayload = {
            user_id: userId,
            date: today,
            steps: null,
            sleep_minutes: null,
            resting_hr: Number.isFinite(restingHr) ? restingHr : null,
            avg_hr: null,
            hr_samples_count: null,
        };

            const ingestResponse = await fetch(`${backendUrl}/ingest/healthkit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(ingestPayload)
            });
            if (!ingestResponse.ok) {
                const body = await ingestResponse.text();
                throw new Error(`Ingest failed (${ingestResponse.status})${body ? `: ${body}` : ''}`);
            }

            setStatus('requesting notebook-model risk');
            const notebookPayload = {
                user_id: userId,
                date: today,
                resting_hr: Number.isFinite(restingHr) ? restingHr : null,
                avg_hr: null,
                hrv_avg: hrvAvg,
            };

            const riskResponse = await fetch(`${backendUrl}/risk/notebook`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(notebookPayload)
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
            refreshSyncStatus();
        } catch (error) {
            console.error('Error:', error);
            setStatus(`error: ${error.message}`);
            showError(`Error: ${error.message}. Make sure FastAPI is running on ${backendUrl}.`);
            refreshSyncStatus();
        } finally {
            analyzeBtn.disabled = false;
        }

        return false;
    };

function showError(message) {
    const resultSection = document.getElementById('resultSection');
    const resultBox = document.getElementById('resultBox');
    const recommendationsBox = document.getElementById('recommendations');

    if (!resultSection || !resultBox || !recommendationsBox) {
        return;
    }

    resultSection.style.display = 'block';
    resultBox.className = 'result-box high';
    resultBox.innerHTML = '❌ <br> Burnout Risk: <strong>UNAVAILABLE</strong>';
    recommendationsBox.innerHTML = `<div class="error">${message}</div>`;
}

function displayResults(riskResult, summaryResult) {
    const resultSection = document.getElementById('resultSection');
    const resultBox = document.getElementById('resultBox');
    const recommendationsBox = document.getElementById('recommendations');

    if (!resultSection || !resultBox || !recommendationsBox) {
        return;
    }
    
    resultSection.style.display = 'block';
    
    // Determine risk level
    const riskScore = riskResult.risk_score || 0;
    let riskLevel, riskClass, icon;
    
    if (riskScore < 40) {
        riskLevel = 'LOW';
        riskClass = 'low';
        icon = '✅';
    } else if (riskScore < 70) {
        riskLevel = 'MODERATE';
        riskClass = 'moderate';
        icon = '⚠️';
    } else {
        riskLevel = 'HIGH';
        riskClass = 'high';
        icon = '🚨';
    }
    
    const confidenceSuffix = Number.isFinite(riskResult?.confidence)
        ? `<br><small>Model confidence: ${Number(riskResult.confidence).toFixed(2)}%</small>`
        : '';
    const assessedDate = riskResult?.date || summaryResult?.date || null;
    const assessedDateSuffix = assessedDate
        ? `<br><small>Data date assessed: ${assessedDate}</small>`
        : '';

    resultBox.className = `result-box ${riskClass}`;
    resultBox.innerHTML = `${icon} <br> Burnout Risk: <strong>${riskLevel}</strong> (${Number(riskScore).toFixed(1)}%)${confidenceSuffix}${assessedDateSuffix}`;
    
    // Generate recommendations
    let recommendations = getRecommendations(riskResult, summaryResult, riskLevel);
    recommendationsBox.innerHTML = recommendations;
}

function getRecommendations(riskResult, summaryResult, riskLevel) {
    let html = '<h3>💡 Recommendations:</h3><ul>';

    const sleepMinutes = summaryResult?.sleep_minutes || 0;
    const steps = summaryResult?.steps || 0;
    const restingHr = summaryResult?.resting_hr || 0;

    if (sleepMinutes > 0 && sleepMinutes < 420) {
        html += '<li>📅 Aim for 7-9 hours of quality sleep each night</li>';
    }

    if (restingHr > 75) {
        html += '<li>❤️ Resting HR is elevated. Prioritize recovery and reduce high-intensity load for a day or two</li>';
    }

    if (steps < 8000) {
        html += '<li>🚶 Increase daily activity to at least 8,000 steps</li>';
    }

    if (Array.isArray(riskResult?.explanation) && riskResult.explanation.length) {
        html += `<li>🧠 Model factors: ${riskResult.explanation.join('; ')}</li>`;
    }

    if (riskLevel === 'HIGH') {
        html += '<li>🏥 Consider speaking with a mental health professional</li>';
    }
    
    if (riskLevel === 'LOW') {
        html += '<li>✨ Great job maintaining your well-being! Keep up the healthy habits</li>';
    }
    
    html += '</ul>';
    return html;
}

