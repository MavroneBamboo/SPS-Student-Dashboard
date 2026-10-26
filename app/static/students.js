export function createStudentWorkspace({$, api, run, notice, cell, showPanel}) {
  let selected = null;
  let offset = 0;
  let listRequest = 0;
  let detailRequest = 0;
  let hasMore = false;
  const pageSize = 25;
  const form = $("profile-form");
  const today = () => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  };
  function close() {
    detailRequest += 1;
    selected = null;
    form.reset();
    $("profile-editor").hidden = true;
    $("profile-history").replaceChildren();
    $("profile-version").textContent = "";
  }
  function clear() {
    close();
    offset = 0;
    listRequest += 1;
    $("profile-rows").replaceChildren();
    $("profile-page").textContent = "";
  }
  async function list() {
    const request = ++listRequest;
    const fields = Object.fromEntries(new FormData($("profile-search")));
    const query = new URLSearchParams(Object.entries(fields).filter(([, value]) => value.trim()));
    query.set("offset", String(offset));
    query.set("limit", String(pageSize + 1));
    const profiles = await api(`/students?${query}`);
    if (request !== listRequest) return;
    $("profile-rows").replaceChildren();
    for (const profile of profiles.slice(0, pageSize)) {
      const row = document.createElement("tr");
      for (const value of [profile.pris_no, profile.name, profile.class_name, profile.category, profile.status]) cell(row, value);
      const open = document.createElement("button");
      open.textContent = "Open";
      open.setAttribute("aria-label", `Open ${profile.pris_no}`);
      open.addEventListener("click", () => run(open, () => load(profile.id)));
      cell(row, "").append(open);
      $("profile-rows").append(row);
    }
    if (!profiles.length) {
      const row = document.createElement("tr");
      cell(row, "No student profiles match the search.").colSpan = 6;
      $("profile-rows").append(row);
    }
    $("profile-page").textContent = profiles.length ? `Showing ${offset + 1}–${offset + Math.min(profiles.length, pageSize)} profiles` : "No results";
    hasMore = profiles.length > pageSize;
    pager();
  }
  function pager() {
    $("profiles-previous").disabled = offset === 0;
    $("profiles-next").disabled = !hasMore;
  }
  function render(profile) {
    form.reset();
    selected = profile;
    $("profile-editor").hidden = false;
    $("profile-editor-title").textContent = profile ? "Edit student profile" : "New student profile";
    $("profile-version").textContent = profile ? `Saved version ${profile.version}. Reload if another operator has changed this record.` : "Create a new student using a unique Pris No.";
    $("reload-profile").hidden = !profile;
    for (const key of ["pris_no", "name", "class_name", "category", "status", "status_effective", "date_of_birth"]) {
      form.elements[key].value = profile ? profile[key] ?? "" : key === "status" ? "ACTIVE" : key === "status_effective" ? today() : "";
    }
    form.elements.pris_no.readOnly = Boolean(profile);
    form.elements.status_effective.disabled = Boolean(profile);
    form.elements.status_effective.required = !profile;
    $("profile-history").replaceChildren();
    form.elements.name.focus();
  }
  async function load(id) {
    const request = ++detailRequest;
    const profile = await api(`/students/${id}`);
    const history = await api(`/students/${id}/status-history`);
    if (request !== detailRequest) return;
    render(profile);
    for (const entry of history) {
      const row = document.createElement("tr");
      for (const value of [entry.effective_date, entry.previous_status ?? "Initial record", entry.new_status, entry.changed_by]) cell(row, value);
      $("profile-history").append(row);
    }
  }
  async function show() {
    showPanel("profiles");
    await list();
  }
  $("new-student").addEventListener("click", () => { detailRequest += 1; render(null); notice(); });
  $("cancel-profile").addEventListener("click", close);
  $("reload-profile").addEventListener("click", () => run($("reload-profile"), () => load(selected.id)));
  form.elements.status.addEventListener("input", () => {
    const changed = !selected || form.elements.status.value.trim().toUpperCase() !== selected.status;
    form.elements.status_effective.disabled = !changed;
    form.elements.status_effective.required = changed;
    form.elements.status_effective.value = changed ? today() : selected?.status_effective ?? "";
  });
  $("profile-search").addEventListener("submit", (event) => {
    event.preventDefault();
    offset = 0;
    run(event.currentTarget, list);
  });
  async function movePage(button, direction) {
    await run(button, async () => {
      const previous = offset;
      offset = Math.max(0, offset + direction * pageSize);
      try { await list(); } catch (error) { offset = previous; throw error; }
    });
    pager();
  }
  $("profiles-previous").addEventListener("click", () => movePage($("profiles-previous"), -1));
  $("profiles-next").addEventListener("click", () => movePage($("profiles-next"), 1));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    run(form, async () => {
      const request = detailRequest;
      const fields = Object.fromEntries(new FormData(form));
      for (const key of Object.keys(fields)) fields[key] = fields[key].trim();
      fields.status = fields.status.toUpperCase();
      fields.date_of_birth = fields.date_of_birth || null;
      let payload = fields;
      if (selected) {
        payload = {expected_version: selected.version};
        for (const key of ["name", "class_name", "category", "status", "status_effective", "date_of_birth"]) {
          if (key in fields && fields[key] !== (selected[key] ?? null)) payload[key] = fields[key];
        }
        if (Object.keys(payload).length === 1) { notice("No profile changes to save."); return; }
      }
      const saved = await api(selected ? `/students/${selected.id}` : "/students", selected ? "PATCH" : "POST", payload);
      if (request !== detailRequest) return;
      await load(saved.id);
      await list();
      notice(`Saved student ${saved.pris_no}.`);
    });
  });
  return {clear, show};
}
