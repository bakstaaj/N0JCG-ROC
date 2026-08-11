const badge = document.querySelector("#system-badge");
const interlock = document.querySelector("#interlock");
const serviceGrid = document.querySelector("#service-grid");
let registrationState = null;
let operationalStarted = false;
let operationalIntervals = [];
let serviceInventory = [];

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
  return service.state;
}

function serviceCard(service, gateway) {
  const card = document.createElement("article");
  card.className = "service-card";
  const serviceState = runtimeServiceState(service, gateway);
  const stateClass = {
    operational: "state state--operational",
    "service fault": "state state--fault",
    "external-node": "state state--observed",
  }[serviceState] || "state state--planned";
  card.innerHTML = `
    <span class="phase">Phase ${service.phase}</span>
    <h3>${service.name}</h3>
    <p>${service.hardware}<br>${service.rf_role}</p>
    <span class="${stateClass}">${serviceState}</span>`;
  return card;
}

function showServices(gateway) {
  serviceGrid.replaceChildren();
  serviceInventory.forEach((service) => serviceGrid.appendChild(serviceCard(service, gateway)));
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

function showWinlink(gateway) {
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
  showWinlinkReliability(winlink.reliability || {});
}

function showWinlinkReliability(reliability) {
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

function showOperatorStatus(status) {
  const badge = document.querySelector("#operator-auth-state");
  const login = document.querySelector("#operator-login-form");
  const setup = document.querySelector("#operator-setup-required");
  const actions = document.querySelector("#operator-actions");
  const cmsTest = document.querySelector('[data-operator-action="cms_test"]');
  const cmsGuard = document.querySelector("#operator-cms-guard");
  operatorCsrfToken = status.csrf_token || "";
  setup.hidden = status.configured;
  login.hidden = !status.configured || status.authenticated;
  actions.hidden = !status.authenticated;
  if (!status.configured) {
    badge.textContent = "Setup required";
    badge.className = "n0-status n0-status--advisory";
  } else if (status.authenticated) {
    badge.textContent = status.maintenance_mode ? "Maintenance" : "Administrator";
    badge.className = `n0-status ${status.maintenance_mode ? "n0-status--advisory" : "n0-status--operational"}`;
  } else {
    badge.textContent = "Locked";
    badge.className = "n0-status n0-status--unknown";
  }
  document.querySelector('[data-operator-action="restart"]').disabled = !status.authenticated;
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
      operatorMessage("Administrator session unlocked for 30 minutes.");
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
    operatorMessage(response.ok ? "Administrator session locked." : "Sign out failed.", !response.ok);
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
  refreshOperatorStatus().catch((error) => operatorMessage(error.message, true));
  window.setInterval(() => refreshOperatorStatus().catch(() => {}), 5000);
}

function showSystem(system) {
  document.querySelector("#metric-host").textContent = system.host.hostname;
  document.querySelector("#metric-platform").textContent = `${system.host.operating_system} ${system.host.kernel} · ${system.host.architecture}`;
  document.querySelector("#metric-uptime").textContent = formatUptime(system.resources.uptime_seconds);
  document.querySelector("#metric-load").textContent = `1 minute load: ${system.resources.load_1m ?? "unavailable"}`;
  document.querySelector("#metric-memory").textContent = formatBytes(system.resources.memory.available_bytes);
  document.querySelector("#metric-memory-total").textContent = `${formatBytes(system.resources.memory.total_bytes)} total`;
  document.querySelector("#metric-disk").textContent = formatBytes(system.resources.disk.free_bytes);
  document.querySelector("#metric-disk-total").textContent = `${formatBytes(system.resources.disk.total_bytes)} total`;
  document.querySelector("#metric-tools").textContent = system.tooling.ready ? "Ready" : "Incomplete";
  document.querySelector("#metric-tools-detail").textContent = system.tooling.ready ? "All declared base tools found" : `Missing: ${system.tooling.missing.join(", ")}`;

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
  document.querySelector("#metric-aprs").textContent = aprs.active ? "Active" : (aprs.configured ? "Stopped" : "Not configured");
  document.querySelector("#metric-aprs-detail").textContent = aprs.active ? "RTL-SDR receive-only path" : "Listener not running";
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
    station.last_report_utc ? `Last APRS report: ${station.last_report_utc}` : null,
    station.symbol ? `APRS symbol: ${station.symbol}` : null,
    station.comment || null,
    station.path ? `Path: ${station.path}` : null,
  ].filter(Boolean).forEach((text) => {
    const line = document.createElement("div");
    line.textContent = text;
    panel.appendChild(line);
  });
  const link = document.createElement("a");
  link.href = station.aprsfi_url;
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "Open on aprs.fi";
  panel.appendChild(link);
  return panel;
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
      aprsMap.fitBounds(localBounds.pad(0.35), {maxZoom: 17});
    } else {
      aprsLocalBounds = null;
      aprsMap.setView([mapCenter.latitude, mapCenter.longitude], 8);
    }
    message.hidden = true;
  } else {
    message.hidden = false;
    message.textContent = payload.message || payload.error || "No aprs.fi positions were found for recently heard callsigns.";
  }
  window.setTimeout(() => aprsMap.invalidateSize(), 0);
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
    if (!aprsMap) return;
    if (aprsLocalBounds?.isValid()) aprsMap.fitBounds(aprsLocalBounds.pad(0.35), {maxZoom: 17});
    else aprsMap.setView([aprsMapCenter.latitude, aprsMapCenter.longitude], 8);
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
    document.querySelector("#metric-voice-calls").textContent = "Disabled";
    document.querySelector("#metric-vhf-locks").textContent = "—";
    document.querySelector("#metric-uhf-locks").textContent = "—";
    document.querySelector("#metric-voice-calls-detail").textContent = "Enable Scanner in Application connections";
    document.querySelector("#metric-vhf-locks-detail").textContent = "Application disabled";
    document.querySelector("#metric-uhf-locks-detail").textContent = "Application disabled";
    return;
  }
  if (!application.reachable) {
    document.querySelector("#metric-voice-calls").textContent = "—";
    document.querySelector("#metric-vhf-locks").textContent = "—";
    document.querySelector("#metric-uhf-locks").textContent = "—";
    document.querySelector("#metric-voice-calls-detail").textContent = "Scanner API unavailable";
    document.querySelector("#metric-vhf-locks-detail").textContent = "Scanner API unavailable";
    document.querySelector("#metric-uhf-locks-detail").textContent = "Scanner API unavailable";
    return;
  }
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
  payload.applications.forEach((application) => {
    showApplicationStatus(application);
    populateApplicationForm(application);
    if (application.id === "scanner") showScannerReadiness(application);
  });
}

