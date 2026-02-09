// ==================== TAB SWITCHING ====================
const tabBtns = document.querySelectorAll('.tab-btn');
const tabContents = document.querySelectorAll('.tab-content');

tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const tabName = btn.getAttribute('data-tab');
        
        // Remove active class from all tabs and buttons
        tabContents.forEach(content => content.classList.remove('active'));
        tabBtns.forEach(b => b.classList.remove('active'));
        
        // Add active class to selected tab and button
        document.getElementById(tabName).classList.add('active');
        btn.classList.add('active');
    });
});

// ==================== BURNOUT DETECTION FORM ====================
// Update stress value display
document.getElementById('stress_level').addEventListener('input', (e) => {
    document.getElementById('stressValue').textContent = e.target.value;
});

// Handle form submission
document.getElementById('burnoutForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const sleep = parseFloat(document.getElementById('sleep').value);
    const hrv = parseFloat(document.getElementById('hrv').value);
    const steps = parseFloat(document.getElementById('steps').value);
    const work_hours = parseFloat(document.getElementById('work_hours').value);
    const stress_level = parseInt(document.getElementById('stress_level').value);
    
    try {
        const response = await fetch('http://127.0.0.1:5000/predict', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sleep, hrv, steps, work_hours, stress_level })
        });
        
        if (!response.ok) {
            throw new Error('Failed to get prediction');
        }
        
        const result = await response.json();
        displayResults(result);
    } catch (error) {
        console.error('Error:', error);
        const resultSection = document.getElementById('resultSection');
        resultSection.style.display = 'block';
        resultSection.innerHTML = `<div class="error">Error: ${error.message}. Make sure the Python server is running.</div>`;
    }
});

function displayResults(result) {
    const resultSection = document.getElementById('resultSection');
    const resultBox = document.getElementById('resultBox');
    const recommendationsBox = document.getElementById('recommendations');
    
    resultSection.style.display = 'block';
    
    // Determine risk level
    const riskScore = result.burnout_risk || result.risk || 0;
    let riskLevel, riskClass, icon;
    
    if (riskScore < 30) {
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
    resultBox.innerHTML = `${icon} <br> Burnout Risk: <strong>${riskLevel}</strong> (${riskScore.toFixed(1)}%)`;
    
    // Generate recommendations
    let recommendations = getRecommendations(result, riskLevel);
    recommendationsBox.innerHTML = recommendations;
}

function getRecommendations(result, riskLevel) {
    let html = '<h3>💡 Recommendations:</h3><ul>';
    
    const sleep = result.sleep || 0;
    const hrv = result.hrv || 0;
    const steps = result.steps || 0;
    const work_hours = result.work_hours || 0;
    const stress_level = result.stress_level || 0;
    
    if (sleep < 7) {
        html += '<li>📅 Aim for 7-9 hours of quality sleep each night</li>';
    }
    
    if (hrv < 40) {
        html += '<li>❤️ Improve recovery: Try meditation, yoga, or deep breathing exercises</li>';
    }
    
    if (steps < 8000) {
        html += '<li>🚶 Increase daily activity to at least 8,000 steps</li>';
    }
    
    if (work_hours > 8.5) {
        html += '<li>⏰ Reduce work hours and ensure adequate breaks during work</li>';
    }
    
    if (stress_level > 7) {
        html += '<li>🧘 Practice stress management: Try meditation, mindfulness, or therapy</li>';
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

