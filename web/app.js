const badge = document.querySelector("#system-badge");
const interlock = document.querySelector("#interlock");
const serviceGrid = document.querySelector("#service-grid");
let registrationState = null;
let operationalStarted = false;
let operationalIntervals = [];
let serviceInventory = [];
let applicationInventory = [];
let latestGateway = null;
const TELEMETRY_METRICS = {
  cpu: {label: "CPU utilization", fixedMin: 0, fixedMax: 100, unit: "%"},
  memory: {label: "Memory used", fixedMin: 0, fixedMax: 100, unit: "%"},
  temperature: {label: "CPU temperature", unit: "°C"},
  aprsFrames: {label: "Decoded APRS frames", unit: ""},
  aircraft: {label: "Aircraft tracked", unit: ""},
  voiceCalls: {label: "Scanner voice calls", unit: ""},
  vhfLocks: {label: "VHF locks", unit: ""},
  uhfLocks: {label: "UHF locks", unit: ""},
};

let telemetryHistory = [];

function trialDataAllowed() {
  return Boolean(registrationState?.registered || registrationState?.data_updates_allowed);
}

function formatTrialClock(seconds) {
  const remaining = Math.max(0, Number(seconds) || 0);
  return `${Math.floor(remaining / 60)}:${String(Math.floor(remaining % 60)).padStart(2, "0")}`;
}

function registrationMessage(message, failed = false) {
  const output = document.querySelector("#registration-result");
  output.textContent = message;
  output.classList.toggle("is-error", failed);
}

function renderRegistration(registration) {
  registrationState = registration || {};
  const registered = Boolean(registrationState.registered);
  const expired = Boolean(registrationState.trial_expired);
  const active = Boolean(registrationState.trial_active);
  const state = document.querySelector("#registration-state");
  const trialButton = document.querySelector("#registration-trial-button");
  const trialBadge = document.querySelector("#registration-trial-badge");
  const form = document.querySelector("#registration-form");
  document.querySelector("#registration-serial").textContent = registrationState.serial_number || "Unavailable";
  state.textContent = registered ? "Registered" : expired ? "Trial ended" : active ? "Trial active" : "Unregistered";
  state.className = `n0-status ${registered ? "n0-status--operational" : expired ? "n0-status--fault" : "n0-status--advisory"}`;
  trialButton.hidden = registered;
  trialButton.disabled = !expired;
  trialButton.title = expired ? "Restart the five-minute trial" : "Trial restart becomes available after the timer expires";
  trialButton.classList.toggle("is-expired", expired);
  trialBadge.textContent = expired ? "ENDED" : active ? formatTrialClock(registrationState.trial_remaining_seconds) : "5:00";
  form.hidden = registered;
  document.querySelector("#registration-status-text").textContent = registered
    ? `Registered license ${registrationState.license_suffix || ""}. Continuous dashboard updates enabled.`
    : expired
      ? "The free five-minute trial has ended. APRS, Weather, and Winlink services are stopped. Restart the trial or activate a Gateway license."
      : `Free five-minute trial · ${formatTrialClock(registrationState.trial_remaining_seconds)} remaining.`;
}

function setTrialDataPaused(paused) {
  const selectors = [
    "#overview", ".summary-grid", "#aprs-activity", "#aprs-map-section", "#winlink-gateway",
    "#radio-services", "#weather-monitor", "#system-readiness", "#applications",
  ];
  selectors.forEach((selector) => document.querySelector(selector)?.classList.toggle("trial-data-paused", paused));
  document.querySelector("#trial-expired-notice").hidden = !paused;
  document.querySelector("#aprs-frames").hidden = true;
  document.querySelector("#winlink-sessions").hidden = true;
}

function stopOperationalUpdates() {
  operationalIntervals.forEach((interval) => window.clearInterval(interval));
  operationalIntervals = [];
  operationalStarted = false;
  setTrialDataPaused(true);
  badge.textContent = "Trial ended";
  badge.className = "n0-status n0-status--advisory";
}

async function postRegistration(path, payload = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error || "Registration request failed");
  return result.registration;
}

async function restartFreeTrial() {
  registrationMessage("Restarting the free five-minute trial…");
  try {
    renderRegistration(await postRegistration("/api/license/trial/reset"));
    setTrialDataPaused(false);
    registrationMessage("Free five-minute trial restarted manually.");
    if (!operationalStarted) await loadOperationalData();
  } catch (error) {
    registrationMessage(`Trial restart failed: ${error.message}`, true);
  }
}

