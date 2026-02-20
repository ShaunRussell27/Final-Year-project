// ==================== TAB SWITCHING ====================
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

// ==================== BURNOUT DETECTION FORM ====================
const burnoutForm = document.getElementById('burnoutForm');
const analyzeBtn = document.getElementById('analyzeBtn');
const debugStatus = document.getElementById('debugStatus');

function setStatus(text) {
    if (debugStatus) {
        debugStatus.textContent = `Status: ${text}`;
    }
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

        const userId = document.getElementById('user_id').value.trim();
        const backendUrl = document.getElementById('backend_url').value.trim().replace(/\/$/, '');

        const sleepHours = parseFloat(document.getElementById('sleep').value);
        const steps = parseFloat(document.getElementById('steps').value);
        const restingHr = parseFloat(document.getElementById('resting_hr').value);
        const avgHr = parseFloat(document.getElementById('avg_hr').value);

        if (!userId) {
            setStatus('missing user_id');
            showError('Please enter a user_id.');
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
            steps: Number.isFinite(steps) ? Math.round(steps) : null,
            sleep_minutes: Number.isFinite(sleepHours) ? Math.round(sleepHours * 60) : null,
            resting_hr: Number.isFinite(restingHr) ? restingHr : null,
            avg_hr: Number.isFinite(avgHr) ? avgHr : null,
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

            setStatus('requesting risk');
            const riskResponse = await fetch(`${backendUrl}/risk/latest?user_id=${encodeURIComponent(userId)}`);
            if (!riskResponse.ok) {
                const body = await riskResponse.text();
                throw new Error(`Risk request failed (${riskResponse.status})${body ? `: ${body}` : ''}`);
            }

            const riskResult = await riskResponse.json();

            setStatus('requesting summary');
            const summaryResponse = await fetch(`${backendUrl}/summary/latest?user_id=${encodeURIComponent(userId)}`);
            let summaryResult = null;
            if (summaryResponse.ok) {
                summaryResult = await summaryResponse.json();
            }

            displayResults(riskResult, summaryResult);
            setStatus('done');
        } catch (error) {
            console.error('Error:', error);
            setStatus(`error: ${error.message}`);
            showError(`Error: ${error.message}. Make sure FastAPI is running on ${backendUrl}.`);
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
    
    resultBox.className = `result-box ${riskClass}`;
    resultBox.innerHTML = `${icon} <br> Burnout Risk: <strong>${riskLevel}</strong> (${Number(riskScore).toFixed(1)}%)`;
    
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

