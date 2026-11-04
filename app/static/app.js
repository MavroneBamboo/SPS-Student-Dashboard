import {createStudentWorkspace} from "./students.js";
import {createAttendanceWorkspace} from "./attendance.js";
import {createTimetableWorkspace} from "./timetable.js";
import {createReferenceDataWorkspace} from "./reference-data.js";

const $ = (id) => document.getElementById(id);
const roles = ["Superuser", "IT Administrator", "Operator", "Executive"];
let token = null;
let identity = null;
let expiryTimer = null;
let epoch = 0;
let requests = new AbortController();
let dashboardRequest = 0;
let referenceData = null;

function notice(message = "") { $("notice").textContent = message; }
function clearData() {
  attendance.clear();
  timetable.clear();
  students.clear();
  referenceData?.clear();
  for (const id of ["user-rows", "metrics", "class-counts", "category-counts", "attendance-trend"]) $(id).replaceChildren();
  $("identity").textContent = "";
  $("dashboard-freshness").textContent = "";
  for (const form of document.forms) form.reset();
  $("reset-user-form").hidden = true;
}
function signedOut(message = "") {
  epoch += 1;
  requests.abort();
  requests = new AbortController();
  clearTimeout(expiryTimer);
  token = null;
  identity = null;
  clearData();
  $("workspace").hidden = true;
  $("password-screen").hidden = true;
  $("signin").hidden = false;
  notice(message);
  $("login-form").elements.username.focus();
}

async function explicitSignOut() {
  const oldToken = token;
  signedOut("Signed out.");
  if (!oldToken) return;
  try {
    const response = await fetch("/api/v1/auth/logout", {
      method: "POST", headers: {Authorization: `Bearer ${oldToken}`}, cache: "no-store",
      credentials: "omit", keepalive: true, signal: AbortSignal.timeout(5000),
    });
    if (!response.ok && response.status !== 401 && token === null) notice("Signed out here. Server sign-out could not be confirmed.");
  } catch {
    if (token === null) notice("Signed out here. Server sign-out could not be confirmed.");
  }
}

function validationMessage(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((row) => `${row.loc?.slice(1).join(".") || "Input"}: ${row.msg}`).join("\n");
  return "The request could not be completed. Review your input and try again.";
}

async function api(path, method = "GET", body) {
  const started = epoch;
  const headers = {Accept: "application/json"};
  if (token) headers.Authorization = `Bearer ${token}`;
  const rawFile = typeof Blob !== "undefined" && body instanceof Blob;
  if (rawFile) headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  else if (body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method, headers, body: body === undefined ? undefined : rawFile ? body : JSON.stringify(body),
      cache: "no-store", credentials: "omit", signal: requests.signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new Error("Unable to reach the server. Check your connection and try again.");
  }
  const data = await response.json().catch(() => ({detail: "The server could not complete the request. Try again."}));
  if (started !== epoch) throw new DOMException("Session changed", "AbortError");
  if (response.status === 401 && token) {
    signedOut("Your session ended. Sign in again.");
    throw new DOMException("Session ended", "AbortError");
  }
  if (response.status === 403 && token && data.detail === "Insufficient permissions") {
    signedOut("Your access changed. Sign in again.");
    throw new DOMException("Access changed", "AbortError");
  }
  if (!response.ok) throw new Error(validationMessage(data.detail));
  return data;
}

