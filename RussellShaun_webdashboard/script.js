fetch('burnout_data.json')
    .then(res => res.json())
    .then(data => {
        let latest = data[data.length - 1];
        document.getElementById("hr").textContent = latest.hr;
        document.getElementById("stress").textContent = latest.stress;
    });