async function refreshApplications() {
  if (!trialDataAllowed()) return null;
  const response = await fetch("/api/applications", {cache: "no-store"});
  if (!response.ok) throw new Error("Application settings API response failed");
  const payload = await response.json();
  showApplications(payload);
  return payload;
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
    return;
  }
  const fields = status.observation.fields || {};
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
    const [healthResponse, stationResponse, servicesResponse, systemResponse, aprsResponse, weatherResponse, applicationsResponse, gatewayResponse] = await Promise.all([
      fetch("/api/health"),
      fetch("/api/station"),
      fetch("/api/services"),
      fetch("/api/system"),
      fetch("/api/aprs"),
      fetch("/api/weather"),
      fetch("/api/applications", {cache: "no-store"}),
      fetch("/api/gateway", {cache: "no-store"}),
    ]);
    if (![healthResponse, stationResponse, servicesResponse, systemResponse, aprsResponse, weatherResponse, applicationsResponse, gatewayResponse].every((response) => response.ok)) {
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

    badge.textContent = "Operational";
    badge.className = "n0-status n0-status--operational";
    showStation(station);
    document.querySelector("#version").textContent = health.version;

    const winlink = gateway.winlink || {};
    const identity = winlink.identity || {};
    const commissioning = Object.values(winlink.commissioning || {});
    const rmsOnAir = winlink.state === "operational"
      && Boolean(winlink.services?.linbpq?.active)
      && Boolean(winlink.services?.dire_wolf?.active)
      && Boolean(winlink.hardware?.ptt_serial_present)
      && commissioning.length > 0
      && commissioning.every(Boolean);
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
    showServices(gateway);
    showSystem(system);
    showAprs(aprs);
    loadAprsMap();
    showApplications(applications);
    showWeather(weather);
    showWinlink(gateway);
    operationalStarted = true;
    if (!operationalIntervals.length) {
      operationalIntervals = [
        window.setInterval(refreshWeather, 30000),
        window.setInterval(refreshWinlink, 30000),
        window.setInterval(() => refreshApplications().catch((error) => console.error("Application refresh failed", error)), 30000),
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
    window.requestAnimationFrame(() => aprsMap.invalidateSize());
    window.setTimeout(() => aprsMap.invalidateSize(), 220);
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

initWorkspaceNavigation();
start();
