const tenants = {
  guanlin: { name: "洛阳关林", attraction: "guanlin-main" },
  "tomb-museum": { name: "洛阳古墓博物馆", attraction: "tomb-museum-main" },
  "wanan-mountain": { name: "万安山", attraction: "wanan-canyon" },
};

const state = { tenant: "guanlin", attractions: [], slots: [], selectedSlot: null };
const $ = (selector) => document.querySelector(selector);

function headers(role = "visitor", extra = {}) {
  return { Authorization: `Bearer demo:${state.tenant}:${role}`, ...extra };
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `请求失败（${response.status}）`);
  return payload;
}

function showNotice(message, success = false) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.className = `notice${success ? " success" : ""}`;
  notice.hidden = false;
  window.clearTimeout(showNotice.timer);
  showNotice.timer = window.setTimeout(() => { notice.hidden = true; }, 4500);
}

function formatDate(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

function admissionLabel(mode) {
  return { paid: "购票预约", free: "免费预约", pass_or_paid: "年票或购票" }[mode] || mode;
}

async function checkService() {
  try {
    await api("/ready");
    $("#status-dot").className = "status-dot online";
    $("#service-status").textContent = "服务正常";
  } catch (_) {
    $("#status-dot").className = "status-dot offline";
    $("#service-status").textContent = "服务不可用";
  }
}

async function loadVisitor() {
  const attractionId = tenants[state.tenant].attraction;
  try {
    const [attractions, slots] = await Promise.all([
      api("/v1/attractions", { headers: headers() }),
      api(`/v1/slots?attraction_id=${encodeURIComponent(attractionId)}`, { headers: headers() }),
    ]);
    state.attractions = attractions;
    state.slots = slots;
    state.selectedSlot = null;
    renderAttraction();
    renderSlots();
  } catch (error) {
    showNotice(error.message);
  }
}

function renderAttraction() {
  const attraction = state.attractions.find((item) => item.id === tenants[state.tenant].attraction);
  const target = $("#attraction-summary");
  target.classList.remove("skeleton");
  if (!attraction) {
    target.innerHTML = "<h3>未找到景区资料</h3>";
    return;
  }
  target.innerHTML = `<h3>${attraction.name}</h3><p>${admissionLabel(attraction.admission_mode)} · ${attraction.requires_real_name ? "需要实名信息" : "无需实名信息"}</p>`;
}

function renderSlots() {
  const target = $("#slot-list");
  $("#selected-slot").value = "";
  $("#selected-slot-label").textContent = "请先选择左侧时段";
  if (!state.slots.length) {
    target.innerHTML = '<div class="empty">当前没有可预约时段</div>';
    return;
  }
  target.innerHTML = state.slots.map((slot) => `
    <button class="slot-card" type="button" data-slot-id="${slot.id}" ${slot.remaining_capacity === 0 ? "disabled" : ""}>
      <span><strong>${formatDate(slot.starts_at)}</strong><span>至 ${formatDate(slot.ends_at)}</span></span>
      <span class="capacity">余 ${slot.remaining_capacity}<small>总量 ${slot.capacity}</small></span>
    </button>`).join("");
  target.querySelectorAll(".slot-card").forEach((button) => {
    button.addEventListener("click", () => selectSlot(button.dataset.slotId));
  });
}

function selectSlot(slotId) {
  state.selectedSlot = state.slots.find((slot) => slot.id === slotId);
  $("#selected-slot").value = slotId;
  $("#selected-slot-label").textContent = `已选择：${formatDate(state.selectedSlot.starts_at)}`;
  document.querySelectorAll(".slot-card").forEach((card) => {
    card.classList.toggle("selected", card.dataset.slotId === slotId);
  });
}

async function createReservation(event) {
  event.preventDefault();
  if (!state.selectedSlot) return showNotice("请先选择预约时段");
  const button = event.submitter;
  button.disabled = true;
  try {
    const reservation = await api("/v1/reservations", {
      method: "POST",
      headers: headers("visitor", { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }),
      body: JSON.stringify({
        attraction_id: tenants[state.tenant].attraction,
        slot_id: state.selectedSlot.id,
        visitor_reference: $("#visitor-reference").value.trim(),
        quantity: Number($("#quantity").value),
      }),
    });
    renderReservation(reservation);
    $("#validation-code").value = reservation.validation_code;
    showNotice("预约成功，核验码已生成", true);
    await loadVisitor();
  } catch (error) {
    showNotice(error.message);
  } finally {
    button.disabled = false;
  }
}

function renderReservation(reservation) {
  const target = $("#reservation-result");
  target.hidden = false;
  target.innerHTML = `
    <p class="step-label">预约成功</p><h3>请保存入园核验码</h3>
    <code>${reservation.validation_code}</code>
    <p>预约编号：${reservation.id}<br>人数：${reservation.quantity} 人</p>
    <div class="result-actions">
      <button class="button" id="copy-code" type="button">复制核验码</button>
      <button class="button" id="cancel-reservation" type="button">取消预约</button>
    </div>`;
  $("#copy-code").addEventListener("click", async () => {
    await navigator.clipboard.writeText(reservation.validation_code);
    showNotice("核验码已复制", true);
  });
  $("#cancel-reservation").addEventListener("click", () => cancelReservation(reservation.id));
}

async function cancelReservation(id) {
  try {
    await api(`/v1/reservations/${id}/cancel`, { method: "POST", headers: headers() });
    $("#reservation-result").hidden = true;
    showNotice("预约已取消，名额已返还", true);
    await loadVisitor();
  } catch (error) {
    showNotice(error.message);
  }
}

async function loadAdmin() {
  try {
    const [metrics, slots] = await Promise.all([
      api("/v1/admin/metrics", { headers: headers("tenant_admin") }),
      api(`/v1/slots?attraction_id=${encodeURIComponent(tenants[state.tenant].attraction)}`, { headers: headers("tenant_admin") }),
    ]);
    renderMetrics(metrics);
    renderAdminSlots(slots);
  } catch (error) {
    showNotice(error.message);
  }
}

function renderMetrics(metrics) {
  const values = [
    ["有效预约", metrics.reservations_confirmed], ["取消预约", metrics.reservations_cancelled],
    ["已核验", metrics.admissions_validated], ["预约人数", metrics.seats_reserved],
  ];
  $("#metric-grid").innerHTML = values.map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join("");
}

function renderAdminSlots(slots) {
  $("#slot-count").textContent = `${slots.length} 个`;
  $("#admin-slot-list").innerHTML = slots.length
    ? slots.map((slot) => `<tr><td>${formatDate(slot.starts_at)}</td><td>${slot.capacity}</td><td>${slot.remaining_capacity}</td></tr>`).join("")
    : '<tr><td colspan="3">暂无时段</td></tr>';
}

async function createSlot(event) {
  event.preventDefault();
  const startsAt = new Date($("#slot-start").value);
  const endsAt = new Date($("#slot-end").value);
  if (endsAt <= startsAt) return showNotice("结束时间必须晚于开始时间");
  const button = event.submitter;
  button.disabled = true;
  try {
    await api("/v1/admin/slots", {
      method: "POST",
      headers: headers("tenant_admin", { "Content-Type": "application/json" }),
      body: JSON.stringify({
        attraction_id: tenants[state.tenant].attraction,
        starts_at: startsAt.toISOString(), ends_at: endsAt.toISOString(),
        capacity: Number($("#slot-capacity").value),
      }),
    });
    showNotice("新时段已创建", true);
    await Promise.all([loadAdmin(), loadVisitor()]);
  } catch (error) {
    showNotice(error.message);
  } finally {
    button.disabled = false;
  }
}

async function validateAdmission(event) {
  event.preventDefault();
  const result = $("#validation-result");
  result.className = "inline-result";
  result.textContent = "正在核验…";
  try {
    const validation = await api("/v1/validations", {
      method: "POST",
      headers: headers("validator", { "Content-Type": "application/json" }),
      body: JSON.stringify({ validation_code: $("#validation-code").value.trim() }),
    });
    result.className = "inline-result success";
    result.textContent = `核验通过 · ${new Date(validation.validated_at).toLocaleString("zh-CN")}`;
  } catch (error) {
    result.className = "inline-result error";
    result.textContent = error.message;
  }
}

function setDefaultTimes() {
  const start = new Date(Date.now() + 24 * 60 * 60 * 1000);
  start.setMinutes(0, 0, 0);
  const end = new Date(start.getTime() + 60 * 60 * 1000);
  const localValue = (date) => new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  $("#slot-start").value = localValue(start);
  $("#slot-end").value = localValue(end);
}

function switchPanel(name) {
  document.querySelectorAll(".role-tab").forEach((tab) => {
    const active = tab.dataset.panel === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".workspace").forEach((panel) => {
    const active = panel.id === `${name}-panel`;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });
  if (name === "admin") loadAdmin();
}

document.querySelectorAll(".role-tab").forEach((tab) => tab.addEventListener("click", () => switchPanel(tab.dataset.panel)));
$("#tenant-select").addEventListener("change", async (event) => {
  state.tenant = event.target.value;
  $("#reservation-result").hidden = true;
  $("#validation-result").textContent = "";
  await loadVisitor();
  if (!$("#admin-panel").hidden) await loadAdmin();
});
$("#refresh-slots").addEventListener("click", loadVisitor);
$("#refresh-admin").addEventListener("click", loadAdmin);
$("#reservation-form").addEventListener("submit", createReservation);
$("#slot-form").addEventListener("submit", createSlot);
$("#validation-form").addEventListener("submit", validateAdmission);

setDefaultTimes();
checkService();
loadVisitor();
