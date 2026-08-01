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

async function start() {
  try {
    const [healthResponse, stationResponse, servicesResponse] = await Promise.all([
      fetch("/api/health"),
      fetch("/api/station"),
      fetch("/api/services"),
    ]);
    if (![healthResponse, stationResponse, servicesResponse].every((response) => response.ok)) {
      throw new Error("API response failed");
    }
    const health = await healthResponse.json();
    const station = await stationResponse.json();
    const inventory = await servicesResponse.json();

    badge.textContent = "Foundation online";
    badge.className = "badge ok";
    document.querySelector("#site-name").textContent = station.station.site_label;
    document.querySelector("#version").textContent = health.version;

    const reasons = health.transmit.reasons.join("; ");
    interlock.querySelector("strong").textContent = health.transmit.ready ? "Transmit ready" : "Transmit locked";
    interlock.querySelector("small").textContent = reasons || "All configured safety gates passed";
    inventory.services.forEach((service) => serviceGrid.appendChild(serviceCard(service)));
  } catch (error) {
    badge.textContent = "Service unavailable";
    console.error(error);
  }
}

start();
