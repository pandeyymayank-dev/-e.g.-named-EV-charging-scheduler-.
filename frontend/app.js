/**
 * EV Charging Dispatch Control Room - Application Logic
 * Pure Vanilla JavaScript with Chart.js Integration
 */

let loadChart = null;
let currentRequests = [];
let currentStation = { id: 1, name: 'Default Station', capacity_kw: 20.0 };

// --- Error Handling ---
function showError(message) {
  const banner = document.getElementById('errorBanner');
  const msgEl = document.getElementById('errorMessage');
  msgEl.textContent = message;
  banner.classList.add('visible');
  console.error('[Control Room Error]:', message);
}

function dismissError() {
  const banner = document.getElementById('errorBanner');
  banner.classList.remove('visible');
}

// --- API Helpers ---
async function apiFetch(endpoint, options = {}) {
  try {
    const res = await fetch(endpoint, {
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {})
      },
      ...options
    });
    
    if (!res.ok) {
      let detail = `HTTP Error ${res.status} ${res.statusText}`;
      try {
        const errorData = await res.json();
        if (errorData.detail) {
          detail = typeof errorData.detail === 'string' ? errorData.detail : JSON.stringify(errorData.detail);
        }
      } catch (_) {}
      throw new Error(detail);
    }
    
    return await res.json();
  } catch (err) {
    showError(err.message || 'Network request failed. Is the backend server running?');
    throw err;
  }
}

// --- Station Management ---
async function loadStation() {
  try {
    const data = await apiFetch('/api/station');
    currentStation = data;
    const capacityInput = document.getElementById('stationCapacityInput');
    if (capacityInput) {
      capacityInput.value = data.capacity_kw;
    }
    return data;
  } catch (err) {
    // Error banner already shown
  }
}

async function saveStationCapacity() {
  const capacityInput = document.getElementById('stationCapacityInput');
  const newCap = parseFloat(capacityInput.value);
  
  if (isNaN(newCap) || newCap < 0) {
    showError('Capacity must be a non-negative number in kW.');
    return;
  }

  try {
    const updated = await apiFetch('/api/station', {
      method: 'PUT',
      body: JSON.stringify({
        name: currentStation.name || 'Default Station',
        capacity_kw: newCap
      })
    });
    currentStation = updated;
    dismissError();
    // Re-run scheduler with new capacity
    await triggerRunScheduler();
  } catch (err) {
    // Handled by apiFetch
  }
}

// --- Requests Queue Management ---
async function loadRequests() {
  try {
    const requests = await apiFetch('/api/requests');
    currentRequests = requests;
    renderQueueTable(requests);
    return requests;
  } catch (err) {
    // Handled by apiFetch
    return [];
  }
}

function applyPreset(modelName, powerKw, hoursNeeded) {
  document.getElementById('evLabel').value = modelName;
  document.getElementById('evPower').value = powerKw.toFixed(1);
  document.getElementById('evHours').value = hoursNeeded.toFixed(1);
  document.getElementById('evArrival').value = '18.0';
  document.getElementById('evDeadline').value = '7.0';
}