async function activateRegistration(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = document.querySelector("#registration-activate");
  button.disabled = true;
  registrationMessage("Contacting the N0JCG licensing service…");
  try {
    renderRegistration(await postRegistration("/api/license/activate", {
      license_serial: form.elements.license_serial.value.trim(),
      email: form.elements.email.value.trim(),
    }));
    form.reset();
    setTrialDataPaused(false);
    registrationMessage("Gateway license activated. Continuous dashboard updates enabled.");
    if (!operationalStarted) await loadOperationalData();
  } catch (error) {
    registrationMessage(`Activation failed: ${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

function initRegistration() {
  document.querySelector("#registration-trial-button")?.addEventListener("click", restartFreeTrial);
  document.querySelector("#trial-notice-restart")?.addEventListener("click", restartFreeTrial);
  document.querySelector("#registration-form")?.addEventListener("submit", activateRegistration);
}

async function refreshRegistration() {
  const response = await fetch("/api/license/status", {cache: "no-store"});
  if (!response.ok) throw new Error("Registration status request failed");
  const payload = await response.json();
  const wasAllowed = trialDataAllowed();
  renderRegistration(payload.registration);
  const allowed = trialDataAllowed();
  if (!allowed) stopOperationalUpdates();
  else if (!wasAllowed || !operationalStarted) {
    setTrialDataPaused(false);
    await loadOperationalData();
  }
  return payload.registration;
}

function runtimeServiceState(service, gateway) {
  if (service.id === "aprs") {
    return gateway?.receive?.aprs?.active ? "operational" : "service fault";
  }
  if (service.id === "winlink") {
    return gateway?.winlink?.state === "operational" ? "operational" : "service fault";
  }
  const applicationId = service.id === "scanner" ? "scanner" : ["adsb", "uat", "noaa", "airband"].includes(service.id) ? "air_traffic" : null;
  if (applicationId) {
    const application = applicationInventory.find((item) => item.id === applicationId);
    if (application) return application.reachable ? "operational" : (application.enabled ? "service fault" : "disabled");
  }
  return service.state;
}

function serviceCard(service, gateway) {
  const card = document.createElement("article");
  card.className = "status-card service-card";
  const serviceState = runtimeServiceState(service, gateway);
  const stateClass = {
    operational: "state state--operational",
    "service fault": "state state--fault",
    "external-node": "state state--observed",
  }[serviceState] || "state state--planned";
  const stateLabel = serviceState.replaceAll("-", " ");
  card.innerHTML = `
    <div class="card-heading"><span>${service.name}</span><span class="phase">Phase ${service.phase}</span></div>
    <strong class="${stateClass}">${stateLabel}</strong>
    <small>${service.hardware} · ${service.rf_role}</small>`;
  return card;
}

function showServices(gateway) {
  if (gateway) latestGateway = gateway;
  serviceGrid.replaceChildren();
  serviceInventory.forEach((service) => serviceGrid.appendChild(serviceCard(service, latestGateway)));
}

function telemetryNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function renderTelemetryChart(metricName) {
  const chart = document.querySelector(`#chart-${metricName}`);
  const definition = TELEMETRY_METRICS[metricName];
  if (!chart || !definition) return;
  const points = telemetryHistory
    .map((point) => ({timestamp: point.timestamp, value: telemetryNumber(point[metricName])}))
    .filter((point) => point.value !== null);
  chart.replaceChildren();
  if (!points.length) {
    const empty = document.createElement("span");
    empty.className = "telemetry-empty";
    empty.textContent = "Collecting history";
    chart.appendChild(empty);
    return;
  }

  const width = 320;
  const height = 88;
  const padding = 5;
  const values = points.map((point) => point.value);
  let minimum = definition.fixedMin ?? Math.min(...values);
  let maximum = definition.fixedMax ?? Math.max(...values);
  if (maximum === minimum) {
    const margin = maximum === 0 ? 1 : Math.max(1, Math.abs(maximum) * 0.08);
    minimum -= margin;
    maximum += margin;
  }
  const coordinates = points.map((point, index) => {
    const x = padding + (points.length === 1 ? (width - padding * 2) / 2 : index / (points.length - 1) * (width - padding * 2));
    const y = height - padding - (point.value - minimum) / (maximum - minimum) * (height - padding * 2);
    return [x, y];
  });
  const namespace = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("aria-hidden", "true");
  const area = document.createElementNS(namespace, "path");
  const linePath = coordinates.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  area.setAttribute("d", `${linePath} L${coordinates.at(-1)[0].toFixed(1)},${height - padding} L${coordinates[0][0].toFixed(1)},${height - padding} Z`);
  area.setAttribute("class", "telemetry-area");
  const line = document.createElementNS(namespace, "path");
  line.setAttribute("d", linePath);
  line.setAttribute("class", "telemetry-line");
  svg.append(area, line);
  chart.appendChild(svg);
  const scale = document.createElement("div");
  scale.className = "telemetry-scale";
  scale.innerHTML = `<span>${minimum.toFixed(definition.unit ? 1 : 0)}${definition.unit}</span><span>${maximum.toFixed(definition.unit ? 1 : 0)}${definition.unit}</span>`;
  chart.appendChild(scale);
  const latest = points.at(-1);
  const first = points[0];
  chart.setAttribute("aria-label", `${definition.label}: ${latest.value}${definition.unit}; ${points.length} samples from ${new Date(first.timestamp).toLocaleTimeString()} to ${new Date(latest.timestamp).toLocaleTimeString()}`);
}

function renderTelemetryCharts() {
  Object.keys(TELEMETRY_METRICS).forEach(renderTelemetryChart);
}

function showTelemetryHistory(payload) {
  telemetryHistory = Array.isArray(payload?.points) ? payload.points : [];
  const summary = document.querySelector("#telemetry-history-summary");
  if (summary) {
    summary.textContent = payload?.sample_count
      ? `${payload.sample_count} persistent samples · since ${formatTimestamp(payload.first_sample_utc)}`
      : "Persistent history · waiting for the first sample";
  }
  renderTelemetryCharts();
}

async function refreshTelemetryHistory() {
  const response = await fetch("/api/telemetry", {cache: "no-store"});
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Telemetry history API response failed");
  showTelemetryHistory(payload);
  return payload;
}

function formatBytes(value) {
  if (value === null || value === undefined) return "Unavailable";
  const gibibytes = value / (1024 ** 3);
  return `${gibibytes.toFixed(gibibytes >= 10 ? 0 : 1)} GiB`;
}

function formatUptime(seconds) {
  if (seconds === null || seconds === undefined) return "Unavailable";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  return days ? `${days}d ${hours}h` : `${hours}h`;
}

function formatTransferBytes(bytes) {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KiB`;
}

function formatFrequency(frequencyHz) {
  const frequency = Number(frequencyHz);
  if (!Number.isFinite(frequency) || frequency <= 0) return "Frequency unavailable";
  return `${(frequency / 1e6).toFixed(3)} MHz`;
}

function formatTimestamp(timestamp) {
  if (!timestamp) return "Not recorded";
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? timestamp : parsed.toLocaleString();
}

function formatServiceUptime(startedUtc) {
  if (!startedUtc) return "Unavailable";
  const started = new Date(startedUtc);
  if (Number.isNaN(started.getTime())) return "Unavailable";
  return formatUptime(Math.max(0, Math.floor((Date.now() - started.getTime()) / 1000)));
}

function rmsGatewayOnAir(winlink) {
  const commissioning = Object.values(winlink?.commissioning || {});
  return winlink?.state === "operational"
    && Boolean(winlink.services?.linbpq?.active)
    && Boolean(winlink.services?.dire_wolf?.active)
    && Boolean(winlink.hardware?.ptt_serial_present)
    && commissioning.length > 0
    && commissioning.every(Boolean);
}

function showRmsSummary(gateway) {
  const winlink = gateway?.winlink || {};
  const identity = winlink.identity || {};
  const onAir = rmsGatewayOnAir(winlink);
  document.querySelector("#metric-rms").textContent = onAir ? "On air" : (winlink.state === "operational" ? "Standby" : "Service fault");
  document.querySelector("#metric-rms-detail").textContent = `${identity.rms_call || "RMS not configured"} · ${formatFrequency(identity.frequency_hz)} · ${identity.mode || "Mode unavailable"}`;
}

function showWinlink(gateway) {
  showRmsSummary(gateway);
  const winlink = gateway.winlink || {};
  const identity = winlink.identity || {};
  const services = winlink.services || {};
  const session = winlink.last_rf_session;
  const queues = winlink.queues || {};
  const state = document.querySelector("#winlink-state");
  const operational = winlink.state === "operational";
  state.textContent = operational ? "Operational" : "Service fault";
  state.className = `n0-status ${operational ? "n0-status--operational" : "n0-status--fault"}`;
  document.querySelector("#winlink-rms-call").textContent = identity.rms_call || "Not configured";
  const frequency = identity.frequency_hz ? `${(identity.frequency_hz / 1e6).toFixed(3)} MHz` : "Frequency unavailable";
  document.querySelector("#winlink-channel").textContent = `${frequency} · ${identity.mode || "Mode unavailable"}`;
  document.querySelector("#winlink-node-call").textContent = [identity.node_call, identity.node_alias].filter(Boolean).join(" / ") || "—";
  document.querySelector("#winlink-post-office-call").textContent = identity.post_office_call || "—";
  document.querySelector("#winlink-linbpq-state").textContent = services.linbpq?.active ? "Running" : (services.linbpq?.state || "Unknown");
  document.querySelector("#winlink-direwolf-state").textContent = services.dire_wolf?.active ? "Running" : (services.dire_wolf?.state || "Unknown");

  document.querySelector("#winlink-session-caller").textContent = session?.caller || "No RF session";
  document.querySelector("#winlink-session-time").textContent = session ? formatTimestamp(session.timestamp_utc) : "No completed RF session recorded";
  document.querySelector("#winlink-session-result").textContent = session?.successful ? "Successful" : (session ? "Incomplete" : "Waiting");
  document.querySelector("#winlink-session-messages").textContent = session ? `${session.messages_sent} sent · ${session.messages_received} received` : "—";
  document.querySelector("#winlink-session-bytes").textContent = session ? `${formatTransferBytes(session.bytes_sent)} out · ${formatTransferBytes(session.bytes_received)} in` : "—";
  document.querySelector("#winlink-session-duration").textContent = session?.duration_seconds == null ? "—" : `${session.duration_seconds} seconds`;
  document.querySelector("#winlink-cms-state").textContent = winlink.cms?.last_session_successful ? "Authenticated" : "No successful session";

  const queueValue = (key) => queues.index_available === false ? "—" : String(queues[key] ?? 0);
  document.querySelector("#winlink-mail-pending").textContent = queueValue("pending");
  document.querySelector("#winlink-mail-delivered").textContent = queueValue("delivered");
  document.querySelector("#winlink-mail-received").textContent = queueValue("received");
  document.querySelector("#winlink-mail-archived").textContent = queueValue("archived");

  document.querySelectorAll("[data-winlink-milestone]").forEach((row) => {
    const verified = Boolean(winlink.commissioning?.[row.dataset.winlinkMilestone]);
    row.classList.toggle("is-verified", verified);
    row.querySelector("strong").textContent = verified ? "Verified" : "Not verified";
  });
  document.querySelector("#winlink-updated").textContent = `Updated ${new Date().toLocaleTimeString()}`;
  showWinlinkStatistics(winlink.statistics_24h || {});
  showWinlinkReliability(winlink.reliability || {}, winlink.rf_diagnostics || {}, winlink.protocol_watchdog || {});
}

function showWinlinkReliability(reliability, diagnostic = {}, watchdog = {}) {
  const state = document.querySelector("#winlink-reliability-state");
  const labels = {healthy: "Healthy", warning: "Needs attention", fault: "Service fault"};
  state.textContent = labels[reliability.state] || "Unknown";
  state.className = `n0-status ${reliability.state === "healthy" ? "n0-status--operational" : reliability.state === "warning" ? "n0-status--advisory" : "n0-status--fault"}`;
  document.querySelector("#winlink-rms-uptime").textContent = formatServiceUptime(reliability.rms_started_utc);
  document.querySelector("#winlink-modem-uptime").textContent = formatServiceUptime(reliability.modem_started_utc);
  document.querySelector("#winlink-rms-restarts").textContent = `${reliability.rms_restart_count ?? 0} automatic restart${reliability.rms_restart_count === 1 ? "" : "s"}`;
  document.querySelector("#winlink-modem-restarts").textContent = `${reliability.modem_restart_count ?? 0} automatic restart${reliability.modem_restart_count === 1 ? "" : "s"}`;
  document.querySelector("#winlink-cms-connections").textContent = String(reliability.cms_connections ?? 0);
  document.querySelector("#winlink-cms-failures").textContent = String(reliability.cms_connection_failures ?? 0);
  document.querySelector("#winlink-modem-faults").textContent = String(reliability.modem_faults ?? 0);
  const cmsEvent = reliability.last_cms_event;
  document.querySelector("#winlink-cms-last-event").textContent = cmsEvent
    ? `${cmsEvent.successful ? "Last connected" : "Last attempt failed"} · ${formatTimestamp(cmsEvent.timestamp_utc)}`
    : "No CMS event in 24 hours";
  const phaseLabels = {
    idle: "Idle",
    connected: "Connected",
    cms_session: "CMS session",
    secure_login: "Secure login",
    mailbox_request: "Mailbox request",
    mailbox_index_generation: "Mailbox index generated",
    index_delivery: "Index delivery",
    client_acknowledgement: "Awaiting client acknowledgement",
    mailbox_transfer: "Mailbox transfer",
    disconnected: "Disconnected",
  };
  document.querySelector("#winlink-rf-phase").textContent = phaseLabels[diagnostic.phase] || "Unknown";
  document.querySelector("#winlink-rf-finding").textContent = watchdog.stale
    ? `STALE SESSION: ${watchdog.finding || diagnostic.finding || "No protocol progress detected."}`
    : (watchdog.finding || diagnostic.finding || "No protocol finding available.");
  document.querySelector("#winlink-rf-next-action").textContent = watchdog.stale
    ? "Use Recover stalled RMS session after confirming the RF channel is clear."
    : (watchdog.next_action || diagnostic.next_action || "Collect a bounded RF capture for the next session.");
}

function showWinlinkStatistics(statistics) {
  document.querySelector("#winlink-stat-sessions").textContent = String(statistics.sessions ?? 0);
  document.querySelector("#winlink-stat-callsigns").textContent = String(statistics.unique_callsigns ?? 0);
  document.querySelector("#winlink-stat-success").textContent = statistics.success_percent == null ? "—" : `${statistics.success_percent}%`;
  document.querySelector("#winlink-stat-duration").textContent = statistics.average_duration_seconds == null ? "—" : `${statistics.average_duration_seconds}s`;
  document.querySelector("#winlink-stat-sent").textContent = String(statistics.messages_sent ?? 0);
  document.querySelector("#winlink-stat-received").textContent = String(statistics.messages_received ?? 0);
  document.querySelector("#winlink-activity-window").textContent = `${statistics.window_hours || 24}-hour rolling window`;
  const chart = document.querySelector("#winlink-hourly-chart");
  const hourly = Array.isArray(statistics.hourly) ? statistics.hourly : [];
  const maximum = Math.max(1, ...hourly.map((item) => Number(item.sessions) || 0));
  chart.replaceChildren();
  hourly.forEach((item) => {
    const sessions = Number(item.sessions) || 0;
    const time = new Date(item.hour_utc);
    const bar = document.createElement("span");
    bar.className = "winlink-hour";
    bar.style.setProperty("--bar-height", `${sessions ? Math.max(8, (sessions / maximum) * 100) : 2}%`);
    bar.dataset.label = Number.isNaN(time.getTime()) ? "" : time.toLocaleTimeString([], {hour: "numeric"});
    bar.title = `${bar.dataset.label || item.hour_utc}: ${sessions} RF session${sessions === 1 ? "" : "s"}`;
    chart.appendChild(bar);
  });
  chart.setAttribute("aria-label", `${statistics.sessions || 0} Winlink RF sessions during the last ${statistics.window_hours || 24} hours`);
}

async function refreshWinlink() {
  if (!trialDataAllowed()) return;
  try {
    const response = await fetch("/api/gateway", {cache: "no-store"});
    if (!response.ok) throw new Error("Gateway status request failed");
    const gateway = await response.json();
    showWinlink(gateway);
    showServices(gateway);
  } catch (error) {
    const state = document.querySelector("#winlink-state");
    state.textContent = "Unavailable";
    state.className = "n0-status n0-status--fault";
    console.error("Winlink refresh failed", error);
  }
}

let winlinkSessionPage = 1;
let winlinkSessionSort = "newest";
let winlinkSessionResult = "all";
let winlinkSessionCallsign = "";

async function loadWinlinkSessions() {
  if (!trialDataAllowed()) return;
  const parameters = new URLSearchParams({
    page: String(winlinkSessionPage),
    sort: winlinkSessionSort,
    result: winlinkSessionResult,
  });
  if (winlinkSessionCallsign) parameters.set("callsign", winlinkSessionCallsign);
  const response = await fetch(`/api/winlink/sessions?${parameters}`, {cache: "no-store"});
  if (!response.ok) throw new Error("Winlink session history request failed");
  const payload = await response.json();
  winlinkSessionPage = payload.page;
  const body = document.querySelector("#winlink-session-list");
  body.replaceChildren();
  if (!payload.sessions.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "winlink-session-empty";
    cell.textContent = "No sessions match these filters.";
    row.appendChild(cell);
    body.appendChild(row);
  }
  payload.sessions.forEach((session) => {
    const row = document.createElement("tr");
    const values = [
      formatTimestamp(session.timestamp_utc),
      session.caller || "—",
      session.successful ? "Successful" : "Failed",
      session.duration_seconds == null ? "—" : `${session.duration_seconds}s`,
      `${session.messages_sent || 0} sent · ${session.messages_received || 0} received`,
      `${formatTransferBytes(session.bytes_sent)} out · ${formatTransferBytes(session.bytes_received)} in`,
    ];
    values.forEach((value, index) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (index === 2) cell.className = session.successful ? "session-success" : "session-failed";
      row.appendChild(cell);
    });
    body.appendChild(row);
  });
  document.querySelector("#winlink-session-page-info").textContent = `Page ${payload.page} of ${payload.pages} · ${payload.total} sessions`;
  document.querySelector("#winlink-session-prev").disabled = payload.page <= 1;
  document.querySelector("#winlink-session-next").disabled = payload.page >= payload.pages;
}

function initWinlinkSessionModal() {
  const modal = document.querySelector("#winlink-sessions");
  document.querySelector("#winlink-history-open")?.addEventListener("click", () => {
    modal.hidden = false;
    winlinkSessionPage = 1;
    loadWinlinkSessions().catch((error) => console.error("Winlink session history failed", error));
  });
  document.querySelector("#winlink-sessions-close")?.addEventListener("click", () => { modal.hidden = true; });
  document.querySelector("#winlink-session-filter")?.addEventListener("click", () => {
    winlinkSessionSort = document.querySelector("#winlink-session-sort").value;
    winlinkSessionResult = document.querySelector("#winlink-session-result-filter").value;
    winlinkSessionCallsign = document.querySelector("#winlink-session-callsign").value.trim().toUpperCase();
    winlinkSessionPage = 1;
    loadWinlinkSessions().catch((error) => console.error("Winlink session filter failed", error));
  });
  document.querySelector("#winlink-session-callsign")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      document.querySelector("#winlink-session-filter").click();
    }
  });
  document.querySelector("#winlink-session-prev")?.addEventListener("click", () => {
    winlinkSessionPage -= 1;
    loadWinlinkSessions().catch((error) => console.error("Winlink session page failed", error));
  });
  document.querySelector("#winlink-session-next")?.addEventListener("click", () => {
    winlinkSessionPage += 1;
    loadWinlinkSessions().catch((error) => console.error("Winlink session page failed", error));
  });
}

let operatorCsrfToken = "";
let adminReportSettingsLoaded = false;
let aprsAlertSettingsLoaded = false;
let wifiNetworks = [];
let wifiBusy = false;
let ethernetBusy = false;
let ethernetSettingsLoaded = false;

function selectedWifiNetwork() {
  const form = document.querySelector("#wifi-settings-form");
  return wifiNetworks.find((network) => network.ssid === form?.elements.ssid.value) || null;
}

function updateWifiFormState() {
  const form = document.querySelector("#wifi-settings-form");
  if (!form) return;
  const locked = !operatorCsrfToken;
  const network = selectedWifiNetwork();
  const passwordRequired = Boolean(network?.secured);
  form.elements.ssid.disabled = locked || wifiBusy || !wifiNetworks.length;
  form.elements.password.disabled = locked || wifiBusy || !network || !passwordRequired;
  form.elements.confirmation.disabled = locked || wifiBusy || !network || !passwordRequired;
  form.elements.password.required = passwordRequired;
  form.elements.confirmation.required = passwordRequired;
  form.querySelector("button[type='submit']").disabled = locked || wifiBusy || !network;
  document.querySelector("#wifi-scan").disabled = locked || wifiBusy;
}

function setWifiLocked(locked) {
  const form = document.querySelector("#wifi-settings-form");
  if (!form) return;
  if (locked) {
    wifiNetworks = [];
    form.elements.ssid.replaceChildren(new Option("Scan to select an SSID", ""));
    form.elements.password.value = "";
    form.elements.confirmation.value = "";
    document.querySelector("#wifi-current-state").textContent = "Operator login required";
    form.querySelector("output").textContent = "Unlock Protected operator controls to scan or connect.";
  } else if (!wifiNetworks.length) {
    document.querySelector("#wifi-current-state").textContent = "Ready to scan";
  }
  updateWifiFormState();
}

function showCurrentWifi(current) {
  const state = document.querySelector("#wifi-current-state");
  if (!state) return;
  if (!current?.ssid) {
    state.textContent = "Wi-Fi disconnected";
    state.className = "application-state application-state--offline";
    return;
  }
  state.textContent = `${current.ssid}${current.address ? ` - ${current.address}` : ""}`;
  state.className = "application-state application-state--online";
}

async function scanWifiNetworks() {
  const form = document.querySelector("#wifi-settings-form");
  const output = form.querySelector("output");
  wifiBusy = true;
  updateWifiFormState();
  output.textContent = "Scanning visible Wi-Fi networks...";
  try {
    const response = await fetch("/api/operator/action", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": operatorCsrfToken},
      body: JSON.stringify({action: "wifi_scan"}),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || "Wi-Fi scan failed");
    wifiNetworks = Array.isArray(payload.networks) ? payload.networks : [];
    const options = [new Option(wifiNetworks.length ? "Select a Wi-Fi network" : "No visible networks found", "")];
    wifiNetworks.forEach((network) => {
      const security = network.secured ? "Secured" : "Open";
      options.push(new Option(`${network.ssid} - ${security} - ${Number(network.signal_dbm).toFixed(0)} dBm`, network.ssid));
    });
    form.elements.ssid.replaceChildren(...options);
    const currentMatch = wifiNetworks.find((network) => network.ssid === payload.current?.ssid);
    if (currentMatch) form.elements.ssid.value = currentMatch.ssid;
    showCurrentWifi(payload.current);
    output.textContent = `${wifiNetworks.length} unique visible ${wifiNetworks.length === 1 ? "network" : "networks"} found.`;
  } catch (error) {
    output.textContent = error.message;
  } finally {
    wifiBusy = false;
    updateWifiFormState();
  }
}

function initWifiSettings() {
  const form = document.querySelector("#wifi-settings-form");
  if (!form) return;
  document.querySelector("#wifi-scan")?.addEventListener("click", scanWifiNetworks);
  form.elements.ssid.addEventListener("change", () => {
    form.elements.password.value = "";
    form.elements.confirmation.value = "";
    updateWifiFormState();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const network = selectedWifiNetwork();
    const output = form.querySelector("output");
    if (!network) {
      output.textContent = "Select a scanned Wi-Fi network.";
      return;
    }
    const password = network.secured ? form.elements.password.value : "";
    if (network.secured && password !== form.elements.confirmation.value) {
      output.textContent = "The Wi-Fi passwords do not match.";
      return;
    }
    const validPassword = (password.length >= 8 && password.length <= 63) || (password.length === 64 && /^[0-9a-f]+$/i.test(password));
    if (network.secured && !validPassword) {
      output.textContent = "Use 8-63 characters, or exactly 64 hexadecimal characters.";
      return;
    }
    if (!window.confirm(`Connect the ROC Wi-Fi interface to ${network.ssid}? Ethernet remains the preferred route and a failed connection will roll back automatically.`)) return;
    wifiBusy = true;
    updateWifiFormState();
    output.textContent = `Connecting to ${network.ssid}; this can take up to 30 seconds...`;
    try {
      const response = await fetch("/api/operator/action", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": operatorCsrfToken},
        body: JSON.stringify({action: "wifi_connect", ssid: network.ssid, password}),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Wi-Fi connection failed and was rolled back");
      form.elements.password.value = "";
      form.elements.confirmation.value = "";
      showCurrentWifi(payload.current);
      output.textContent = payload.message || `Connected to ${network.ssid}.`;
    } catch (error) {
      form.elements.password.value = "";
      form.elements.confirmation.value = "";
      output.textContent = error.message;
    } finally {
      wifiBusy = false;
      updateWifiFormState();
    }
  });
}

function updateEthernetFormState(pending = false) {
  const form = document.querySelector("#ethernet-settings-form");
  if (!form) return;
  const locked = !operatorCsrfToken;
  document.querySelector("#ethernet-load").disabled = locked || ethernetBusy;
  form.elements.interface.disabled = locked || ethernetBusy;
  form.elements.address_cidr.disabled = locked || ethernetBusy || pending;
  form.elements.gateway.disabled = locked || ethernetBusy || pending;
  form.elements.dns.disabled = locked || ethernetBusy || pending;
  form.querySelector("button[type='submit']").disabled = locked || ethernetBusy || pending || !form.elements.interface.value;
  const confirmButton = document.querySelector("#ethernet-confirm");
  confirmButton.hidden = !pending;
  confirmButton.disabled = locked || ethernetBusy || !pending;
  form.dataset.pending = pending ? "true" : "false";
}

function setEthernetLocked(locked) {
  const form = document.querySelector("#ethernet-settings-form");
  if (!form) return;
  if (locked) {
    ethernetSettingsLoaded = false;
    document.querySelector("#ethernet-current-state").textContent = "Operator login required";
    form.querySelector("output").textContent = "Unlock Protected operator controls to view or change Ethernet settings.";
  }
  updateEthernetFormState(form.dataset.pending === "true");
}

function showEthernetStatus(status) {
  const form = document.querySelector("#ethernet-settings-form");
  const state = document.querySelector("#ethernet-current-state");
  if (!form || !status) return;
  form.elements.interface.value = status.interface || "";
  form.elements.address_cidr.value = status.address_cidr || "";
  form.elements.gateway.value = status.gateway || "";
  if (status.dns) form.elements.dns.value = status.dns;
  state.textContent = status.pending
    ? `Confirmation pending - ${status.address_cidr}`
    : status.address_cidr || "No wired IPv4 address";
  state.className = `application-state ${status.address_cidr ? "application-state--online" : "application-state--offline"}`;
  updateEthernetFormState(Boolean(status.pending));
}

async function ethernetAction(action, settings = {}) {
  const response = await fetch("/api/operator/action", {
    method: "POST",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": operatorCsrfToken},
    body: JSON.stringify({action, ...settings}),
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) throw new Error(payload.error || "Ethernet operation failed");
  return payload;
}

async function loadEthernetStatus() {
  const form = document.querySelector("#ethernet-settings-form");
  const output = form.querySelector("output");
  ethernetBusy = true;
  updateEthernetFormState(form.dataset.pending === "true");
  output.textContent = "Reading current Ethernet settings...";
  try {
    const payload = await ethernetAction("ethernet_status");
    showEthernetStatus(payload.ethernet);
    ethernetSettingsLoaded = true;
    output.textContent = payload.ethernet?.pending
      ? "Reconnect at the pending address and confirm it before the 3-minute rollback expires."
      : "Current wired interface settings loaded.";
  } catch (error) {
    output.textContent = error.message;
  } finally {
    ethernetBusy = false;
    updateEthernetFormState(form.dataset.pending === "true");
  }
}

function initEthernetSettings() {
  const form = document.querySelector("#ethernet-settings-form");
  if (!form) return;
  document.querySelector("#ethernet-load")?.addEventListener("click", loadEthernetStatus);
  document.querySelector("#ethernet-confirm")?.addEventListener("click", async () => {
    if (!window.confirm("Confirm this static Ethernet address and cancel the automatic rollback?")) return;
    ethernetBusy = true;
    updateEthernetFormState(true);
    try {
      const payload = await ethernetAction("ethernet_confirm");
      showEthernetStatus(payload.ethernet);
      form.querySelector("output").textContent = payload.message || "Static Ethernet address confirmed.";
    } catch (error) {
      form.querySelector("output").textContent = error.message;
    } finally {
      ethernetBusy = false;
      updateEthernetFormState(form.dataset.pending === "true");
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const settings = {
      interface: form.elements.interface.value.trim(),
      address_cidr: form.elements.address_cidr.value.trim(),
      gateway: form.elements.gateway.value.trim(),
      dns: form.elements.dns.value.trim(),
    };
    if (!window.confirm(`Apply ${settings.address_cidr} to ${settings.interface}? The old configuration will return automatically unless this address is confirmed within 3 minutes.`)) return;
    const host = settings.address_cidr.split("/")[0];
    const port = window.location.port ? `:${window.location.port}` : "";
    const reconnectUrl = `${window.location.protocol}//${host}${port}/#application-settings`;
    ethernetBusy = true;
    updateEthernetFormState(false);
    form.querySelector("output").textContent = "Applying the static address and starting the rollback timer...";
    try {
      const payload = await ethernetAction("ethernet_set", settings);
      showEthernetStatus(payload.ethernet);
      form.querySelector("output").textContent = `${payload.message}. Reopening ${reconnectUrl}`;
      window.setTimeout(() => window.location.assign(reconnectUrl), 2500);
    } catch (error) {
      form.querySelector("output").textContent = error.message;
    } finally {
      ethernetBusy = false;
      updateEthernetFormState(form.dataset.pending === "true");
    }
  });
}

