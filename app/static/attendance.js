export function createAttendanceWorkspace({$, api, run, notice, cell, showPanel}) {
  let current = null;
  let correction = null;
  let offset = 0;
  let hasMore = false;
  let listSequence = 0;
  let detailSequence = 0;
  const createForm = $("new-session-form");
  const recordForm = $("attendance-record-form");
  const countForm = $("attendance-count-form");
  const closeForm = $("attendance-close-form");
  const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`; };
  function resetRecord() {
    correction = null;
    recordForm.reset();
    recordForm.elements.pris_no.readOnly = false;
    recordForm.elements.correction_reason.required = false;
    $("record-editor-title").textContent = "Record attendance";
    $("cancel-correction").hidden = true;
  }
  function clear() {
    current = null;
    detailSequence += 1;
    listSequence += 1;
    offset = 0;
    resetRecord();
    for (const id of ["attendance-session-rows", "attendance-record-rows", "eligible-student-rows"]) $(id).replaceChildren();
    for (const id of ["attendance-summary", "attendance-notes", "eligible-summary", "attendance-page"]) $(id).textContent = "";
    $("attendance-editor").hidden = true;
    $("new-session-panel").hidden = true;
    createForm.elements.class_name.replaceChildren();
    closeForm.elements.reason.required = false;
  }
  function pager() { $("attendance-previous").disabled = offset === 0; $("attendance-next").disabled = !hasMore; }
  async function list() {
    const sequence = ++listSequence;
    const fields = Object.fromEntries(new FormData($("attendance-search")));
    if (fields.date_from && fields.date_to && fields.date_from > fields.date_to) throw new Error("Session from must be on or before session to.");
    const query = new URLSearchParams(Object.entries(fields).filter(([, value]) => value.trim()));
    query.set("offset", String(offset)); query.set("limit", "26");
    const rows = await api(`/attendance/sessions?${query}`);
    if (sequence !== listSequence) return;
    $("attendance-session-rows").replaceChildren();
    for (const session of rows.slice(0,25)) {
      const row = document.createElement("tr");
      for (const value of [session.session_date, session.class_name, session.session_type, session.expected_count, session.status]) cell(row, value);
      const open = document.createElement("button"); open.textContent = "Open"; open.setAttribute("aria-label", `Open session ${session.id}`);
      open.addEventListener("click", () => run(open, () => load(session.id)));
      cell(row, "").append(open); $("attendance-session-rows").append(row);
    }
    if (!rows.length) { const row = document.createElement("tr"); cell(row,"No sessions match the filters.").colSpan = 6; $("attendance-session-rows").append(row); }
    hasMore = rows.length > 25;
    $("attendance-page").textContent = rows.length ? `Showing ${offset+1}–${offset+Math.min(rows.length,25)} sessions` : "No sessions";
    pager();
  }
  async function eligible() {
    if (!current || current.session.status !== "OPEN") return;
    const query = $("attendance-student-search").elements.q.value.trim().toLocaleLowerCase();
    const matches = current.roster.filter(student => !query || student.pris_no.toLocaleLowerCase().includes(query) || student.student_name.toLocaleLowerCase().includes(query));
    const students = matches.slice(0, 26);
    $("eligible-student-rows").replaceChildren();
    for (const student of students.slice(0,25)) {
      const row = document.createElement("tr"); cell(row, student.pris_no); cell(row, student.student_name);
      const select = document.createElement("button");
      const recorded = student.attendance_status !== null;
      select.textContent = recorded ? "Recorded" : "Select"; select.disabled = recorded;
      select.setAttribute("aria-label", `Select ${student.pris_no}`);
      select.addEventListener("click", () => { resetRecord(); recordForm.elements.pris_no.value = student.pris_no; recordForm.elements.attendance_status.focus(); });
      cell(row, "").append(select); $("eligible-student-rows").append(row);
    }
    const prefix = current.roster_snapshot_complete ? "Captured roster" : "Legacy partial roster";
    $("eligible-summary").textContent = `${prefix}: ${students.length > 25 ? "more than 25 students match; refine your search." : `${matches.length} students match.`}`;
  }
  async function load(id) {
    const sequence = ++detailSequence;
    const data = await api(`/attendance/sessions/${id}`);
    if (sequence !== detailSequence) return;
    current = data;
    resetRecord(); countForm.reset(); closeForm.reset();
    closeForm.elements.reason.required = false;
    $("new-session-panel").hidden = true; $("attendance-editor").hidden = false;
    $("attendance-editor-title").textContent = `${data.session.class_name} · ${data.session.session_date} · ${data.session.session_type}`;
    $("attendance-summary").textContent = `${data.session.status} · version ${data.session.version} · roster ${data.roster_count}${data.roster_snapshot_complete ? " captured" : " legacy partial"} · ${data.records.length}/${data.session.expected_count} recorded · ${data.missing} not entered · ${data.marked_missing} marked missing`;
    $("attendance-notes").textContent = data.session.notes ? `Notes: ${data.session.notes}` : "";
    $("attendance-write-panel").hidden = data.session.status !== "OPEN";
    countForm.elements.expected_count.value = data.session.expected_count;
    $("attendance-record-rows").replaceChildren(); $("eligible-student-rows").replaceChildren(); $("eligible-summary").textContent = "";
    for (const record of data.records) {
      const row = document.createElement("tr");
      for (const value of [record.pris_no, record.student_name, record.attendance_status, record.correction_reason ?? ""]) cell(row, value);
      const actionCell = cell(row, data.session.status === "CLOSED" ? "Closed" : "");
      if (data.session.status === "OPEN") {
        const edit = document.createElement("button"); edit.textContent = "Correct"; edit.setAttribute("aria-label", `Correct ${record.pris_no}`);
        edit.addEventListener("click", () => {
          resetRecord(); correction = record;
          recordForm.elements.pris_no.value = record.pris_no; recordForm.elements.pris_no.readOnly = true;
          recordForm.elements.attendance_status.value = record.attendance_status; recordForm.elements.correction_reason.required = true;
          $("record-editor-title").textContent = "Correct attendance"; $("cancel-correction").hidden = false;
          recordForm.elements.correction_reason.focus();
        }); actionCell.append(edit);
      }
      $("attendance-record-rows").append(row);
    }
    if (!data.records.length) { const row = document.createElement("tr"); cell(row, "No attendance has been recorded.").colSpan = 5; $("attendance-record-rows").append(row); }
  }
  async function show() { showPanel("attendance"); await list(); }
  $("new-attendance-session").addEventListener("click", () => run($("new-attendance-session"), async () => {
    const sequence = ++detailSequence; current = null;
    $("attendance-editor").hidden = true; $("new-session-panel").hidden = false;
    createForm.reset(); createForm.elements.session_date.value = today(); createForm.elements.class_name.replaceChildren();
    const data = await api("/reports/dashboard");
    if (sequence !== detailSequence) return;
    for (const [name, count] of Object.entries(data.students.by_class)) {
      const option = document.createElement("option"); option.value = name; option.textContent = `${name} (${count} active)`; option.dataset.count = String(count); createForm.elements.class_name.append(option);
    }
    createForm.elements.expected_count.value = createForm.elements.class_name.selectedOptions[0]?.dataset.count ?? "";
    if (!createForm.elements.class_name.options.length) notice("Create or activate student profiles before creating attendance sessions.");
  }));
  createForm.elements.class_name.addEventListener("change", () => { createForm.elements.expected_count.value = createForm.elements.class_name.selectedOptions[0]?.dataset.count ?? ""; });
  $("cancel-new-session").addEventListener("click", () => { detailSequence += 1; createForm.reset(); $("new-session-panel").hidden = true; });
  createForm.addEventListener("submit", event => { event.preventDefault(); run(createForm, async () => {
    const sequence = detailSequence; const fields = Object.fromEntries(new FormData(createForm)); fields.expected_count = Number(fields.expected_count); fields.notes = fields.notes.trim() || null;
    const saved = await api("/attendance/sessions", "POST", fields);
    if (sequence !== detailSequence) return;
    await load(saved.id); await list(); notice(`Created attendance session ${saved.id}.`);
  }); });
  $("reload-attendance").addEventListener("click", () => run($("reload-attendance"), () => load(current.session.id)));
  $("cancel-correction").addEventListener("click", resetRecord);
  $("attendance-student-search").addEventListener("submit", event => { event.preventDefault(); run(event.currentTarget, eligible); });
  recordForm.addEventListener("submit", event => { event.preventDefault(); run(recordForm, async () => {
    const sequence = detailSequence; const id = current.session.id;
    const fields = Object.fromEntries(new FormData(recordForm)); fields.expected_session_version = current.session.version;
    fields.correction_reason = fields.correction_reason.trim(); if (!fields.correction_reason) delete fields.correction_reason;
    if (correction) fields.expected_version = correction.version;
    await api(correction ? `/attendance/records/${correction.id}` : `/attendance/sessions/${id}/records`, correction ? "PATCH" : "POST", fields);
    if (sequence !== detailSequence) return;
    await load(id); await list(); notice("Attendance saved.");
  }); });
  countForm.addEventListener("submit", event => { event.preventDefault(); run(countForm, async () => {
    const sequence = detailSequence; const id = current.session.id;
    await api(`/attendance/sessions/${id}`, "PATCH", {expected_version: current.session.version, expected_count: Number(countForm.elements.expected_count.value), reason: countForm.elements.reason.value});
    if (sequence !== detailSequence) return;
    await load(id); await list(); notice("Expected count updated.");
  }); });
  closeForm.elements.allow_incomplete.addEventListener("change", () => { closeForm.elements.reason.required = closeForm.elements.allow_incomplete.checked; });
  closeForm.addEventListener("submit", event => { event.preventDefault(); run(closeForm, async () => {
    const sequence = detailSequence; const id = current.session.id; const allow = closeForm.elements.allow_incomplete.checked;
    const payload = {expected_version: current.session.version, allow_incomplete: allow}; if (allow) payload.reason = closeForm.elements.reason.value;
    await api(`/attendance/sessions/${id}/close`, "POST", payload);
    if (sequence !== detailSequence) return;
    await load(id); await list(); notice("Attendance session closed.");
  }); });
  $("attendance-search").addEventListener("submit", event => { event.preventDefault(); offset = 0; run(event.currentTarget, list); });
  async function movePage(button, direction) { await run(button, async () => { const previous = offset; offset = Math.max(0, offset+direction*25); try { await list(); } catch (error) { offset = previous; throw error; } }); pager(); }
  $("attendance-previous").addEventListener("click", () => movePage($("attendance-previous"), -1));
  $("attendance-next").addEventListener("click", () => movePage($("attendance-next"), 1));
  return {clear, show};
}