function renderQueueTable(requests) {
  const tbody = document.getElementById('queueTableBody');
  const countBadge = document.getElementById('queueCountBadge');
  countBadge.textContent = `${requests.length} EVs`;

  if (!requests || requests.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 20px;">
          Queue empty. Add an EV or click Reset.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = requests.map(r => `
    <tr>
      <td style="font-family: var(--font-mono); color: var(--text-muted);">#${r.id}</td>
      <td><strong>${escapeHtml(r.label)}</strong></td>
      <td style="font-family: var(--font-mono);">${formatHour(r.arrival)} → ${formatHour(r.deadline)}</td>
      <td style="font-family: var(--font-mono);">${r.hours_needed.toFixed(1)}h</td>
      <td style="font-family: var(--font-mono); color: var(--accent-cyan);">${r.power_kw.toFixed(1)} kW</td>
      <td>
        <button class="btn btn-danger" onclick="deleteEvRequest(${r.id})" title="Remove vehicle from queue">
          Delete
        </button>
      </td>
    </tr>
  `).join('');
}

async function handleAddEv(event) {
  event.preventDefault();
  dismissError();

  const label = document.getElementById('evLabel').value.trim();
  const arrival = parseFloat(document.getElementById('evArrival').value);
  const deadline = parseFloat(document.getElementById('evDeadline').value);
  const hours_needed = parseFloat(document.getElementById('evHours').value);
  const power_kw = parseFloat(document.getElementById('evPower').value);

  if (!label) {
    showError('Vehicle label is required.');
    return;
  }
  if (isNaN(arrival) || isNaN(deadline) || isNaN(hours_needed) || isNaN(power_kw)) {
    showError('All numerical fields must be valid numbers.');
    return;
  }
  if (hours_needed <= 0 || power_kw <= 0) {
    showError('Hours needed and power demand must be greater than zero.');
    return;
  }

  try {
    await apiFetch('/api/requests', {
      method: 'POST',
      body: JSON.stringify({
        label,
        arrival,
        deadline,
        hours_needed,
        power_kw
      })
    });

    document.getElementById('addEvForm').reset();
    document.getElementById('evPower').value = '10.0';
    await loadRequests();
    await triggerRunScheduler();
  } catch (err) {
    // Handled by apiFetch
  }
}

async function deleteEvRequest(id) {
  try {
    await apiFetch(`/api/requests/${id}`, { method: 'DELETE' });
    await loadRequests();
    await triggerRunScheduler();
  } catch (err) {
    // Handled by apiFetch
  }
}

async function triggerResetBenchmark() {
  dismissError();
  try {
    const result = await apiFetch('/api/reset', { method: 'POST' });
    currentStation = result.station;
    document.getElementById('stationCapacityInput').value = result.station.capacity_kw;
    await loadRequests();
    await triggerRunScheduler();
  } catch (err) {
    // Handled by apiFetch
  }
}

async function triggerSimulateEvs(n = 20) {
  dismissError();
  const simBtn = document.getElementById('simulateBtn');
  if (simBtn) {
    simBtn.disabled = true;
    simBtn.style.opacity = '0.7';
  }

  try {
    const result = await apiFetch(`/api/simulate?n=${n}`, { method: 'POST' });
    // Update queue table from returned or refreshed requests
    await loadRequests();
    // Render the simulated scheduler result immediately
    renderDashboard(result);
  } catch (err) {
    // Handled by apiFetch
  } finally {
    if (simBtn) {
      simBtn.disabled = false;
      simBtn.style.opacity = '1';
    }
  }
}

// --- Scheduler Run & Dashboard Visualizations ---
async function triggerRunScheduler() {
  dismissError();
  const runBtn = document.getElementById('runScheduleBtn');
  runBtn.disabled = true;
  runBtn.style.opacity = '0.7';

  try {
    const data = await apiFetch('/api/schedule/run', { method: 'POST' });
    renderDashboard(data);
  } catch (err) {
    // Handled by apiFetch
  } finally {
    runBtn.disabled = false;
    runBtn.style.opacity = '1';
  }
}

function renderDashboard(data) {
  const metrics = data.metrics || {};
  const capacityKw = data.capacity_kw || 20.0;
  const unctrlPeak = metrics.uncontrolled_peak_kw || 0.0;
  const schedPeak = metrics.scheduled_peak_kw || 0.0;

  // 1. Stat Card 1: Peak Load Reduction %
  const peakReductionEl = document.getElementById('statPeakReduction');
  const peakDetailsEl = document.getElementById('statPeakDetails');
  if (unctrlPeak > 0) {
    const reductionPct = Math.max(0, ((unctrlPeak - schedPeak) / unctrlPeak) * 100);
    peakReductionEl.textContent = `${reductionPct.toFixed(1)}%`;
    peakDetailsEl.textContent = `${unctrlPeak.toFixed(1)} kW Uncontrolled → ${schedPeak.toFixed(1)} kW Scheduled`;
  } else {
    peakReductionEl.textContent = '0.0%';
    peakDetailsEl.textContent = 'No load detected';
  }

  // 2. Stat Card 2: Deadlines Met
  const deadlinesMetEl = document.getElementById('statDeadlinesMet');
  const deadlinesDetailsEl = document.getElementById('statDeadlinesDetails');
  const deadlineFlags = data.deadline_met || {};
  const totalEvs = Object.keys(deadlineFlags).length;
  const metCount = Object.values(deadlineFlags).filter(v => v === true).length;

  if (totalEvs > 0) {
    const rate = ((metCount / totalEvs) * 100).toFixed(0);
    deadlinesMetEl.textContent = `${metCount} / ${totalEvs}`;
    deadlinesDetailsEl.textContent = `${rate}% On-Time Fulfillment (${totalEvs - metCount} missed)`;
    if (metCount === totalEvs) {
      deadlinesMetEl.style.color = 'var(--accent-emerald)';
    } else {
      deadlinesMetEl.style.color = 'var(--accent-amber)';
    }
  } else {
    deadlinesMetEl.textContent = '0 / 0';
    deadlinesDetailsEl.textContent = 'No active vehicles';
  }

  // 3. Stat Card 3: Total Cost in Rupees
  const costEl = document.getElementById('statEstimatedCost');
  const costDetailsEl = document.getElementById('statCostDetails');
  const costs = data.costs || {};
  const schedCost = costs.scheduled_cost !== undefined ? costs.scheduled_cost : 0.0;
  const unctrlCost = costs.uncontrolled_cost !== undefined ? costs.uncontrolled_cost : 0.0;
  const savings = costs.savings !== undefined ? costs.savings : Math.max(0, unctrlCost - schedCost);
  const savingsPct = costs.savings_pct !== undefined ? costs.savings_pct : (unctrlCost > 0 ? (savings / unctrlCost * 100) : 0.0);

  costEl.textContent = `₹${schedCost.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (unctrlCost > 0) {
    costDetailsEl.innerHTML = `Uncontrolled: <strong>₹${unctrlCost.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong> | Saved: <strong style="color: var(--accent-emerald)">₹${savings.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong> (${savingsPct.toFixed(1)}%)`;
  } else {
    costDetailsEl.textContent = 'Uncontrolled: ₹0.00 | Savings: ₹0.00';
  }

  // 4. Update Grouped Bar Chart with Dashed Red Capacity Line
  updateLoadChart(data.scheduled_load, data.uncontrolled_load, capacityKw);

  // 5. Update Vehicle Charging Assignments Table
  renderAssignmentsTable(currentRequests, data.assigned_slots, data.deadline_met);

  // 6. Update Scheduler Terminal Log
  renderDecisionLog(data.log);
}

// --- Chart.js Integration ---
function updateLoadChart(scheduledLoadMap = {}, uncontrolledLoadMap = {}, capacityKw = 20.0) {
  const ctx = document.getElementById('loadChart').getContext('2d');

  // Extract and sort all slots
  const allSlots = Array.from(new Set([
    ...Object.keys(scheduledLoadMap),
    ...Object.keys(uncontrolledLoadMap)
  ])).sort((a, b) => parseFloat(a) - parseFloat(b));

  const labels = allSlots.map(s => formatSlotLabel(s));
  const uncontrolledData = allSlots.map(s => uncontrolledLoadMap[s] || 0.0);
  const scheduledData = allSlots.map(s => scheduledLoadMap[s] || 0.0);
  const capacityLineData = allSlots.map(() => capacityKw);

  if (loadChart) {
    loadChart.destroy();
  }

  loadChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Uncontrolled Load (kW)',
          data: uncontrolledData,
          backgroundColor: 'rgba(245, 158, 11, 0.75)',
          borderColor: '#f59e0b',
          borderWidth: 1,
          borderRadius: 4,
          order: 2
        },
        {
          label: 'Scheduled Load (kW)',
          data: scheduledData,
          backgroundColor: 'rgba(6, 182, 212, 0.85)',
          borderColor: '#06b6d4',
          borderWidth: 1,
          borderRadius: 4,
          order: 2
        },
        {
          type: 'line',
          label: `Station Capacity (${capacityKw} kW)`,
          data: capacityLineData,
          borderColor: '#ef4444',
          borderWidth: 2,
          borderDash: [6, 6],
          pointRadius: 0,
          pointHoverRadius: 0,
          fill: false,
          order: 1
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false
      },
      plugins: {
        legend: {
          position: 'top',
          labels: {
            color: '#94a3b8',
            font: { family: 'JetBrains Mono', size: 11 },
            usePointStyle: true,
            boxWidth: 8
          }
        },
        tooltip: {
          backgroundColor: '#0d1322',
          titleColor: '#f8fafc',
          bodyColor: '#cbd5e1',
          borderColor: '#334155',
          borderWidth: 1,
          titleFont: { family: 'JetBrains Mono', size: 12 },
          bodyFont: { family: 'JetBrains Mono', size: 11 },
          padding: 10,
          callbacks: {
            title: function(items) {
              if (!items || !items.length) return '';
              const idx = items[0].dataIndex;
              return `Slot ${labels[idx]}`;
            },
            label: function(context) {
              return ` ${context.dataset.label}: ${context.parsed.y.toFixed(1)} kW`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: {
            color: 'rgba(255, 255, 255, 0.05)'
          },
          ticks: {
            color: '#94a3b8',
            font: { family: 'JetBrains Mono', size: 10 }
          }
        },
        y: {
          beginAtZero: true,
          suggestedMax: Math.max(capacityKw * 1.25, 25),
          grid: {
            color: 'rgba(255, 255, 255, 0.07)'
          },
          ticks: {
            color: '#94a3b8',
            font: { family: 'JetBrains Mono', size: 10 },
            callback: function(value) { return value + ' kW'; }
          }
        }
      }
    }
  });
}

// --- Render Table & Log ---
function renderAssignmentsTable(requests = [], assignedSlotsMap = {}, deadlineMetMap = {}) {
  const tbody = document.getElementById('scheduleTableBody');

  if (!requests || requests.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 20px;">
          No active vehicles to schedule.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = requests.map(r => {
    const slots = assignedSlotsMap[r.id] || [];
    const isMet = deadlineMetMap[r.id];
    const energyKwh = (r.hours_needed * r.power_kw).toFixed(1);

    const slotBadges = slots.length > 0
      ? slots.map(s => `<span class="badge badge-slot">${formatSlotLabel(s)}</span>`).join('')
      : '<em style="color: var(--text-muted); font-size: 0.75rem;">None assigned</em>';

    const statusBadge = isMet
      ? '<span class="badge badge-emerald">✓ On-Time</span>'
      : '<span class="badge badge-red">✗ Missed</span>';

    return `
      <tr>
        <td style="font-family: var(--font-mono); color: var(--text-muted);">#${r.id}</td>
        <td><strong>${escapeHtml(r.label)}</strong></td>
        <td style="font-family: var(--font-mono);">${formatHour(r.arrival)} → ${formatHour(r.deadline)}</td>
        <td style="font-family: var(--font-mono);">${energyKwh} kWh <span style="color: var(--text-muted);">(${r.hours_needed}h @ ${r.power_kw}kW)</span></td>
        <td>${slotBadges}</td>
        <td>${statusBadge}</td>
      </tr>
    `;
  }).join('');
}

function renderDecisionLog(logEntries = []) {
  const terminal = document.getElementById('terminalLog');

  if (!logEntries || logEntries.length === 0) {
    terminal.innerHTML = `
      <div class="log-line">
        <span class="log-tag-info">[INFO]</span>
        <span class="log-text">No active decisions recorded.</span>
      </div>
    `;
    return;
  }

  terminal.innerHTML = logEntries.map(entry => {
    const isCharge = entry.includes('CHARGE');
    const isDefer = entry.includes('DEFER');
    
    let tagHtml = '<span class="log-tag-info">[LOG]</span>';
    if (isCharge) {
      tagHtml = '<span class="log-tag-charge">[CHARGE]</span>';
    } else if (isDefer) {
      tagHtml = '<span class="log-tag-defer">[DEFER]</span>';
    }

    return `
      <div class="log-line">
        ${tagHtml}
        <span class="log-text">${escapeHtml(entry)}</span>
      </div>
    `;
  }).join('');
  
  // Scroll to bottom
  terminal.scrollTop = terminal.scrollHeight;
}

// --- Utilities ---
function formatHour(h) {
  const hourInt = Math.floor(h);
  const mins = Math.round((h - hourInt) * 60);
  const normalizedHour = hourInt % 24;
  const dayOffset = Math.floor(hourInt / 24);
  const timeStr = `${String(normalizedHour).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
  return dayOffset > 0 ? `${timeStr} (+${dayOffset}d)` : timeStr;
}

function formatSlotLabel(slot) {
  const s = parseFloat(slot);
  return formatHour(s);
}

function escapeHtml(str) {
  if (typeof str !== 'string') return str;
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// --- App Initialization ---
window.addEventListener('DOMContentLoaded', async () => {
  // Allow saving capacity on Enter key
  const capInput = document.getElementById('stationCapacityInput');
  if (capInput) {
    capInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        saveStationCapacity();
      }
    });
  }

  try {
    await loadStation();
    await loadRequests();
    await triggerRunScheduler();
  } catch (err) {
    console.error('Initialization error:', err);
  }
});