async function downloadXlsx(path) {
  const started = epoch;
  const activeToken = token;
  let response;
  try {
    response = await fetch(`/api/v1${path}`, {
      headers: {Authorization: `Bearer ${activeToken}`},
      cache: "no-store",
      credentials: "omit",
      signal: requests.signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new Error("Unable to reach the server. Check your connection and try again.");
  }
  if (started !== epoch || activeToken !== token) throw new DOMException("Session changed", "AbortError");
  if (response.status === 401 && token) {
    signedOut("Your session ended. Sign in again.");
    throw new DOMException("Session ended", "AbortError");
  }
  if (response.status === 403 && token) {
    signedOut("Your access changed. Sign in again.");
    throw new DOMException("Access changed", "AbortError");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Could not generate the timetable report.");
  }
  const blob = await response.blob();
  if (started !== epoch || activeToken !== token) throw new DOMException("Session changed", "AbortError");
  const filename = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)"?/i)?.[1] || "timetable-report.xlsx";
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  notice("Timetable report workbook downloaded.");
}

async function run(control, action) {
  const controls = control.matches("form") ? [...control.querySelectorAll("button")] : [control];
  controls.forEach((element) => { element.disabled = true; });
  notice();
  try { await action(); }
  catch (error) { if (error.name !== "AbortError") notice(error.message); }
  finally { controls.forEach((element) => { element.disabled = false; }); }
}

async function acceptSession(session) {
  token = session.access_token;
  clearTimeout(expiryTimer);
  expiryTimer = setTimeout(() => signedOut("Your session expired. Sign in again."), session.expires_in * 1000);
  identity = await api("/auth/me");
  $("signin").hidden = true;
  $("password-form").reset();
  if (identity.must_change_password) {
    $("workspace").hidden = true;
    $("password-screen").hidden = false;
    $("password-help").textContent = "You must change your temporary password before accessing the workspace. Use at least 12 characters.";
    $("password-form").elements.current_password.focus();
    return;
  }
  $("password-screen").hidden = true;
  $("workspace").hidden = false;
  $("identity").textContent = `${identity.username} · ${identity.role}`;
  $("users-nav").hidden = !["Superuser", "IT Administrator"].includes(identity.role);
  $("dashboard-nav").hidden = identity.role === "IT Administrator";
  $("profiles-nav").hidden = !["Operator", "Superuser"].includes(identity.role);
  $("attendance-nav").hidden = !["Operator", "Superuser"].includes(identity.role);
  $("timetable-nav").hidden = false;
  $("reference-data-nav").hidden = !["IT Administrator", "Superuser"].includes(identity.role);
  if (identity.role === "IT Administrator") await showUsers();
  else await showDashboard();
}

function cell(row, value) {
  const element = document.createElement("td");
  element.textContent = String(value);
  row.append(element);
  return element;
}
function showPanel(name) {
  $("dashboard-panel").hidden = name !== "dashboard";
  $("users-panel").hidden = name !== "users";
  $("profiles-panel").hidden = name !== "profiles";
  $("attendance-panel").hidden = name !== "attendance";
  $("timetable-panel").hidden = name !== "timetable";
  $("reference-data-panel").hidden = name !== "reference-data";
  const navIds = {users: "users-nav", dashboard: "dashboard-nav", profiles: "profiles-nav", attendance: "attendance-nav", timetable: "timetable-nav", "reference-data": "reference-data-nav"};
  for (const [panel, id] of Object.entries(navIds)) {
    const button = $(id);
    const active = panel === name;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  $("workspace-title").textContent = {users: "Account setup", dashboard: "Dashboard", profiles: "Student profiles", attendance: "Attendance", timetable: "Timetable / Schedule", "reference-data": "Reference data"}[name];
}
function breakdown(id, values) {
  const list = document.createElement("dl");
  for (const [label, count] of Object.entries(values)) {
    const term = document.createElement("dt");
    const value = document.createElement("dd");
    term.textContent = label || "Unassigned";
    value.textContent = String(count);
    list.append(term, value);
  }
  if (!list.children.length) list.textContent = "No active students match the filter.";
  $(id).replaceChildren(list);
}
async function showDashboard() {
  const requestId = ++dashboardRequest;
  showPanel("dashboard");
  if (!$("monthly-attendance-report").elements.month.value) $("monthly-attendance-report").elements.month.value = new Date().toISOString().slice(0, 7);
  const fields = Object.fromEntries(new FormData($("dashboard-filter")));
  if (fields.date_from && fields.date_to && fields.date_from > fields.date_to) throw new Error("Attendance from must be on or before attendance to.");
  const query = new URLSearchParams(Object.entries(fields).filter(([, value]) => value));
  const data = await api(`/reports/dashboard?${query}`);
  if (requestId !== dashboardRequest) return;
  $("metrics").replaceChildren();
  for (const [label, value] of [
    ["Active students", data.students.active],
    ["Attendance", data.attendance.rate === null ? "No sessions" : `${data.attendance.rate}%`],
    ["Missing attendance records", data.attendance.missing],
    ["Sessions", data.attendance.sessions],
  ]) {
    const card = document.createElement("div");
    card.className = "metric";
    const title = document.createElement("span");
    const number = document.createElement("strong");
    title.textContent = label;
    number.textContent = String(value);
    card.append(title, number);
    $("metrics").append(card);
  }
  breakdown("class-counts", data.students.by_class);
  breakdown("category-counts", data.students.by_category);
  $("attendance-trend").replaceChildren();
  for (const entry of data.attendance.trend) {
    const row = document.createElement("tr");
    for (const value of [entry.date, entry.class, entry.session, entry.present_or_late, entry.recorded, entry.expected, `${entry.rate}%`]) cell(row, value);
    $("attendance-trend").append(row);
  }
  if (!data.attendance.trend.length) {
    const row = document.createElement("tr");
    cell(row, "No attendance sessions match the filters.").colSpan = 7;
    $("attendance-trend").append(row);
  }
  $("dashboard-freshness").textContent = `Committed data refreshed ${new Date(data.refreshed_at).toLocaleString()}`;
}
const monthlyReportForm = $("monthly-attendance-report");
monthlyReportForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  run(form, async () => {
    const started = epoch;
    const activeToken = token;
    const fields = Object.fromEntries(new FormData(form));
    const query = new URLSearchParams(fields);
    const response = await fetch(`/api/v1/reports/attendance/monthly.xlsx?${query}`, {
      headers: {Authorization: `Bearer ${activeToken}`},
      cache: "no-store",
      credentials: "omit",
      signal: requests.signal,
    });
    if (started !== epoch) throw new DOMException("Session changed", "AbortError");
    if (response.status === 401 && token) {
      signedOut("Your session ended. Sign in again.");
      throw new DOMException("Session ended", "AbortError");
    }
    if (response.status === 403 && token) {
      signedOut("Your access changed. Sign in again.");
      throw new DOMException("Access changed", "AbortError");
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || "Could not generate the monthly attendance register.");
    }
    const blob = await response.blob();
    if (started !== epoch || activeToken !== token) throw new DOMException("Session changed", "AbortError");
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `attendance-${fields.month}-${fields.class_name.trim().replace(/[^\p{L}\p{N}_-]+/gu, "_")}.xlsx`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
});
async function showUsers() {
  if (!["Superuser", "IT Administrator"].includes(identity.role)) throw new Error("User administration is not available for this role.");
  showPanel("users");
  const users = await api("/users");
  [...$("create-user-form").elements.role.options].find((option) => option.value === "Superuser").hidden = identity.role !== "Superuser";
  $("user-rows").replaceChildren();
  for (const user of users) {
    const row = document.createElement("tr");
    cell(row, user.username);
    const role = document.createElement("select");
    role.setAttribute("aria-label", `Role for ${user.username}`);
    for (const value of roles.filter((value) => identity.role === "Superuser" || value !== "Superuser")) {
      const option = document.createElement("option");
      option.textContent = value;
      option.value = value;
      option.selected = value === user.role;
      role.append(option);
    }
    cell(row, "").append(role);
    const active = document.createElement("input");
    active.type = "checkbox";
    active.checked = user.is_active;
    active.setAttribute("aria-label", `Active for ${user.username}`);
    cell(row, "").append(active);
    cell(row, user.must_change_password ? "Required" : "Completed");
    const save = document.createElement("button");
    save.textContent = "Save";
    save.setAttribute("aria-label", `Save ${user.username}`);
    save.addEventListener("click", () => run(save, async () => {
      await api(`/users/${user.id}`, "PATCH", {role: role.value, is_active: active.checked});
      identity = await api("/auth/me");
      if (!["Superuser", "IT Administrator"].includes(identity.role)) {
        signedOut("Your role changed. Sign in again to load your workspace.");
        return;
      }
      await showUsers();
      notice(`Updated ${user.username}.`);
    }));
    const actions = cell(row, "");
    actions.append(save);
    if (user.id !== Number(identity.sub)) {
      const reset = document.createElement("button");
      reset.className = "secondary";
      reset.textContent = "Reset password";
      reset.setAttribute("aria-label", `Reset password for ${user.username}`);
      reset.addEventListener("click", () => {
        const form = $("reset-user-form");
        form.reset();
        form.elements.user_id.value = user.id;
        $("reset-user-title").textContent = `Reset password for ${user.username}`;
        form.hidden = false;
        form.elements.temporary_password.focus();
      });
      actions.append(reset);
    }
    $("user-rows").append(row);
  }
}

const students = createStudentWorkspace({$, api, run, notice, cell, showPanel});
const attendance = createAttendanceWorkspace({$, api, run, notice, cell, showPanel});
const timetable = createTimetableWorkspace({$, api, run, notice, cell, showPanel, role: () => identity?.role, downloadXlsx});
referenceData = createReferenceDataWorkspace({$, api, run, notice, cell, showPanel, role: () => identity?.role});
$("profiles-nav").addEventListener("click", () => run($("profiles-nav"), students.show));
$("attendance-nav").addEventListener("click", () => run($("attendance-nav"), attendance.show));
$("timetable-nav").addEventListener("click", () => run($("timetable-nav"), timetable.show));
$("reference-data-nav").addEventListener("click", () => run($("reference-data-nav"), referenceData.show));

$("login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run(event.currentTarget, async () => {
    const payload = Object.fromEntries(new FormData($("login-form")));
    try { await acceptSession(await api("/auth/login", "POST", payload)); }
    finally { $("login-form").elements.password.value = ""; }
  });
});
$("password-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run(event.currentTarget, async () => {
    const payload = Object.fromEntries(new FormData($("password-form")));
    if (payload.new_password !== payload.confirmation) throw new Error("The new passwords do not match.");
    delete payload.confirmation;
    try {
      await acceptSession(await api("/auth/change-password", "POST", payload));
      notice("Password changed.");
    } finally { $("password-form").reset(); }
  });
});
$("create-user-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run(event.currentTarget, async () => {
    const payload = Object.fromEntries(new FormData($("create-user-form")));
    try {
      await api("/users", "POST", payload);
      $("create-user-form").reset();
      await showUsers();
      notice(`Created ${payload.username}. Supply the temporary password through your approved secure channel.`);
    } finally { $("create-user-form").elements.temporary_password.value = ""; }
  });
});
$("reset-user-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run(event.currentTarget, async () => {
    const form = $("reset-user-form");
    const userId = form.elements.user_id.value;
    const temporaryPassword = form.elements.temporary_password.value;
    try {
      await api(`/users/${userId}/reset-password`, "POST", {temporary_password: temporaryPassword});
      form.reset();
      form.hidden = true;
      await showUsers();
      notice("Temporary password set. Supply it through your approved secure channel.");
    } finally { form.elements.temporary_password.value = ""; }
  });
});
$("cancel-reset-user").addEventListener("click", () => { $("reset-user-form").reset(); $("reset-user-form").hidden = true; });
$("dashboard-filter").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, showDashboard); });
for (const id of ["dashboard-nav", "refresh-dashboard"]) $(id).addEventListener("click", () => run($(id), showDashboard));
for (const id of ["users-nav", "refresh-users"]) $(id).addEventListener("click", () => run($(id), showUsers));
for (const id of ["signout", "password-cancel"]) $(id).addEventListener("click", explicitSignOut);
$("change-password").addEventListener("click", () => {
  $("workspace").hidden = true;
  $("password-screen").hidden = false;
  $("password-help").textContent = "Choose a new password with at least 12 characters. Signing out cancels this action.";
  notice();
  $("password-form").elements.current_password.focus();
});
window.addEventListener("pagehide", () => signedOut());
signedOut();