function setAdminReportLocked(locked) {
  const form = document.querySelector("#admin-report-settings-form");
  if (!form) return;
  form.elements.enabled.disabled = locked;
  form.elements.recipient.disabled = locked;
  form.elements.interval_hours.disabled = locked;
  form.querySelector("button[type='submit']").disabled = locked;
  document.querySelector("#admin-report-send-now").disabled = locked;
  if (locked) {
    adminReportSettingsLoaded = false;
    document.querySelector("#admin-report-credentials").textContent = "Operator login required";
    form.querySelector("output").textContent = "Unlock Protected operator controls to view or change these settings.";
  }
}

function setAprsAlertLocked(locked) {
  const form = document.querySelector("#aprs-alert-settings-form");
  if (!form) return;
  form.elements.enabled.disabled = locked;
  form.elements.recipient.disabled = locked;
  form.querySelector("button[type='submit']").disabled = locked;
  document.querySelector("#aprs-alert-send-test").disabled = locked;
  if (locked) {
    aprsAlertSettingsLoaded = false;
    form.querySelector("output").textContent = "Unlock Protected operator controls to configure alerts.";
  }
}

function showAprsAlertSettings(payload) {
  const form = document.querySelector("#aprs-alert-settings-form");
  if (!form) return;
  form.elements.enabled.checked = Boolean(payload.enabled);
  form.elements.recipient.value = payload.recipient || "";
  document.querySelector("#aprs-alert-sender").textContent = payload.sender || "roc@n0jcg.com";
  setAprsAlertLocked(false);
  document.querySelector("#aprs-alert-send-test").disabled = !payload.enabled;
}

