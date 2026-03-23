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
    const manualAvgHrInput = document.getElementById('manual_avg_hr');
    const manualStepsInput = document.getElementById('manual_steps');
    const manualSleepHoursInput = document.getElementById('manual_sleep_hours');
    const manualAvgStressInput = document.getElementById('manual_avg_stress');
    const manualBodyBatteryInput = document.getElementById('manual_body_battery');
    const manualSleepScoreInput = document.getElementById('manual_sleep_score');

    let syncStatusTimer = null;
    let lastResolvedWatchMetrics = {
        restingHr: null,
        hrvAvg: null,
        dataDate: null,
        avgStress: null,
        bodyBatteryMax: null,
        sleepScore: null,
        steps: null,
        sleepMinutes: null,
        avgHr: null,
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
        let avgStress = null;
        let bodyBatteryMax = null;
        let sleepScore = null;
        let steps = null;
        let sleepMinutes = null;
        let avgHr = null;

        try {
            const summaryResponse = await fetch(`${backendUrl}/summary/latest?user_id=${encodeURIComponent(userId)}&preferred_source=garmin_export`);
            if (summaryResponse.ok) {
                const summary = await summaryResponse.json();
                if (Number.isFinite(summary?.resting_hr)) {
                    restingHr = Number(summary.resting_hr);
                }
                if (typeof summary?.date === 'string' && summary.date) {
                    summaryDate = summary.date;
                }
                if (Number.isFinite(summary?.avg_stress)) {
                    avgStress = Number(summary.avg_stress);
                }
                if (Number.isFinite(summary?.body_battery_max)) {
                    bodyBatteryMax = Number(summary.body_battery_max);
                }
                if (Number.isFinite(summary?.sleep_score)) {
                    sleepScore = Number(summary.sleep_score);
                }
                if (Number.isFinite(summary?.steps)) {
                    steps = Number(summary.steps);
                }
                if (Number.isFinite(summary?.sleep_minutes)) {
                    sleepMinutes = Number(summary.sleep_minutes);
                }
                if (Number.isFinite(summary?.avg_hr)) {
                    avgHr = Number(summary.avg_hr);
                }
                if (Number.isFinite(summary?.hrv_avg) && summary.hrv_avg > 0) {
                    hrvAvg = Number(summary.hrv_avg);
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
            avgStress: Number.isFinite(avgStress) ? avgStress : null,
            bodyBatteryMax: Number.isFinite(bodyBatteryMax) ? bodyBatteryMax : null,
            sleepScore: Number.isFinite(sleepScore) ? sleepScore : null,
            steps: Number.isFinite(steps) ? steps : null,
            sleepMinutes: Number.isFinite(sleepMinutes) ? sleepMinutes : null,
            avgHr: Number.isFinite(avgHr) ? avgHr : null,
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

        if (manualAvgHrInput && Number.isFinite(watchMetrics.avgHr)) {
            manualAvgHrInput.value = String(watchMetrics.avgHr);
        }
        if (manualStepsInput && Number.isFinite(watchMetrics.steps)) {
            manualStepsInput.value = String(watchMetrics.steps);
        }
        if (manualSleepHoursInput && Number.isFinite(watchMetrics.sleepMinutes)) {
            manualSleepHoursInput.value = (watchMetrics.sleepMinutes / 60).toFixed(2);
        }
        if (manualAvgStressInput && Number.isFinite(watchMetrics.avgStress)) {
            manualAvgStressInput.value = String(watchMetrics.avgStress);
        }
        if (manualBodyBatteryInput && Number.isFinite(watchMetrics.bodyBatteryMax)) {
            manualBodyBatteryInput.value = String(watchMetrics.bodyBatteryMax);
        }
        if (manualSleepScoreInput && Number.isFinite(watchMetrics.sleepScore)) {
            manualSleepScoreInput.value = String(watchMetrics.sleepScore);
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

            // Only keep strong signals as "top drivers".
            if (text.includes('low hrv')) {
                addDriver('low HRV');
            } else if (text.includes('high resting hr') || text.includes('significantly higher than baseline')) {
                addDriver('high resting HR');
            } else if (text.includes('sleep is much lower') || text.includes('sleep drop')) {
                addDriver('sleep drop');
            } else if (text.includes('steps are far below')) {
                addDriver('activity drop');
            } else if (text.includes('watch stress') || text.includes('blended stress') || text.includes('— high') || text.includes('— elevated')) {
                addDriver('high watch stress');
            } else if (text.includes('body battery critically low') || text.includes('body battery is low')) {
                addDriver('low body battery');
            } else if (text.includes('high self-reported stress') || text.includes('elevated self-reported stress')) {
                addDriver('high perceived stress');
            } else if (text.includes('long workday') || text.includes('extended workday')) {
                addDriver('long workday');
            } else if (text.includes('poor self-reported mood')) {
                addDriver('low mood');
            }
        });

        const sleepMinutes = summaryResult?.sleep_minutes;
        if (Number.isFinite(sleepMinutes) && sleepMinutes > 0 && sleepMinutes < 360) {
            addDriver('sleep drop');
        }

        const restingHr = summaryResult?.resting_hr;
        if (Number.isFinite(restingHr) && restingHr >= 80) {
            addDriver('high resting HR');
        }

        return drivers.slice(0, 3);
    }

    function getRecommendations(riskResult, summaryResult, riskLevel, selfReport) {
        let html = '<h3>Recommendations:</h3><ul>';

        const sleepMinutes = summaryResult?.sleep_minutes || 0;
        const steps = summaryResult?.steps || 0;
        const restingHr = summaryResult?.resting_hr || 0;
        const percStress = selfReport?.perceivedStress;
        const wkHrs = selfReport?.workHours;
        const mScore = selfReport?.moodScore;
        const wStress = selfReport?.watchAvgStress;
        const wBattery = selfReport?.watchBodyBattery;

        if (sleepMinutes > 0 && sleepMinutes < 420) {
            html += '<li>Aim for 7-9 hours of quality sleep each night</li>';
        }

        if (restingHr > 75) {
            html += '<li>Resting HR is elevated. Prioritize recovery and reduce high-intensity load for a day or two</li>';
        }

        if (steps < 8000) {
            html += '<li>Increase daily activity to at least 8,000 steps</li>';
        }

        if (Number.isFinite(wStress) && wStress >= 75) {
            html += '<li>Your Garmin stress score is very high. Schedule at least one 10-minute rest block today and avoid additional stressors.</li>';
        } else if (Number.isFinite(wStress) && wStress >= 60) {
            html += '<li>Your Garmin stress score is elevated. Short breathing exercises and a lighter afternoon schedule can help.</li>';
        } else if (Number.isFinite(wBattery) && wBattery <= 20) {
            html += '<li>Body battery is critically low — avoid intense workouts and prioritise sleep tonight.</li>';
        } else if (Number.isFinite(wBattery) && wBattery <= 40) {
            html += '<li>Body battery is low. Consider a longer sleep window and a shorter or easier training session.</li>';
        }

        if (Number.isFinite(percStress) && percStress >= 75) {
            html += '<li>Your stress level is very high. Try a 10-minute breathing or mindfulness exercise before your next task.</li>';
        } else if (Number.isFinite(percStress) && percStress >= 60) {
            html += '<li>Your stress is elevated. Take short breaks every 90 minutes and limit caffeine after 2 pm.</li>';
        }

        if (Number.isFinite(wkHrs) && wkHrs > 10) {
            html += '<li>You worked more than 10 hours today. Set a firm stopping time tomorrow to protect recovery.</li>';
        } else if (Number.isFinite(wkHrs) && wkHrs > 8) {
            html += '<li>Long workday detected. Try to end on time tomorrow and build in a wind-down routine.</li>';
        }

        if (Number.isFinite(mScore) && mScore <= 2) {
            html += '<li>Your mood is low — a short walk, social connection, or enjoyable activity can help recharge.</li>';
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

    function displayResults(riskResult, summaryResult, selfReport) {
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
        const topDriversSuffix = topDrivers.length
            ? `<br><small>Top drivers: ${topDrivers.join('; ')}</small>`
            : '';

        // Watch biometrics line — shown when Garmin stress / body battery were available
        const wStress = selfReport?.watchAvgStress;
        const wBattery = selfReport?.watchBodyBattery;
        const wSleep = selfReport?.watchSleepScore;
        const watchBioItems = [];
        if (Number.isFinite(wStress)) watchBioItems.push(`Stress&nbsp;${wStress}/100`);
        if (Number.isFinite(wBattery)) watchBioItems.push(`Body&nbsp;Battery&nbsp;${wBattery}/100`);
        if (Number.isFinite(wSleep)) watchBioItems.push(`Sleep&nbsp;Score&nbsp;${wSleep}`);
        const watchBioSuffix = watchBioItems.length
            ? `<br><small class="watch-bio-line">Watch: ${watchBioItems.join(' &middot; ')}</small>`
            : '';

        resultBox.className = `result-box ${riskClass}`;
        resultBox.innerHTML = `${icon} <br> Burnout Risk: <strong>${riskLevel}</strong> (${Number(riskScore).toFixed(1)}%)${confidenceSuffix}${assessedDateSuffix}${watchBioSuffix}${topDriversSuffix}`;
        recommendationsBox.innerHTML = getRecommendations(riskResult, summaryResult, riskLevel, selfReport);
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
        const manualAvgHr = parseFloat(document.getElementById('manual_avg_hr')?.value);
        const manualSteps = parseInt(document.getElementById('manual_steps')?.value, 10);
        const manualSleepHours = parseFloat(document.getElementById('manual_sleep_hours')?.value);
        const manualAvgStress = parseInt(document.getElementById('manual_avg_stress')?.value, 10);
        const manualBodyBattery = parseInt(document.getElementById('manual_body_battery')?.value, 10);
        const manualSleepScore = parseInt(document.getElementById('manual_sleep_score')?.value, 10);
        const perceivedStress = parseInt(document.getElementById('perceived_stress')?.value, 10);
        const workHours = parseFloat(document.getElementById('work_hours')?.value);
        const moodRadio = document.querySelector('input[name="mood_score"]:checked');
        const moodScore = moodRadio ? parseInt(moodRadio.value, 10) : null;

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
        let watchAvgStress = null;
        let watchBodyBattery = null;
        let watchSleepScore = null;

        if (metricSource === 'watch') {
            setStatus('reading watch metrics');
            const watchMetrics = await resolveWatchMetrics(backendUrl, userId);
            restingHr = watchMetrics.restingHr ?? restingHr;
            hrvAvg = watchMetrics.hrvAvg ?? hrvAvg;
            watchDataDate = watchMetrics.dataDate || null;
            watchAvgStress = watchMetrics.avgStress ?? null;
            watchBodyBattery = watchMetrics.bodyBatteryMax ?? null;
            watchSleepScore = watchMetrics.sleepScore ?? null;

            // If watch provides stress, auto-hide the manual stress slider
            const stressRow = document.getElementById('perceived_stress')?.closest('.form-group');
            if (Number.isFinite(watchAvgStress)) {
                if (stressRow) {
                    stressRow.classList.add('watch-data-available');
                    const note = stressRow.querySelector('.watch-override-note');
                    if (note) note.style.display = 'block';
                }
            }

            if (restingHrInput && Number.isFinite(restingHr)) {
                restingHrInput.value = String(restingHr);
            }

            if (hrvAvgInput && Number.isFinite(hrvAvg)) {
                hrvAvgInput.value = String(hrvAvg);
            }
        }

        // In manual mode, HRV is required for the notebook model
        if (metricSource === 'manual' && (!Number.isFinite(hrvAvg) || hrvAvg <= 0)) {
            setStatus('missing hrv_avg');
            showError('Please enter a valid HRV Average (RMSSD).');
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
                    steps: Number.isFinite(manualSteps) ? manualSteps : null,
                    sleep_minutes: Number.isFinite(manualSleepHours) ? Math.round(manualSleepHours * 60) : null,
                    resting_hr: Number.isFinite(restingHr) ? restingHr : null,
                    avg_hr: Number.isFinite(manualAvgHr) ? manualAvgHr : null,
                    hr_samples_count: null,
                    avg_stress: Number.isFinite(manualAvgStress) ? manualAvgStress : null,
                    body_battery_max: Number.isFinite(manualBodyBattery) ? manualBodyBattery : null,
                    sleep_score: Number.isFinite(manualSleepScore) ? manualSleepScore : null,
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

            setStatus('requesting risk score');
            // In manual mode, manually-entered stress/battery take priority over watch values
            const effectiveAvgStress = metricSource === 'manual' && Number.isFinite(manualAvgStress)
                ? manualAvgStress
                : (Number.isFinite(watchAvgStress) ? watchAvgStress : null);
            const effectiveBodyBattery = metricSource === 'manual' && Number.isFinite(manualBodyBattery)
                ? manualBodyBattery
                : (Number.isFinite(watchBodyBattery) ? watchBodyBattery : null);
            const effectiveSleepScore = metricSource === 'manual' && Number.isFinite(manualSleepScore)
                ? manualSleepScore
                : watchSleepScore;

            let riskResult;

            // Watch mode without HRV: /risk/latest already blends notebook model when HRV is in DB
            if (metricSource === 'watch' && (!Number.isFinite(hrvAvg) || hrvAvg <= 0)) {
                setStatus('no HRV — using watch baseline risk');
                const fallbackResponse = await fetch(`${backendUrl}/risk/latest?user_id=${encodeURIComponent(userId)}`);
                if (!fallbackResponse.ok) {
                    throw new Error(`Risk request failed (${fallbackResponse.status})`);
                }
                riskResult = await fallbackResponse.json();
                if (!Array.isArray(riskResult.explanation)) {
                    riskResult.explanation = [];
                }
            } else {
                const notebookPayload = {
                    user_id: userId,
                    date: analysisDate,
                    resting_hr: Number.isFinite(restingHr) ? restingHr : null,
                    avg_hr: metricSource === 'manual' && Number.isFinite(manualAvgHr) ? manualAvgHr : null,
                    hrv_avg: hrvAvg,
                    avg_stress: Number.isFinite(effectiveAvgStress) ? effectiveAvgStress : null,
                    body_battery_max: Number.isFinite(effectiveBodyBattery) ? effectiveBodyBattery : null,
                    perceived_stress: Number.isFinite(perceivedStress) && perceivedStress >= 0 ? perceivedStress : null,
                    work_hours: Number.isFinite(workHours) && workHours >= 0 ? workHours : null,
                    mood_score: moodScore,
                };

                const riskResponse = await fetch(`${backendUrl}/risk/notebook`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(notebookPayload),
                });

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
            }

            setStatus('requesting summary');
            const summaryResponse = await fetch(`${backendUrl}/summary/latest?user_id=${encodeURIComponent(userId)}`);
            let summaryResult = null;
            if (summaryResponse.ok) {
                summaryResult = await summaryResponse.json();
            }

            displayResults(riskResult, summaryResult, { perceivedStress, workHours, moodScore, watchAvgStress: effectiveAvgStress, watchBodyBattery: effectiveBodyBattery, watchSleepScore: effectiveSleepScore });
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

    const stressSlider = document.getElementById('perceived_stress');
    const stressValDisplay = document.getElementById('perceived_stress_val');
    if (stressSlider && stressValDisplay) {
        stressValDisplay.textContent = stressSlider.value; // set initial display
        stressSlider.addEventListener('input', () => {
            stressValDisplay.textContent = stressSlider.value;
        });
    }

    document.querySelectorAll('input[name="mood_score"]').forEach((radio) => {
        radio.addEventListener('change', () => {
            document.querySelectorAll('.mood-option').forEach((opt) => opt.classList.remove('checked'));
            if (radio.checked) {
                radio.closest('.mood-option')?.classList.add('checked');
            }
        });
    });

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
