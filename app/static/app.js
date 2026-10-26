import {createStudentWorkspace} from "./students.js";

const $ = (id) => document.getElementById(id);
const roles = ["Superuser", "IT Administrator", "Operator", "Executive"];
let token = null;
let identity = null;
let expiryTimer = null;
let epoch = 0;
let requests = new AbortController();
let dashboardRequest = 0;

function notice(message = "") { $("notice").textContent = message; }
function clearData() {
  students.clear();
  for (const id of ["user-rows", "metrics", "class-counts", "category-counts", "attendance-trend"]) $(id).replaceChildren();
  $("identity").textContent = "";
  $("dashboard-freshness").textContent = "";
  for (const form of document.forms) form.reset();
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

function validationMessage(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((row) => `${row.loc?.slice(1).join(".") || "Input"}: ${row.msg}`).join("\n");
  return "The request could not be completed. Review your input and try again.";
}

async function api(path, method = "GET", body) {
  const started = epoch;
  const headers = {Accept: "application/json"};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
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
  $("users-nav").hidden = identity.role !== "Superuser";
  $("dashboard-nav").hidden = identity.role === "Superuser";
  $("profiles-nav").hidden = identity.role !== "Operator";
  if (identity.role === "Superuser") await showUsers();
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
  $("workspace-title").textContent = {users: "Account setup", dashboard: "Dashboard", profiles: "Student profiles"}[name];
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
async function showUsers() {
  if (identity.role !== "Superuser") throw new Error("User administration is not available for this role.");
  showPanel("users");
  const users = await api("/users");
  $("user-rows").replaceChildren();
  for (const user of users) {
    const row = document.createElement("tr");
    cell(row, user.username);
    const role = document.createElement("select");
    role.setAttribute("aria-label", `Role for ${user.username}`);
    for (const value of roles) {
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
      if (identity.role !== "Superuser") {
        signedOut("Your role changed. Sign in again to load your workspace.");
        return;
      }
      await showUsers();
      notice(`Updated ${user.username}.`);
    }));
    cell(row, "").append(save);
    $("user-rows").append(row);
  }
}

const students = createStudentWorkspace({$, api, run, notice, cell, showPanel});
$("profiles-nav").addEventListener("click", () => run($("profiles-nav"), students.show));

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
$("dashboard-filter").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, showDashboard); });
for (const id of ["dashboard-nav", "refresh-dashboard"]) $(id).addEventListener("click", () => run($(id), showDashboard));
for (const id of ["users-nav", "refresh-users"]) $(id).addEventListener("click", () => run($(id), showUsers));
for (const id of ["signout", "password-cancel"]) $(id).addEventListener("click", () => signedOut("Signed out."));
$("change-password").addEventListener("click", () => {
  $("workspace").hidden = true;
  $("password-screen").hidden = false;
  $("password-help").textContent = "Choose a new password with at least 12 characters. Signing out cancels this action.";
  notice();
  $("password-form").elements.current_password.focus();
});
window.addEventListener("pagehide", () => signedOut());
signedOut();