function setCwopLocked(locked) {
  const form = document.querySelector("#cwop-settings-form");
  if (!form) return;
  [...form.elements].forEach((element) => { element.disabled = locked; });
  form.querySelector("output").textContent = locked ? "Unlock Protected operator controls to configure CWOP." : "CWOP settings are operator-protected.";
}

let cwopSettingsDirty = false;

function showCwopSettings(payload) {
  const form = document.querySelector("#cwop-settings-form");
  if (!form) return;
  form.elements.enabled.checked = Boolean(payload.enabled);
  form.elements.station_id.value = payload.station_id || "";
  form.elements.latitude.value = payload.latitude || "";
  form.elements.longitude.value = payload.longitude || "";
  form.elements.interval_seconds.value = payload.interval_seconds || 300;
  const state = document.querySelector("#cwop-configured");
  state.textContent = payload.configured ? (payload.enabled ? "Enabled" : "Configured") : "Not configured";
  state.className = `application-state application-state--${payload.configured ? (payload.enabled ? "online" : "advisory") : "offline"}`;
  cwopSettingsDirty = false;
  setCwopLocked(false);
}

async function loadCwopSettings() {
  if (cwopSettingsDirty) return null;
  const response = await fetch("/api/weather/cwop/settings", {cache: "no-store", credentials: "same-origin"});
  if (!response.ok) throw new Error(response.status === 401 ? "Operator login required" : "CWOP settings request failed");
  const payload = await response.json();
  showCwopSettings(payload);
  return payload;
}

function initCwopSettings() {
  const form = document.querySelector("#cwop-settings-form");
  form?.addEventListener("input", () => { cwopSettingsDirty = true; });
  form?.addEventListener("change", () => { cwopSettingsDirty = true; });
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const output = form.querySelector("output");
    try {
      const response = await fetch("/api/weather/cwop/settings", {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json", "X-CSRF-Token": operatorCsrfToken}, body: JSON.stringify({enabled: form.elements.enabled.checked, station_id: form.elements.station_id.value.trim(), latitude: form.elements.latitude.value, longitude: form.elements.longitude.value, interval_seconds: Number(form.elements.interval_seconds.value)})});
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "CWOP settings could not be saved");
      showCwopSettings(payload);
      output.textContent = payload.enabled ? "CWOP weather upload enabled." : "CWOP weather upload disabled.";
    } catch (error) { output.textContent = error.message; }
  });
}

async function loadAprsAlertSettings() {
  const response = await fetch("/api/aprs/alerts/settings", {cache: "no-store", credentials: "same-origin"});
  if (!response.ok) throw new Error(response.status === 401 ? "Operator login required" : "APRS alert settings request failed");
  const payload = await response.json();
  showAprsAlertSettings(payload);
  return payload;
}

function showAdminReportSettings(payload) {
  const form = document.querySelector("#admin-report-settings-form");
  if (!form) return;
  form.elements.enabled.checked = Boolean(payload.enabled);
  form.elements.recipient.value = payload.recipient || "";
  form.elements.interval_hours.value = payload.interval_hours || 12;
  form.elements.sender.value = payload.sender || "ROC@n0jcg.com";
  const credentialState = document.querySelector("#admin-report-credentials");
  credentialState.textContent = payload.credentials_configured ? "Email service ready" : "Email credentials required";
  credentialState.className = `application-state application-state--${payload.credentials_configured ? "online" : "offline"}`;
  const delivery = payload.delivery || {};
  document.querySelector("#admin-report-delivery").textContent = delivery.last_sent_utc
    ? `Last sent ${formatTimestamp(delivery.last_sent_utc)} · next ${formatTimestamp(delivery.next_due_utc)}`
    : (delivery.next_due_utc ? `Next report ${formatTimestamp(delivery.next_due_utc)}` : "No report has been sent yet.");
  setAdminReportLocked(false);
  document.querySelector("#admin-report-send-now").disabled = !payload.enabled || !payload.credentials_configured || Boolean(payload.send_now_queued);
  adminReportSettingsLoaded = true;
}

async function loadAdminReportSettings() {
  const response = await fetch("/api/admin-report/settings", {cache: "no-store", credentials: "same-origin"});
  if (!response.ok) throw new Error(response.status === 401 ? "Operator login required" : "Report settings request failed");
  const payload = await response.json();
  showAdminReportSettings(payload);
  return payload;
}

function showOperatorStatus(status) {
  const badge = document.querySelector("#operator-auth-state");
  const login = document.querySelector("#operator-login-form");
  const setup = document.querySelector("#operator-setup-required");
  const actions = document.querySelector("#operator-actions");
  const cmsTest = document.querySelector('[data-operator-action="cms_test"]');
  const cmsGuard = document.querySelector("#operator-cms-guard");
  operatorCsrfToken = status.csrf_token || "";
  const telemetryReset = document.querySelector("#telemetry-reset");
  if (telemetryReset) {
    telemetryReset.disabled = !status.authenticated;
    telemetryReset.title = status.authenticated ? "Delete all stored trend history" : "Operator login required to reset trends";
  }
  setAdminReportLocked(!status.authenticated);
  setAprsAlertLocked(!status.authenticated);
  setCwopLocked(!status.authenticated);
  setWifiLocked(!status.authenticated);
  setEthernetLocked(!status.authenticated);
  setup.hidden = status.configured;
  login.hidden = !status.configured || status.authenticated;
  actions.hidden = !status.authenticated;
  if (!status.configured) {
    badge.textContent = "Setup required";
    badge.className = "n0-status n0-status--advisory";
  } else if (status.authenticated) {
    badge.textContent = status.maintenance_mode ? "Maintenance" : "Operator";
    badge.className = `n0-status ${status.maintenance_mode ? "n0-status--advisory" : "n0-status--operational"}`;
  } else {
    badge.textContent = "Locked";
    badge.className = "n0-status n0-status--unknown";
  }
  document.querySelector('[data-operator-action="restart"]').disabled = !status.authenticated;
  document.querySelector('[data-operator-action="rms_recover"]').disabled = !status.authenticated || Boolean(status.maintenance_mode) || Boolean(status.rf_session_active);
  document.querySelector('[data-operator-action="maintenance_on"]').disabled = !status.authenticated || Boolean(status.maintenance_mode);
  document.querySelector('[data-operator-action="maintenance_off"]').disabled = !status.authenticated || !status.maintenance_mode;
  const cmsBlocked = !status.authenticated || status.maintenance_mode || !status.rf_activity_check_available || status.rf_session_active;
  cmsTest.disabled = cmsBlocked;
  if (!status.rf_activity_check_available) {
    cmsGuard.textContent = "CMS test blocked: the ROC cannot verify RF activity.";
  } else if (status.rf_session_active) {
    cmsGuard.textContent = "CMS test blocked: an RF session is active.";
  } else if (status.maintenance_mode) {
    cmsGuard.textContent = "CMS test unavailable while the gateway is in maintenance mode.";
  } else {
    cmsGuard.textContent = "RF channel idle. CMS connection testing is available.";
  }
  cmsGuard.classList.toggle("is-blocked", cmsBlocked && status.authenticated);
}

async function refreshOperatorStatus() {
  const response = await fetch("/api/operator/status", {cache: "no-store", credentials: "same-origin"});
  if (!response.ok) throw new Error("Operator status request failed");
  const status = await response.json();
  showOperatorStatus(status);
  if (status.authenticated && !adminReportSettingsLoaded) {
    await loadAdminReportSettings();
  }
  if (status.authenticated && !aprsAlertSettingsLoaded) {
    await loadAprsAlertSettings();
    aprsAlertSettingsLoaded = true;
  }
  if (status.authenticated) await loadCwopSettings().catch(() => {});
  if (status.authenticated && !ethernetSettingsLoaded) {
    await loadEthernetStatus();
  }
  return status;
}

function operatorMessage(message, failed = false) {
  const output = document.querySelector("#operator-result");
  output.textContent = message;
  output.classList.toggle("is-error", failed);
}

async function runOperatorAction(action) {
  const confirmations = {
    restart: "Restart the Winlink RMS and Dire Wolf services now? Active sessions will be disconnected.",
    rms_recover: "Recover a stalled RMS session? This stops and restarts only LinBPQ RMS after verifying that no RF session is active.",
    maintenance_on: "Stop the Winlink RMS and modem and enter maintenance mode?",
    maintenance_off: "Start the Winlink modem and RMS and return the gateway online?",
    cms_test: "Run a network-only authenticated CMS connectivity test? The ROC will block this action if an RF session is active.",
  };
  if (!window.confirm(confirmations[action])) return;
  const buttons = [...document.querySelectorAll("#operator-actions button")];
  buttons.forEach((button) => { button.disabled = true; });
  operatorMessage("Operator action in progress…");
  try {
    const response = await fetch("/api/operator/action", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": operatorCsrfToken},
      body: JSON.stringify({action}),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || payload.message || "Operator action failed");
    operatorMessage(payload.message || "Operator action completed successfully.");
    await new Promise((resolve) => window.setTimeout(resolve, 750));
    await Promise.all([refreshOperatorStatus(), refreshWinlink()]);
  } catch (error) {
    operatorMessage(error.message, true);
    await refreshOperatorStatus().catch(() => {});
  } finally {
    const status = await refreshOperatorStatus().catch(() => null);
    if (!status?.authenticated) buttons.forEach((button) => { button.disabled = true; });
  }
}

