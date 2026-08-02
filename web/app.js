const badge = document.querySelector("#system-badge");
const interlock = document.querySelector("#interlock");
const serviceGrid = document.querySelector("#service-grid");

function serviceCard(service) {
  const card = document.createElement("article");
  card.className = "service-card";
  card.innerHTML = `
    <span class="phase">Phase ${service.phase}</span>
    <h3>${service.name}</h3>
    <p>${service.hardware}<br>${service.rf_role}</p>
    <span class="state">${service.state}</span>`;
  return card;
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

function showAprs(aprs) {
  document.querySelector("#metric-aprs").textContent = aprs.configured ? "Configured" : "Not configured";
  document.querySelector("#metric-aprs-detail").textContent = "RTL-SDR receive-only path";
  document.querySelector("#metric-aprs-packets").textContent = String(aprs.packet_count ?? 0);
  document.querySelector("#metric-aprs-packets-detail").textContent = aprs.packet_count ? "Decoded frames" : "No decoded frames yet";
}

async function start() {
  try {
    const [healthResponse, stationResponse, servicesResponse, systemResponse, aprsResponse] = await Promise.all([
      fetch("/api/health"),
      fetch("/api/station"),
      fetch("/api/services"),
      fetch("/api/system"),
      fetch("/api/aprs"),
    ]);
    if (![healthResponse, stationResponse, servicesResponse, systemResponse, aprsResponse].every((response) => response.ok)) {
      throw new Error("API response failed");
    }
    const health = await healthResponse.json();
    const station = await stationResponse.json();
    const inventory = await servicesResponse.json();
    const system = await systemResponse.json();
    const aprs = await aprsResponse.json();

    badge.textContent = "Foundation online";
    badge.className = "badge ok";
    document.querySelector("#site-name").textContent = station.station.site_label;
    document.querySelector("#version").textContent = health.version;

    const reasons = health.transmit.reasons.join("; ");
    interlock.querySelector("strong").textContent = health.transmit.ready ? "Transmit ready" : "Transmit locked";
    interlock.querySelector("small").textContent = reasons || "All configured safety gates passed";
    inventory.services.forEach((service) => serviceGrid.appendChild(serviceCard(service)));
    showSystem(system);
    showAprs(aprs);
  } catch (error) {
    badge.textContent = "Service unavailable";
    console.error(error);
  }
}

start();