function initOperatorControls() {
  const form = document.querySelector("#operator-login-form");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    operatorMessage("Authenticating…");
    try {
      const response = await fetch("/api/operator/login", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({password: form.elements.password.value}),
      });
      const payload = await response.json();
      form.reset();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Login failed");
      operatorCsrfToken = payload.csrf_token;
      operatorMessage("Operator session unlocked for 30 minutes.");
      await refreshOperatorStatus();
    } catch (error) {
      form.elements.password.value = "";
      operatorMessage(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
  document.querySelectorAll("[data-operator-action]").forEach((button) => {
    button.addEventListener("click", () => runOperatorAction(button.dataset.operatorAction));
  });
  document.querySelector("#operator-logout")?.addEventListener("click", async () => {
    const response = await fetch("/api/operator/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": operatorCsrfToken},
      body: "{}",
    });
    operatorCsrfToken = "";
    adminReportSettingsLoaded = false;
    aprsAlertSettingsLoaded = false;
    operatorMessage(response.ok ? "Operator session locked." : "Sign out failed.", !response.ok);
    await refreshOperatorStatus();
  });
  document.querySelector("#operator-diagnostics")?.addEventListener("click", async () => {
    operatorMessage("Preparing privacy-safe diagnostics…");
    try {
      const response = await fetch("/api/operator/diagnostics", {cache: "no-store", credentials: "same-origin"});
      if (!response.ok) throw new Error("Diagnostics download failed");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "n0jcg-roc-diagnostics.json";
      link.click();
      URL.revokeObjectURL(url);
      operatorMessage("Diagnostics downloaded.");
    } catch (error) {
      operatorMessage(error.message, true);
    }
  });
  document.querySelector("#telemetry-reset")?.addEventListener("click", async () => {
    if (!window.confirm("Permanently delete all stored Performance Trends history? This cannot be undone.")) return;
    const button = document.querySelector("#telemetry-reset");
    const output = document.querySelector("#telemetry-reset-result");
    button.disabled = true;
    output.textContent = "Resetting…";
    try {
      const response = await fetch("/api/telemetry/reset", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": operatorCsrfToken},
        body: "{}",
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Trend history could not be reset");
      showTelemetryHistory(payload);
      output.textContent = `${payload.deleted_samples} stored samples deleted.`;
    } catch (error) {
      output.textContent = error.message;
    } finally {
      button.disabled = !operatorCsrfToken;
    }
  });
  refreshOperatorStatus().catch((error) => operatorMessage(error.message, true));
  window.setInterval(() => refreshOperatorStatus().catch(() => {}), 5000);
}

function initAdminReportSettings() {
  const form = document.querySelector("#admin-report-settings-form");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const output = form.querySelector("output");
    const button = form.querySelector("button[type='submit']");
    output.textContent = "Saving…";
    button.disabled = true;
    try {
      const response = await fetch("/api/admin-report/settings", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": operatorCsrfToken},
        body: JSON.stringify({
          enabled: form.elements.enabled.checked,
          recipient: form.elements.recipient.value.trim(),
          interval_hours: Number(form.elements.interval_hours.value),
        }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Report settings could not be saved");
      showAdminReportSettings(payload);
      output.textContent = payload.enabled ? "Periodic reports enabled." : "Periodic reports disabled.";
    } catch (error) {
      output.textContent = error.message;
    } finally {
      button.disabled = !operatorCsrfToken;
    }
  });
  document.querySelector("#admin-report-send-now")?.addEventListener("click", async () => {
    const output = form.querySelector("output");
    const button = document.querySelector("#admin-report-send-now");
    button.disabled = true;
    output.textContent = "Queuing operator report…";
    try {
      const response = await fetch("/api/admin-report/send-now", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": operatorCsrfToken},
        body: "{}",
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Report could not be queued");
      output.textContent = "Report queued. Waiting for delivery status…";
      const requestedUtc = payload.requested_utc;
      for (let attempt = 0; attempt < 12; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2500));
        const status = await loadAdminReportSettings();
        const attemptedUtc = status.delivery?.last_attempt_utc;
        if (attemptedUtc && (!requestedUtc || attemptedUtc >= requestedUtc)) {
          if (status.delivery.status === "sent") output.textContent = "Operator report sent successfully.";
          else output.textContent = status.delivery.error || "Operator report delivery failed.";
          return;
        }
      }
      output.textContent = "Report remains queued; delivery status will update shortly.";
    } catch (error) {
      output.textContent = error.message;
    } finally {
      await loadAdminReportSettings().catch(() => {});
    }
  });
  setAdminReportLocked(true);
}

function initAprsAlertSettings() {
  const form = document.querySelector("#aprs-alert-settings-form");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const output = form.querySelector("output");
    const button = form.querySelector("button[type='submit']");
    button.disabled = true;
    output.textContent = "Saving alert settings…";
    try {
      const response = await fetch("/api/aprs/alerts/settings", {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json", "X-CSRF-Token": operatorCsrfToken}, body: JSON.stringify({enabled: form.elements.enabled.checked, recipient: form.elements.recipient.value.trim()})});
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Alert settings could not be saved");
      showAprsAlertSettings(payload);
      output.textContent = payload.enabled ? "APRS pipeline alerts enabled." : "APRS pipeline alerts disabled.";
    } catch (error) { output.textContent = error.message; }
    finally { button.disabled = !operatorCsrfToken; }
  });
  document.querySelector("#aprs-alert-send-test")?.addEventListener("click", async () => {
    const output = form.querySelector("output");
    const button = document.querySelector("#aprs-alert-send-test");
    button.disabled = true;
    output.textContent = "Sending test alert…";
    try {
      const response = await fetch("/api/aprs/alerts/send-test", {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json", "X-CSRF-Token": operatorCsrfToken}, body: "{}"});
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Test alert failed");
      output.textContent = "Test alert submitted.";
    } catch (error) { output.textContent = error.message; }
    finally { button.disabled = !operatorCsrfToken; }
  });
}

function showSystem(system) {
  document.querySelector("#metric-host").textContent = system.host.hostname;
  document.querySelector("#metric-platform").textContent = `${system.host.operating_system} ${system.host.kernel} · ${system.host.architecture}`;
  document.querySelector("#metric-uptime").textContent = formatUptime(system.resources.uptime_seconds);
  document.querySelector("#metric-load").textContent = `1 minute load: ${system.resources.load_1m ?? "unavailable"}`;
  const cpuPercent = system.resources.cpu?.utilization_percent;
  document.querySelector("#metric-cpu").textContent = cpuPercent === null || cpuPercent === undefined ? "—" : `${Number(cpuPercent).toFixed(1)}%`;
  document.querySelector("#metric-cpu-detail").textContent = `${system.resources.cpu?.logical_processors || "—"} logical processors · load ${system.resources.load_1m ?? "—"}`;
  const memoryPercent = system.resources.memory.used_percent;
  document.querySelector("#metric-memory").textContent = memoryPercent === null || memoryPercent === undefined ? "—" : `${Number(memoryPercent).toFixed(1)}%`;
  document.querySelector("#metric-memory-total").textContent = `${formatBytes(system.resources.memory.used_bytes)} used · ${formatBytes(system.resources.memory.total_bytes)} total`;
  const temperature = system.resources.temperature?.celsius;
  document.querySelector("#metric-temperature").textContent = temperature === null || temperature === undefined ? "—" : `${Number(temperature).toFixed(1)}°C`;
  document.querySelector("#metric-temperature-detail").textContent = system.resources.temperature?.source || "CPU temperature sensor unavailable";
  document.querySelector("#metric-disk").textContent = formatBytes(system.resources.disk.free_bytes);
  document.querySelector("#metric-disk-total").textContent = `${formatBytes(system.resources.disk.total_bytes)} total`;
  const requiredTools = Object.keys(system.tooling.commands || {});
  const installedTools = requiredTools.filter((tool) => system.tooling.commands[tool]);
  document.querySelector("#metric-tools").textContent = `${installedTools.length}/${requiredTools.length} installed`;
  document.querySelector("#metric-tools-detail").textContent = system.tooling.ready
    ? "All ROC software prerequisites are installed"
    : `Missing: ${system.tooling.missing.join(", ")}`;

  const hardwareCount = system.hardware.serial_by_id.length + system.hardware.usb_audio_cards.length + system.hardware.rtl_sdr_count;
  document.querySelector("#metric-hardware").textContent = hardwareCount ? `${hardwareCount} detected` : "None";
  document.querySelector("#metric-hardware-detail").textContent = `${system.hardware.serial_by_id.length} serial · ${system.hardware.usb_audio_cards.length} USB audio · ${system.hardware.rtl_sdr_count} RTL-SDR`;
  document.querySelector("#hardware-state").textContent = system.hardware.state === "bare-server" ? "Bare server ready" : "Devices present";
}

function showStation(station) {
  const overviewTitle = station.display?.overview_title || [station.station.callsign, station.station.site_label].filter(Boolean).join(" · ");
  document.querySelector("#site-name").textContent = overviewTitle;
  const form = document.querySelector("#station-settings-form");
  if (form) form.elements.overview_title.value = overviewTitle;
}

function initStationSettings() {
  const form = document.querySelector("#station-settings-form");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const output = form.querySelector("output");
    const button = form.querySelector("button[type='submit']");
    output.textContent = "Saving…";
    button.disabled = true;
    try {
      const response = await fetch("/api/station/settings", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({overview_title: form.elements.overview_title.value.trim()}),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Station overview could not be saved");
      document.querySelector("#site-name").textContent = payload.overview_title;
      form.elements.overview_title.value = payload.overview_title;
      output.textContent = "Saved";
    } catch (error) {
      output.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
}

function showAprs(aprs) {
  const pipeline = aprs.pipeline || {};
  const state = pipeline.state || (aprs.active ? "healthy" : "fault");
  const labels = {healthy: "Healthy", degraded: "Degraded", fault: "Fault", stopped: "Stopped"};
  const metric = document.querySelector("#metric-aprs");
  metric.textContent = labels[state] || state;
  metric.dataset.pipelineState = state;
  document.querySelector("#metric-aprs-detail").textContent = pipeline.summary || (aprs.active ? "RTL-SDR receive-only path" : "Listener not running");
  document.querySelector("#metric-aprs-packets").textContent = String(aprs.packet_count ?? 0);
  document.querySelector("#metric-aprs-packets-detail").textContent = aprs.packet_count ? "RF and Internet APRS frames" : "No APRS frames yet";
  const latest = aprs.last_packet || "—";
  let latestNode = document.querySelector("#metric-aprs-latest");
  if (latestNode && latestNode.tagName !== "A") {
    const link = document.createElement("a");
    link.id = latestNode.id;
    link.className = "metric-link";
    link.href = "#aprs-frames";
    latestNode.replaceWith(link);
    latestNode = link;
  }
  latestNode.textContent = latest;
  latestNode.href = "#aprs-frames";
  latestNode.onclick = (event) => {
    event.preventDefault();
    document.querySelector("#aprs-frames").hidden = false;
    loadAprsFrames();
  };
  const latestOrigin = aprs.last_packet_origin === "internet" ? "Internet-only beacon" : "RF decode";
  document.querySelector("#metric-aprs-latest-detail").textContent = aprs.last_packet
    ? `${latestOrigin} · ${aprs.last_packet_timestamp_utc || "timestamp unavailable"}`
    : "Waiting for an APRS frame";
  const detail = document.querySelector("#metric-aprs-detail");
  if (detail && pipeline.last_rf_packet_timestamp_utc) {
    detail.title = `Last RF decode: ${pipeline.last_rf_packet_timestamp_utc}; pipeline activity: ${pipeline.last_pipeline_activity_utc || "unknown"}`;
  }
  const quality = aprs.quality || {};
  const qualityFrames = document.querySelector("#aprs-quality-frames");
  if (qualityFrames) qualityFrames.textContent = `${quality.rf_frames ?? 0} RF`;
  const qualityState = document.querySelector("#aprs-quality-state");
  if (qualityState) qualityState.textContent = `${quality.unique_stations ?? 0} stations`;
  const qualityDetail = document.querySelector("#aprs-quality-detail");
  if (qualityDetail) qualityDetail.textContent = `${quality.duplicate_rate_percent ?? 0}% duplicates · avg decode ${quality.decode_confidence?.average ?? "—"}`;
  const isHealth = aprs.aprs_is || {};
  const isState = document.querySelector("#aprs-is-state");
  if (isState) isState.textContent = isHealth.state || "Unknown";
  const isServer = document.querySelector("#aprs-is-server");
  if (isServer) isServer.textContent = isHealth.server || "Not connected";
  const isDetail = document.querySelector("#aprs-is-detail");
  if (isDetail) isDetail.textContent = `${isHealth.authentication || "unknown"} · ${isHealth.reconnect_count ?? 0} connection${isHealth.reconnect_count === 1 ? "" : "s"} · last upload ${isHealth.last_successful_upload_utc || "—"}`;
  const history = aprs.rf_history || {};
  const historyPoints = document.querySelector("#aprs-rf-history-points");
  if (historyPoints) historyPoints.textContent = `${history.last_24h_rf_frames ?? 0} RF frames`;
  const historyState = document.querySelector("#aprs-rf-history-state");
  if (historyState) historyState.textContent = `${history.last_24h_stations ?? 0} stations`;
  const historyDetail = document.querySelector("#aprs-rf-history-detail");
  if (historyDetail) historyDetail.textContent = `Latest hour: ${history.latest_hour_rf_frames ?? 0} frames · avg confidence ${history.latest_hour_average_confidence ?? "—"} · history coverage ${history.coverage_hours ?? 0}/168 hours`;
  const historyChart = document.querySelector("#aprs-rf-history-chart");
  if (historyChart) {
    historyChart.replaceChildren();
    const points = (history.points || []).slice(-24);
    const maximum = Math.max(1, ...points.map((point) => Number(point.rf_frames || 0)));
    points.forEach((point) => {
      const bar = document.createElement("span");
      bar.className = "aprs-rf-history-bar";
      bar.style.height = `${Math.max(4, (Number(point.rf_frames || 0) / maximum) * 100)}%`;
      bar.title = `${point.hour_utc}: ${point.rf_frames || 0} frames`;
      historyChart.appendChild(bar);
    });
  }
}

function showAprsDigipeaterSurvey(payload) {
  const message = document.querySelector("#aprs-digi-survey-message");
  const list = document.querySelector("#aprs-digi-survey-list");
  if (!message || !list) return;
  document.querySelector("#aprs-digi-survey-window").textContent = `${payload.window_hours || 72}-hour window`;
  message.textContent = payload.message || "No survey result available.";
  list.replaceChildren();
  (payload.observed || []).forEach((item) => {
    const row = document.createElement("div");
    row.className = "aprs-digi-survey-row";
    const distance = item.source_distance_km == null ? "source distance unavailable" : `source ${item.source_distance_km} km from ROC`;
    row.innerHTML = `<strong></strong><span>${item.count} used hop${item.count === 1 ? "" : "s"} · last heard ${item.last_heard_utc || "unknown"} · ${distance}</span>`;
    row.querySelector("strong").textContent = item.callsign;
    list.appendChild(row);
  });
}

let aprsFramePage = 1;
let aprsFrameSort = "newest";
async function loadAprsFrames() {
  if (!trialDataAllowed()) return;
  const response = await fetch(`/api/aprs/frames?page=${aprsFramePage}&sort=${aprsFrameSort}`, {cache: "no-store"});
  const payload = await response.json();
  const list = document.querySelector("#aprs-frame-list");
  list.replaceChildren();
  payload.frames.forEach((item) => {
    const row = document.createElement("div");
    row.className = "aprs-frame";
    const origin = item.origin === "internet" ? "Internet" : "RF";
    row.innerHTML = `<time>${item.timestamp_utc || "Timestamp unavailable"} · ${origin}</time><code></code>`;
    row.querySelector("code").textContent = item.frame;
    list.appendChild(row);
  });
  document.querySelector("#aprs-page-info").textContent = `Page ${payload.page} of ${payload.pages} · ${payload.total} frames`;
  document.querySelector("#aprs-prev").disabled = payload.page <= 1;
  document.querySelector("#aprs-next").disabled = payload.page >= payload.pages;
}
function initAprsFrameModal() {
  const modal = document.querySelector("#aprs-frames");
  document.querySelector("#aprs-frames-close")?.addEventListener("click", () => { modal.hidden = true; });
  document.querySelector("#aprs-sort")?.addEventListener("change", (event) => { aprsFrameSort = event.target.value; aprsFramePage = 1; loadAprsFrames(); });
  document.querySelector("#aprs-prev")?.addEventListener("click", () => { aprsFramePage -= 1; loadAprsFrames(); });
  document.querySelector("#aprs-next")?.addEventListener("click", () => { aprsFramePage += 1; loadAprsFrames(); });
}

let aprsMap;
let aprsMarkerLayer;
let aprsAllBounds;
let aprsLocalBounds;
let aprsMapCenter = {latitude: 38.8008, longitude: -105.2001};

const APRS_SYMBOL_ROWS = [
  `!"#$%&'()*+,-./0`,
  "123456789:;<=>?@",
  "ABCDEFGHIJKLMNOP",
  "QRSTUVWXYZ[\\]^_`",
  "abcdefghijklmnop",
  "qrstuvwxyz{|}~",
];

function aprsSymbolAddress(character) {
  if (typeof character !== "string" || character.length !== 1) return null;
  for (let row = 0; row < APRS_SYMBOL_ROWS.length; row += 1) {
    const column = APRS_SYMBOL_ROWS[row].indexOf(character);
    if (column >= 0) return {row, column};
  }
  return null;
}

function aprsSymbolIcon(symbol) {
  if (typeof symbol !== "string" || symbol.length < 2) return null;
  const tableCode = symbol[0];
  const symbolCode = symbol[1];
  const symbolAddress = aprsSymbolAddress(symbolCode);
  if (!symbolAddress) return null;

  const table = tableCode === "/" ? "primary" : "alternate";
  const overlay = tableCode !== "/" && tableCode !== "\\" ? aprsSymbolAddress(tableCode) : null;
  const sprite = (kind, address) => `<span class="aprs-symbol-sprite" style="background-image:url('/assets/aprs-symbols-48-${kind}.png');background-position:-${address.column * 48}px -${address.row * 48}px"></span>`;
  const html = `<span class="aprs-symbol-stack">${sprite(table, symbolAddress)}${overlay ? sprite("overlay", overlay) : ""}</span>`;
  return L.divIcon({
    className: "aprs-symbol-marker",
    html,
    iconSize: [40, 40],
    iconAnchor: [20, 20],
    popupAnchor: [0, -20],
    tooltipAnchor: [0, -22],
  });
}

function initAprsMap() {
  const message = document.querySelector("#aprs-map-message");
  if (!window.L) {
    message.textContent = "The map library could not be loaded. Check the ROC internet connection.";
    return false;
  }
  if (aprsMap) return true;
  aprsMap = L.map("aprs-map", {scrollWheelZoom: false}).setView([38.8008, -105.2001], 8);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap contributors",
  }).addTo(aprsMap);
  aprsMarkerLayer = L.featureGroup().addTo(aprsMap);
  return true;
}

function stationPopup(station) {
  const panel = document.createElement("div");
  const heading = document.createElement("strong");
  heading.className = "aprs-marker-label";
  heading.textContent = station.callsign;
  panel.appendChild(heading);
  [
    station.heard_utc ? `Heard by ROC: ${station.heard_utc}` : null,
    station.last_report_utc ? `Last APRS report: ${station.last_report_utc}` : null,
    station.symbol ? `APRS symbol: ${station.symbol}` : null,
    station.comment || null,
    station.path ? `Path: ${station.path}` : null,
  ].filter(Boolean).forEach((text) => {
    const line = document.createElement("div");
    line.textContent = text;
    panel.appendChild(line);
  });
  if (station.heard_frame) {
    const frame = document.createElement("code");
    frame.className = "aprs-marker-frame";
    frame.textContent = station.heard_frame;
    panel.appendChild(frame);
  }
  const link = document.createElement("a");
  link.href = station.aprsfi_url;
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "Open on aprs.fi";
  panel.appendChild(link);
  return panel;
}

function focusAprsRocArea() {
  if (!aprsMap) return;
  aprsMap.invalidateSize();
  if (aprsLocalBounds?.isValid()) aprsMap.fitBounds(aprsLocalBounds.pad(0.35), {maxZoom: 17});
  else aprsMap.setView([aprsMapCenter.latitude, aprsMapCenter.longitude], 8);
}

function distanceKm(first, second) {
  const radians = (degrees) => Number(degrees) * Math.PI / 180;
  const latitudeDelta = radians(second.latitude - first.latitude);
  const longitudeDelta = radians(second.longitude - first.longitude);
  const latitude1 = radians(first.latitude);
  const latitude2 = radians(second.latitude);
  const haversine = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(latitude1) * Math.cos(latitude2) * Math.sin(longitudeDelta / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
}

function showAprsMap(payload) {
  const message = document.querySelector("#aprs-map-message");
  const summary = document.querySelector("#aprs-map-summary");
  const configured = document.querySelector("#aprsfi-configured");
  const settingsForm = document.querySelector("#aprsfi-settings-form");
  settingsForm.elements.enabled.checked = Boolean(payload.enabled);
  configured.textContent = payload.configured ? "Key saved" : "Key required";
  configured.className = `application-state ${payload.configured ? "application-state--online" : "application-state--offline"}`;
  const stations = payload.stations || [];
  const mapCenter = payload.map_center || {latitude: 38.8008, longitude: -105.2001};
  aprsMapCenter = mapCenter;
  const localStations = stations.filter((station) => distanceKm(mapCenter, station) <= 250);
  const outsideArea = stations.length - localStations.length;
  const showAllButton = document.querySelector("#aprs-map-show-all");
  showAllButton.hidden = outsideArea === 0;
  summary.textContent = `${payload.frame_count || 0} frames · ${payload.callsign_count || 0} callsigns heard in the last ${payload.window_hours || 24} hours · ${stations.length} current positions${outsideArea ? ` · ${outsideArea} outside ROC area` : ""}`;

  if (!initAprsMap()) return;
  aprsMarkerLayer.clearLayers();
  stations.forEach((station) => {
    const icon = aprsSymbolIcon(station.symbol);
    const marker = icon
      ? L.marker([station.latitude, station.longitude], {icon})
      : L.circleMarker([station.latitude, station.longitude], {
        radius: 8,
        color: "#0a1f44",
        weight: 2,
        fillColor: "#00b8d9",
        fillOpacity: 0.9,
      });
    marker.bindTooltip(station.callsign, {
      direction: "top",
      className: "aprs-callsign-tooltip",
    }).bindPopup(stationPopup(station)).addTo(aprsMarkerLayer);
  });
  if (aprsMarkerLayer.getLayers().length) {
    aprsAllBounds = aprsMarkerLayer.getBounds();
    if (localStations.length) {
      const localBounds = L.latLngBounds(localStations.map((station) => [station.latitude, station.longitude]));
      aprsLocalBounds = localBounds;
      focusAprsRocArea();
    } else {
      aprsLocalBounds = null;
      aprsMap.setView([mapCenter.latitude, mapCenter.longitude], 8);
    }
    message.hidden = true;
  } else {
    message.hidden = false;
    message.textContent = payload.message || payload.error || "No aprs.fi positions were found for recently heard callsigns.";
  }
  window.requestAnimationFrame(focusAprsRocArea);
  window.setTimeout(focusAprsRocArea, 220);
}

async function loadAprsMap(forceRefresh = false) {
  if (!trialDataAllowed()) return;
  const button = document.querySelector("#aprs-map-refresh");
  button.disabled = true;
  try {
    const response = await fetch(`/api/aprs-map${forceRefresh ? "?refresh=1" : ""}`, {cache: "no-store"});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "APRS map request failed");
    showAprsMap(payload);
  } catch (error) {
    const message = document.querySelector("#aprs-map-message");
    message.hidden = false;
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function initAprsMapSettings() {
  document.querySelector("#aprs-map-refresh").addEventListener("click", () => loadAprsMap(true));
  document.querySelector("#aprs-map-zoom-in").addEventListener("click", () => aprsMap?.zoomIn());
  document.querySelector("#aprs-map-zoom-out").addEventListener("click", () => aprsMap?.zoomOut());
  document.querySelector("#aprs-map-roc-area").addEventListener("click", () => {
    focusAprsRocArea();
  });
  document.querySelector("#aprs-map-show-all").addEventListener("click", () => {
    if (aprsMap && aprsAllBounds?.isValid()) aprsMap.fitBounds(aprsAllBounds.pad(0.12), {maxZoom: 12});
  });
  const form = document.querySelector("#aprsfi-settings-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const output = form.querySelector("output");
    const button = form.querySelector("button[type='submit']");
    const apiKey = form.elements.api_key.value.trim();
    output.textContent = "Saving…";
    button.disabled = true;
    try {
      const settings = {enabled: form.elements.enabled.checked};
      if (apiKey) settings.api_key = apiKey;
      const response = await fetch("/api/aprs-map/settings", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(settings),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "API key could not be saved");
      form.reset();
      output.textContent = "API key saved";
      await loadAprsMap(true);
    } catch (error) {
      output.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
}

function showApplicationStatus(application) {
  const card = document.querySelector(`[data-application-card="${application.id}"]`);
  const link = document.querySelector(application.id === "air_traffic" ? "#air-traffic-link" : "#scanner-link");
  const applicationState = document.querySelector(`[data-application-state="${application.id}"]`);
  if (card) card.hidden = !application.enabled;
  if (link) {
    link.href = application.url;
    link.target = "_blank";
    link.rel = "noopener";
  }
  if (applicationState) {
    applicationState.textContent = application.state === "online" ? `Online · ${application.host}:${application.port}` : application.state;
    applicationState.className = `application-state application-state--${application.state}`;
  }

  if (application.id !== "air_traffic") return;
  const state = document.querySelector("#metric-air-traffic");
  const detail = document.querySelector("#metric-air-traffic-detail");
  const aircraft = document.querySelector("#metric-aircraft");
  const aircraftDetail = document.querySelector("#metric-aircraft-detail");
  if (!application.enabled) {
    state.textContent = "Disabled";
    detail.textContent = "Enable Air Traffic in Application connections";
    aircraft.textContent = "—";
    aircraftDetail.textContent = "Application disabled";
  } else if (application.reachable) {
    state.textContent = "Online";
    detail.textContent = `Standalone Pi · ${application.host}:${application.port}`;
    aircraft.textContent = String(application.metrics?.aircraft_count ?? 0);
    aircraftDetail.textContent = `${application.metrics?.aircraft_with_position ?? 0} positioned`;
  } else {
    state.textContent = "Offline";
    detail.textContent = application.error || "N0JCG Air Traffic API unavailable";
    aircraft.textContent = "—";
    aircraftDetail.textContent = "No remote data";
  }
}

function showScannerReadiness(application) {
  const metrics = application.metrics || {};
  if (!application.enabled) {
    document.querySelector("#metric-scanner").textContent = "Disabled";
    document.querySelector("#metric-scanner-detail").textContent = "Enable Scanner in Application connections";
    document.querySelector("#metric-voice-calls").textContent = "Disabled";
    document.querySelector("#metric-vhf-locks").textContent = "—";
    document.querySelector("#metric-uhf-locks").textContent = "—";
    document.querySelector("#metric-voice-calls-detail").textContent = "Enable Scanner in Application connections";
    document.querySelector("#metric-vhf-locks-detail").textContent = "Application disabled";
    document.querySelector("#metric-uhf-locks-detail").textContent = "Application disabled";
    return;
  }
  if (!application.reachable) {
    document.querySelector("#metric-scanner").textContent = "Offline";
    document.querySelector("#metric-scanner-detail").textContent = "N0JCG Scanner API unavailable";
    document.querySelector("#metric-voice-calls").textContent = "—";
    document.querySelector("#metric-vhf-locks").textContent = "—";
    document.querySelector("#metric-uhf-locks").textContent = "—";
    document.querySelector("#metric-voice-calls-detail").textContent = "Scanner API unavailable";
    document.querySelector("#metric-vhf-locks-detail").textContent = "Scanner API unavailable";
    document.querySelector("#metric-uhf-locks-detail").textContent = "Scanner API unavailable";
    return;
  }
  document.querySelector("#metric-scanner").textContent = "Online";
  document.querySelector("#metric-scanner-detail").textContent = `Standalone Pi · ${application.host}:${application.port}`;
  document.querySelector("#metric-voice-calls").textContent = String(metrics.voice_calls ?? 0);
  document.querySelector("#metric-voice-calls-detail").textContent = "Distinct P25 voice calls";
  document.querySelector("#metric-vhf-locks").textContent = String(metrics.vhf_locks ?? 0);
  document.querySelector("#metric-vhf-locks-detail").textContent = metrics.vhf_state || "VHF analog scanner";
  document.querySelector("#metric-uhf-locks").textContent = String(metrics.uhf_locks ?? 0);
  document.querySelector("#metric-uhf-locks-detail").textContent = metrics.uhf_state || "UHF analog scanner";
}

function populateApplicationForm(application) {
  const form = document.querySelector(`[data-application-form="${application.id}"]`);
  if (!form) return;
  form.elements.enabled.checked = application.enabled;
  form.elements.host.value = application.host;
  form.elements.port.value = application.port;
}

function showApplications(payload) {
  applicationInventory = payload.applications || [];
  payload.applications.forEach((application) => {
    showApplicationStatus(application);
    populateApplicationForm(application);
    if (application.id === "scanner") showScannerReadiness(application);
  });
  if (latestGateway) showServices(latestGateway);
}

async function refreshApplications() {
  if (!trialDataAllowed()) return null;
  const response = await fetch("/api/applications", {cache: "no-store"});
  if (!response.ok) throw new Error("Application settings API response failed");
  const payload = await response.json();
  showApplications(payload);
  return payload;
}

async function refreshOverviewTelemetry() {
  if (!trialDataAllowed()) return null;
  const [systemResponse, aprsResponse, applicationsResponse, telemetryResponse] = await Promise.all([
    fetch("/api/system", {cache: "no-store"}),
    fetch("/api/aprs", {cache: "no-store"}),
    fetch("/api/applications", {cache: "no-store"}),
    fetch("/api/telemetry", {cache: "no-store"}),
  ]);
  if (![systemResponse, aprsResponse, applicationsResponse, telemetryResponse].every((response) => response.ok)) {
    throw new Error("Overview telemetry API response failed");
  }
  const system = await systemResponse.json();
  const aprs = await aprsResponse.json();
  const applications = await applicationsResponse.json();
  const telemetry = await telemetryResponse.json();
  showSystem(system);
  showAprs(aprs);
  showApplications(applications);
  showTelemetryHistory(telemetry);
  return {system, aprs, applications, telemetry};
}

function initApplicationSettings() {
  document.querySelectorAll("[data-application-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const applicationId = form.dataset.applicationForm;
      const output = form.querySelector("output");
      const button = form.querySelector("button[type='submit']");
      output.textContent = "Saving…";
      button.disabled = true;
      try {
        const response = await fetch("/api/applications", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({applications: {[applicationId]: {
            enabled: form.elements.enabled.checked,
            host: form.elements.host.value.trim(),
            port: Number(form.elements.port.value),
          }}}),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Settings could not be saved");
        output.textContent = "Saved";
        await refreshApplications();
      } catch (error) {
        output.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  });
}

function showWeather(status) {
  const state = document.querySelector("#metric-weather");
  const detail = document.querySelector("#metric-weather-detail");
  if (!state || !detail) return;
  if (!status.available || !status.observation) {
    state.textContent = "Waiting";
    detail.textContent = status.message || "Waiting for GW1100/WS90 data";
    document.querySelector("#weather-gateway").textContent = "Offline";
    document.querySelector("#weather-updated").textContent = "Waiting for gateway";
    document.querySelector("#weather-lightning").textContent = "—";
    document.querySelector("#weather-lightning-detail").textContent = "Waiting for WH57 sensor";
    return;
  }
  const fields = status.observation.fields || {};
  const cwop = status.cwop || {};
  document.querySelector("#weather-cwop").textContent = cwop.enabled && cwop.configured ? "Enabled" : "Disabled";
  document.querySelector("#weather-cwop-detail").textContent = cwop.configured ? `${cwop.station_id} · every ${cwop.interval_seconds}s` : "Operator configuration required";
  const observed = new Date(status.observation.received_utc);
  const observedLabel = Number.isNaN(observed.getTime()) ? status.observation.received_utc : observed.toLocaleString();
  const value = (number, digits = 1) => number == null ? "—" : Number(number).toFixed(digits);
  const fahrenheit = (celsius) => celsius == null ? null : (Number(celsius) * 9 / 5) + 32;
  const mph = (mps) => mps == null ? null : Number(mps) * 2.236936;
  const inches = (mm) => mm == null ? null : Number(mm) / 25.4;
  const inHg = (hpa) => hpa == null ? null : Number(hpa) / 33.863887;
  const compass = (degrees) => {
    if (degrees == null) return "—";
    const points = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
    return `${points[Math.round(Number(degrees) / 22.5) % 16]} ${Number(degrees).toFixed(0)}°`;
  };

  const outdoorDetected = Boolean(status.observation.outdoor_sensor_detected);
  state.textContent = outdoorDetected ? `${value(fahrenheit(fields.temperature_c))} °F` : "Gateway online";
  detail.textContent = status.stale ? `Weather data stale · ${observedLabel}` : `${outdoorDetected ? "WS90 online" : "WS90 not detected"} · ${observedLabel}`;
  document.querySelector("#weather-temperature").textContent = fields.temperature_c == null ? "—" : `${value(fahrenheit(fields.temperature_c))} °F`;
  document.querySelector("#weather-outdoor-state").textContent = outdoorDetected ? "WS90 reporting" : "WS90 not detected by gateway";
  document.querySelector("#weather-humidity").textContent = fields.humidity_percent == null ? "—" : `${value(fields.humidity_percent, 0)}%`;
  document.querySelector("#weather-wind").textContent = fields.wind_speed_mps == null ? "—" : `${value(mph(fields.wind_speed_mps))} mph`;
  document.querySelector("#weather-wind-detail").textContent = `${compass(fields.wind_direction_deg)} · gust ${fields.wind_gust_mps == null ? "—" : `${value(mph(fields.wind_gust_mps))} mph`}`;
  const relativePressure = fields.pressure_hpa;
  const absolutePressure = fields.pressure_absolute_hpa;
  const displayedPressure = relativePressure ?? absolutePressure;
  document.querySelector("#weather-pressure").textContent = displayedPressure == null ? "—" : `${value(inHg(displayedPressure), 2)} inHg`;
  document.querySelector("#weather-pressure-detail").textContent = [
    relativePressure == null ? null : `Relative ${value(inHg(relativePressure), 2)} inHg`,
    absolutePressure == null ? null : `Absolute ${value(inHg(absolutePressure), 2)} inHg`,
  ].filter(Boolean).join(" · ") || "Waiting for GW1100 pressure data";
  document.querySelector("#weather-rain").textContent = fields.rain_rate_mm_h == null ? "—" : `${value(inches(fields.rain_rate_mm_h), 2)} in/hr`;
  document.querySelector("#weather-rain-detail").textContent = fields.rain_today_mm == null ? "Today —" : `Today ${value(inches(fields.rain_today_mm), 2)} in`;
  document.querySelector("#weather-uv").textContent = fields.uv_index == null ? "—" : `UV ${value(fields.uv_index, 1)}`;
  document.querySelector("#weather-solar").textContent = fields.solar_w_m2 == null ? "Solar —" : `${value(fields.solar_w_m2, 0)} W/m²`;
  const lightningDetected = Boolean(status.observation.lightning_sensor_detected);
  const lightningCount = fields.lightning_count == null ? null : Number(fields.lightning_count);
  const lightningDistance = fields.lightning_distance && !String(fields.lightning_distance).includes("--") ? String(fields.lightning_distance) : null;
  const lightningLast = fields.lightning_last_local && !String(fields.lightning_last_local).includes("--") ? String(fields.lightning_last_local) : null;
  document.querySelector("#weather-lightning").textContent = !lightningDetected
    ? "Not detected"
    : lightningCount == null
      ? "—"
      : `${lightningCount.toFixed(0)} ${lightningCount === 1 ? "strike" : "strikes"}`;
  document.querySelector("#weather-lightning-detail").textContent = !lightningDetected
    ? "WH57 not detected by gateway"
    : [
      lightningLast ? `Last ${lightningLast}` : "No strike recorded",
      lightningDistance ? `${lightningDistance} away` : null,
      fields.lightning_battery_level == null ? null : `battery ${value(fields.lightning_battery_level, 0)}`,
      fields.lightning_signal_dbm == null ? null : `${value(fields.lightning_signal_dbm, 0)} dBm`,
    ].filter(Boolean).join(" · ");
  document.querySelector("#weather-indoor").textContent = fields.indoor_temperature_c == null ? "—" : `${value(fahrenheit(fields.indoor_temperature_c))} °F`;
  document.querySelector("#weather-indoor-detail").textContent = fields.indoor_humidity_percent == null ? "GW1100 sensor" : `${value(fields.indoor_humidity_percent, 0)}% RH`;
  document.querySelector("#weather-gateway").textContent = status.stale ? "Stale" : "Online";
  document.querySelector("#weather-gateway-detail").textContent = status.observation.gateway_url || "192.168.68.131";
  document.querySelector("#weather-updated").textContent = `Updated ${observedLabel}`;
}

async function refreshWeather() {
  if (!trialDataAllowed()) return;
  try {
    const response = await fetch("/api/weather", {cache: "no-store"});
    if (response.ok) showWeather(await response.json());
  } catch (error) {
    console.error("Weather refresh failed", error);
  }
}

async function loadOperationalData() {
  if (!trialDataAllowed()) return;
  try {
    const [healthResponse, stationResponse, servicesResponse, systemResponse, aprsResponse, weatherResponse, applicationsResponse, gatewayResponse, telemetryResponse, digipeaterResponse] = await Promise.all([
      fetch("/api/health"),
      fetch("/api/station"),
      fetch("/api/services"),
      fetch("/api/system"),
      fetch("/api/aprs"),
      fetch("/api/weather"),
      fetch("/api/applications", {cache: "no-store"}),
      fetch("/api/gateway", {cache: "no-store"}),
      fetch("/api/telemetry", {cache: "no-store"}),
      fetch("/api/aprs/digipeaters", {cache: "no-store"}),
    ]);
    if (![healthResponse, stationResponse, servicesResponse, systemResponse, aprsResponse, weatherResponse, applicationsResponse, gatewayResponse, telemetryResponse, digipeaterResponse].every((response) => response.ok)) {
      throw new Error("API response failed");
    }
    const health = await healthResponse.json();
    const station = await stationResponse.json();
    const inventory = await servicesResponse.json();
    const system = await systemResponse.json();
    const aprs = await aprsResponse.json();
    const weather = await weatherResponse.json();
    const applications = await applicationsResponse.json();
    const gateway = await gatewayResponse.json();
    const telemetry = await telemetryResponse.json();
    const digipeaterSurvey = await digipeaterResponse.json();

    badge.textContent = "Operational";
    badge.className = "n0-status n0-status--operational";
    showStation(station);
    document.querySelector("#version").textContent = health.version;

    const winlink = gateway.winlink || {};
    const identity = winlink.identity || {};
    const rmsOnAir = rmsGatewayOnAir(winlink);
    interlock.classList.toggle("interlock--operational", rmsOnAir);
    interlock.querySelector(".interlock-icon").textContent = rmsOnAir ? "RMS" : "TX";
    if (rmsOnAir) {
      interlock.querySelector("strong").textContent = "Winlink RMS on air";
      interlock.querySelector("small").textContent = `${identity.rms_call || "RMS"} · ${formatFrequency(identity.frequency_hz)} · ${identity.mode || "Packet"}`;
    } else {
      const reasons = health.transmit.reasons.join("; ");
      interlock.querySelector("strong").textContent = health.transmit.ready ? "Gateway ready" : "Gateway transmit unavailable";
      interlock.querySelector("small").textContent = reasons || "Commissioned gateway services are not currently on air";
    }
    serviceInventory = inventory.services;
    showSystem(system);
    showAprs(aprs);
    showAprsDigipeaterSurvey(digipeaterSurvey);
    loadAprsMap();
    showApplications(applications);
    showServices(gateway);
    showTelemetryHistory(telemetry);
    showWeather(weather);
    showWinlink(gateway);
    operationalStarted = true;
    if (!operationalIntervals.length) {
      operationalIntervals = [
        window.setInterval(refreshWeather, 30000),
        window.setInterval(refreshWinlink, 30000),
        window.setInterval(() => refreshOverviewTelemetry().catch((error) => console.error("Overview telemetry refresh failed", error)), 30000),
      ];
    }
  } catch (error) {
    badge.textContent = "Service fault";
    badge.className = "n0-status n0-status--fault";
    console.error(error);
  }
}

async function start() {
  initRegistration();
  initAprsFrameModal();
  initStationSettings();
  initAprsMapSettings();
  initApplicationSettings();
  initWinlinkSessionModal();
  initOperatorControls();
  initAdminReportSettings();
  initAprsAlertSettings();
  initCwopSettings();
  initWifiSettings();
  initEthernetSettings();
  try {
    await refreshRegistration();
    window.setInterval(() => refreshRegistration().catch((error) => {
      registrationMessage(error.message, true);
    }), 1000);
  } catch (error) {
    badge.textContent = "Service fault";
    badge.className = "n0-status n0-status--fault";
    registrationMessage(error.message, true);
    console.error(error);
  }
}

const workspacePanels = [...document.querySelectorAll("[data-workspace-panel]")];
const workspaceLinks = [...document.querySelectorAll(".app-rail nav [data-workspace-target]")];

function workspacePanelForHash(hash) {
  const requestedHash = hash && hash !== "#" ? hash : "#overview";
  let target;
  try {
    target = document.querySelector(requestedHash);
  } catch (_error) {
    target = null;
  }
  return target?.closest("[data-workspace-panel]")
    || document.querySelector('[data-workspace-panel="overview"]');
}

function showWorkspacePanel(hash, {updateHistory = false, scroll = true} = {}) {
  const panel = workspacePanelForHash(hash);
  if (!panel) return;
  const panelName = panel.dataset.workspacePanel;

  workspacePanels.forEach((item) => {
    item.hidden = item !== panel;
  });
  workspaceLinks.forEach((link) => {
    if (link.dataset.workspaceTarget === panelName) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });

  const selectedLink = workspaceLinks.find((link) => link.dataset.workspaceTarget === panelName);
  let selectedHash = selectedLink?.hash || "#overview";
  try {
    const requestedTarget = hash && hash !== "#" ? document.querySelector(hash) : null;
    if (requestedTarget?.closest("[data-workspace-panel]") === panel) {
      selectedHash = hash;
    }
  } catch (_error) {
    // Malformed or stale hashes fall back to the panel's primary navigation link.
  }
  if (updateHistory && window.location.hash !== selectedHash) {
    window.history.pushState({workspacePanel: panelName}, "", selectedHash);
  } else if (!window.location.hash) {
    window.history.replaceState({workspacePanel: panelName}, "", selectedHash);
  }

  if (scroll) window.scrollTo({top: 0, behavior: "smooth"});
  else if (selectedHash !== selectedLink?.hash) {
    window.requestAnimationFrame(() => document.querySelector(selectedHash)?.scrollIntoView({block: "start"}));
  }
  if (panelName === "aprs" && aprsMap) {
    window.requestAnimationFrame(focusAprsRocArea);
    window.setTimeout(focusAprsRocArea, 220);
  }
}

function initWorkspaceNavigation() {
  workspaceLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      showWorkspacePanel(link.hash, {updateHistory: true});
    });
  });
  window.addEventListener("popstate", () => showWorkspacePanel(window.location.hash, {scroll: false}));
  window.addEventListener("hashchange", () => showWorkspacePanel(window.location.hash, {scroll: false}));
  showWorkspacePanel(window.location.hash || "#overview", {scroll: false});
}

renderTelemetryCharts();
initWorkspaceNavigation();
start();
