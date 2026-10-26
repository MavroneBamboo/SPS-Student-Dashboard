const weekdays = ["MON", "TUE", "WED", "THU", "FRI"];
const periods = ["P1", "P2", "LUNCH", "P3", "P4"];
const periodLabels = {P1: "Period 1", P2: "Period 2", LUNCH: "Lunch", P3: "Period 3", P4: "Period 4"};

export function createTimetableWorkspace({$, api, run, notice, cell, showPanel, role}) {
  let versions = [];
  let classes = [];
  let current = null;
  let pageOffset = 0;
  let detailSequence = 0;
  const currentRole = () => typeof role === "function" ? role() : role;
  const canEdit = () => ["Operator", "IT Administrator"].includes(currentRole());
  const canApprove = () => currentRole() === "IT Administrator";
  const placementForm = $("timetable-placement-form");

  function clear() {
    versions = [];
    classes = [];
    current = null;
    detailSequence += 1;
    pageOffset = 0;
    for (const id of ["timetable-version-rows", "timetable-grid", "timetable-pending"]) $(id).replaceChildren();
    $("timetable-editor").hidden = true;
    $("timetable-create-form").hidden = true;
    $("new-timetable").hidden = true;
    placementForm.reset();
    placementForm.hidden = true;
    $("timetable-generation-summary").textContent = "";
    for (const id of ["teacher-availability", "timetable-teacher-rows", "timetable-subject-rows", "timetable-class-rows", "timetable-period-rows"]) {
      const element = $(id);
      if (element) element.replaceChildren();
    }
  }

  function editableDraft() {
    return canEdit() && current?.status === "DRAFT";
  }

  function renderVersions() {
    const rows = $("timetable-version-rows");
    rows.replaceChildren();
    for (const version of versions) {
      const row = document.createElement("tr");
      for (const value of [version.name, version.academic_year, version.week_start, version.status, `r${version.revision}`]) cell(row, value);
      const open = document.createElement("button");
      open.textContent = "Open";
      open.setAttribute("aria-label", `Open timetable ${version.name}`);
      open.addEventListener("click", () => run(open, () => load(version.id)));
      cell(row, "").append(open);
      rows.append(row);
    }
    if (!versions.length) {
      const row = document.createElement("tr");
      cell(row, "No saved timetables are available.").colSpan = 6;
      rows.append(row);
    }
  }

  async function refresh() {
    const data = await Promise.all([
      api("/timetable/versions?limit=100"),
      api("/timetable/classes"),
    ]);
    versions = data[0];
    classes = data[1].filter((row) => row.is_active);
    renderVersions();
    const createForm = $("timetable-create-form");
    $("new-timetable").hidden = !canEdit();
    const select = createForm.elements.class_ids;
    select.replaceChildren();
    for (const item of classes) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = `${item.code} · ${item.name}`;
      select.append(option);
    }
    $("timetable-setup").hidden = currentRole() !== "IT Administrator";
    $("timetable-lesson-form").hidden = !canEdit();
    if (canEdit()) await refreshSetup();
  }

  function fillSelect(select, rows, label) {
    const previous = select.value;
    select.replaceChildren();
    for (const row of rows) {
      const option = document.createElement("option");
      option.value = row.id;
      option.textContent = label(row);
      select.append(option);
    }
    if (rows.some((row) => String(row.id) === previous)) select.value = previous;
  }

  function renderAvailability() {
    const fieldset = $("teacher-availability");
    if (fieldset.childElementCount) return;
    for (const day of weekdays) {
      const row = document.createElement("div");
      row.className = "availability-row";
      const title = document.createElement("strong");
      title.textContent = day;
      row.append(title);
      for (const period of periods.filter((item) => item !== "LUNCH")) {
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = true;
        input.value = period;
        input.dataset.day = day;
        input.setAttribute("aria-label", `${day} ${period}`);
        label.append(input, document.createTextNode(period));
        row.append(label);
      }
      fieldset.append(row);
    }
  }

  async function refreshSetup() {
    const [teachers, subjects, instructionalClasses, clusters, periodRows] = await Promise.all([
      api("/timetable/teachers"), api("/timetable/subjects"), api("/timetable/classes"), api("/timetable/clusters"), api("/timetable/periods"),
    ]);
    const activeTeachers = teachers.filter((row) => row.is_active);
    const activeSubjects = subjects.filter((row) => row.is_active);
    const activeClasses = instructionalClasses.filter((row) => row.is_active);
    const activeClusters = clusters.filter((row) => row.is_active);
    lastClusters = activeClusters;
    fillSelect($("timetable-lesson-form").elements.instructional_class_id, activeClasses, (row) => `${row.code} · ${row.name}`);
    fillSelect($("timetable-lesson-form").elements.teacher_id, activeTeachers, (row) => `${row.short_code} · ${row.full_name}`);
    fillSelect($("timetable-lesson-form").elements.subject_id, activeSubjects, (row) => `${row.code} · ${row.name}`);
    fillSelect($("timetable-cluster-member-form").elements.cluster_id, activeClusters, (row) => `${row.code} · ${row.name}`);
    fillSelect($("timetable-cluster-member-form").elements.instructional_class_id, activeClasses, (row) => `${row.code} · ${row.name}`);
    fillSelect($("timetable-period-form").elements.target_id, activeClasses, (row) => `${row.code} · ${row.name}`);
    fillSelect($("timetable-rule-form").elements.target_id, activeClasses, (row) => `${row.code} · ${row.name}`);
    for (const [id, values] of [["timetable-teacher-rows", teachers], ["timetable-subject-rows", subjects], ["timetable-class-rows", instructionalClasses]]) {
      const body = $(id);
      body.replaceChildren();
      for (const item of values) {
        const row = document.createElement("tr");
        const code = item.short_code || item.code;
        for (const value of [code, item.full_name || item.name, item.is_active ? "Active" : "Inactive"]) cell(row, value);
        body.append(row);
      }
    }
    $("timetable-resource-summary").textContent = `${teachers.length} teacher profiles · ${subjects.length} subjects · ${instructionalClasses.length} classes · ${clusters.length} clusters`;
    renderAvailability();
    const periodTable = $("timetable-period-rows");
    periodTable?.replaceChildren();
    if (periodTable) for (const period of periodRows) {
      const row = document.createElement("tr");
      for (const value of [period.scope, period.target_id ?? "Default", period.slot_code, period.label, period.starts_at ?? "", period.ends_at ?? ""]) cell(row, value);
      periodTable.append(row);
    }
    updatePeriodTargets();
    updateRuleTargets();
  }

  function updatePeriodTargets() {
    const form = $("timetable-period-form");
    const rows = form.elements.scope.value === "CLASS" ? classes : [];
    const targets = form.elements.scope.value === "CLASS" ? rows : lastClusters;
    fillSelect(form.elements.target_id, targets, (row) => `${row.code} · ${row.name}`);
    form.elements.target_id.disabled = form.elements.scope.value === "DEFAULT";
  }

  let lastClusters = [];
  function updateRuleTargets() {
    const form = $("timetable-rule-form");
    const targets = form.elements.target_type.value === "CLASS" ? classes : lastClusters;
    fillSelect(form.elements.target_id, targets, (row) => `${row.code} · ${row.name}`);
  }

  function availabilityPayload() {
    return Object.fromEntries(weekdays.map((day) => [
      day,
      [...$("teacher-availability").querySelectorAll(`input[data-day="${day}"]:checked`)].map((input) => input.value),
    ]));
  }

  function submitJSON(formId, path, payloadFor, success) {
    const form = $(formId);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      run(form, async () => {
        const payload = payloadFor(form);
        await api(path, "POST", payload);
        form.reset();
        if (formId === "timetable-teacher-form") {
          for (const input of $("teacher-availability").querySelectorAll('input[type="checkbox"]')) input.checked = true;
        }
        await refresh();
        notice(success);
      });
    });
  }

  submitJSON("timetable-teacher-form", "/timetable/teachers", (form) => ({
    short_code: form.elements.short_code.value,
    full_name: form.elements.full_name.value,
    is_adjunct: form.elements.is_adjunct.checked,
    availability: availabilityPayload(),
  }), "Teacher profile created.");
  submitJSON("timetable-subject-form", "/timetable/subjects", (form) => ({code: form.elements.code.value, name: form.elements.name.value}), "Subject created.");
  submitJSON("timetable-class-form", "/timetable/classes", (form) => ({code: form.elements.code.value, name: form.elements.name.value}), "Instructional class created.");
  submitJSON("timetable-cluster-form", "/timetable/clusters", (form) => ({code: form.elements.code.value, name: form.elements.name.value}), "Class cluster created.");
  $("timetable-cluster-member-form").addEventListener("submit", (event) => {
    event.preventDefault();
    run(event.currentTarget, async () => {
      const form = event.currentTarget;
      const clusterId = Number(form.elements.cluster_id.value);
      await api(`/timetable/clusters/${clusterId}/classes`, "POST", {instructional_class_id: Number(form.elements.instructional_class_id.value)});
      await refresh();
      notice("Class added to cluster.");
    });
  });
  submitJSON("timetable-period-form", "/timetable/periods", (form) => ({
    scope: form.elements.scope.value,
    target_id: Number(form.elements.target_id.value),
    slot_code: form.elements.slot_code.value,
    label: form.elements.label.value,
    starts_at: form.elements.starts_at.value,
    ends_at: form.elements.ends_at.value,
  }), "Period override saved. The new override applies to future timetable snapshots.");
  submitJSON("timetable-rule-form", "/timetable/rules", (form) => ({
    academic_year: form.elements.academic_year.value,
    target_type: form.elements.target_type.value,
    target_id: Number(form.elements.target_id.value),
    effective_from: form.elements.effective_from.value,
    effective_to: form.elements.effective_to.value || null,
    rule: {
      schema_version: 1,
      max_lessons_per_day: Number(form.elements.max_lessons_per_day.value),
      allowed_days: [...form.elements.allowed_days.selectedOptions].map((option) => option.value),
      allowed_periods: [...form.elements.allowed_periods.selectedOptions].map((option) => option.value),
    },
  }), "Scheduling rule saved.");
  submitJSON("timetable-lesson-form", "/timetable/lessons", (form) => ({
    academic_year: form.elements.academic_year.value,
    instructional_class_id: Number(form.elements.instructional_class_id.value),
    teacher_id: Number(form.elements.teacher_id.value),
    subject_id: Number(form.elements.subject_id.value),
    weekly_count: Number(form.elements.weekly_count.value),
    block_length: Number(form.elements.block_length.value),
  }), "Weekly lesson requirement saved.");

  async function show() {
    showPanel("timetable");
    await refresh();
  }

  function labelFor(block) {
    const requirement = current.snapshot.requirements[String(block.lesson_requirement_id)];
    const teacher = current.snapshot.teachers[String(requirement.teacher_id)];
    const subject = current.snapshot.subjects[String(requirement.subject_id)];
    return `${subject.code} · ${teacher.short_code}${block.is_locked ? " · locked" : ""}`;
  }

  function requirementLabel(id) {
    const requirement = current.snapshot.requirements[String(id)];
    const teacher = current.snapshot.teachers[String(requirement.teacher_id)];
    const subject = current.snapshot.subjects[String(requirement.subject_id)];
    const classItem = current.snapshot.classes[String(requirement.instructional_class_id)];
    return `${classItem.code} · ${subject.name} · ${teacher.full_name} · ${requirement.weekly_count}/week`;
  }

  function classRows() {
    return Object.values(current.snapshot.classes).sort((a, b) => a.reporting_order - b.reporting_order || a.code.localeCompare(b.code));
  }

  function renderGrid() {
    const host = $("timetable-grid");
    host.replaceChildren();
    const all = classRows();
    const density = Number($("timetable-density").value) || 4;
    const visible = all.slice(pageOffset, pageOffset + density);
    $("timetable-previous").disabled = pageOffset === 0;
    $("timetable-next").disabled = pageOffset + density >= all.length;
    for (const classItem of visible) {
      const panel = document.createElement("section");
      panel.className = "panel timetable-class";
      const heading = document.createElement("h4");
      heading.textContent = `${classItem.code} · ${classItem.name}`;
      panel.append(heading);
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      const table = document.createElement("table");
      table.className = "amend-grid";
      const head = document.createElement("thead");
      const headerRow = document.createElement("tr");
      cell(headerRow, "Day");
      for (const period of periods) cell(headerRow, period === "LUNCH" ? "Lunch" : period);
      head.append(headerRow);
      table.append(head);
      const body = document.createElement("tbody");
      for (const day of weekdays) {
        const row = document.createElement("tr");
        cell(row, day);
        for (const period of periods) {
          const td = cell(row, "");
          if (period === "LUNCH") {
            td.className = "lunch-cell";
            td.textContent = "Lunch";
            continue;
          }
          const placement = current.placements.find((block) => block.slots.some((slot) =>
            slot.instructional_class_id === classItem.id && slot.weekday === day && slot.slot_code === period));
          const button = document.createElement("button");
          button.className = placement ? "lesson-cell" : "empty-cell";
          button.disabled = !editableDraft();
          button.textContent = placement ? labelFor(placement) : (editableDraft() ? "+ Add lesson" : "—");
          button.setAttribute("aria-label", placement
            ? `${classItem.code} ${day} ${periodLabels[period]} ${labelFor(placement)}`
            : `Add lesson to ${classItem.code} ${day} ${periodLabels[period]}`);
          if (placement) button.addEventListener("click", () => editPlacement(placement, day, period));
          else if (editableDraft()) button.addEventListener("click", () => run(button, () => addPlacement(classItem, day, period)));
          td.append(button);
        }
        body.append(row);
      }
      table.append(body);
      wrap.append(table);
      panel.append(wrap);
      host.append(panel);
    }
    if (!visible.length) host.textContent = "This timetable has no selected classes.";
  }

  function renderPending() {
    const rows = $("timetable-pending");
    rows.replaceChildren();
    for (const pending of current.pending) {
      const requirement = current.snapshot.requirements[String(pending.lesson_requirement_id)];
      const teacher = current.snapshot.teachers[String(requirement.teacher_id)];
      const subject = current.snapshot.subjects[String(requirement.subject_id)];
      const classItem = current.snapshot.classes[String(requirement.instructional_class_id)];
      const row = document.createElement("tr");
      for (const value of [classItem.name, subject.name, teacher.full_name, pending.remaining_periods, pending.remaining_blocks.join(", ")]) cell(row, value);
      rows.append(row);
    }
    if (!current.pending.length) {
      const row = document.createElement("tr");
      cell(row, "All weekly lesson requirements are placed.").colSpan = 5;
      rows.append(row);
    }
  }

  function render() {
    if (!current) return;
    $("timetable-editor").hidden = false;
    $("timetable-editor-title").textContent = current.name;
    $("timetable-version-detail").textContent = `${current.academic_year} · week of ${current.week_start} · ${current.status} · revision ${current.revision}`;
    $("timetable-generate").hidden = !editableDraft();
    $("timetable-generation-mode").disabled = !editableDraft();
    $("timetable-search-budget").disabled = !editableDraft();
    $("timetable-approve").hidden = !canApprove() || current.status !== "DRAFT";
    renderGrid();
    renderPending();
  }

  async function load(id) {
    const sequence = ++detailSequence;
    const result = await api(`/timetable/versions/${id}`);
    if (sequence !== detailSequence) return;
    current = result;
    placementForm.hidden = true;
    $("timetable-generation-summary").textContent = "";
    pageOffset = 0;
    render();
  }

  function openPlacement(requirementOptions, values, isEdit = false) {
    const form = placementForm;
    form.reset();
    form.hidden = false;
    form.elements.placement_id.value = values.placement_id || "";
    form.elements.weekday.value = values.weekday;
    form.elements.start_period.value = values.start_period;
    form.elements.note.value = values.note || "";
    $("timetable-placement-title").textContent = isEdit ? "Amend lesson block" : "Add lesson block";
    $("timetable-placement-location").textContent = `${values.class_code} · ${values.weekday} · ${values.start_period}`;
    const reqSelect = form.elements.lesson_requirement_id;
    reqSelect.replaceChildren();
    for (const id of requirementOptions) {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = requirementLabel(id);
      reqSelect.append(option);
    }
    if (values.lesson_requirement_id) reqSelect.value = String(values.lesson_requirement_id);
    const lengthSelect = form.elements.period_count;
    lengthSelect.replaceChildren();
    const lengths = new Set(values.allowed_lengths || [1]);
    if (values.period_count) lengths.add(values.period_count);
    for (const length of [...lengths].sort((a, b) => a - b)) {
      const option = document.createElement("option");
      option.value = length;
      option.textContent = `${length} period${length === 1 ? "" : "s"}`;
      lengthSelect.append(option);
    }
    if (values.period_count) lengthSelect.value = String(values.period_count);
    $("timetable-remove").hidden = !isEdit;
    $("timetable-lock").hidden = !isEdit;
    $("timetable-lock").textContent = values.is_locked ? "Unlock lesson" : "Lock lesson";
    $("timetable-lock").dataset.locked = String(values.is_locked || false);
    form.elements.lesson_requirement_id.disabled = !editableDraft();
    form.elements.period_count.disabled = !editableDraft();
    form.elements.note.disabled = !editableDraft();
    form.querySelector('[type="submit"]').hidden = !editableDraft();
    form.elements.lesson_requirement_id.focus();
  }

  function addPlacement(classItem, weekday, startPeriod) {
    const pending = current.pending.filter((item) => {
      const requirement = current.snapshot.requirements[String(item.lesson_requirement_id)];
      const requirementClass = current.snapshot.classes[String(requirement?.instructional_class_id)];
      return requirementClass?.code === classItem.code;
    });
    if (!pending.length) {
      notice(`No unplaced requirements remain for ${classItem.name}.`);
      return;
    }
    const ids = pending.map((item) => item.lesson_requirement_id);
    const lengths = pending.flatMap((item) => item.remaining_blocks);
    openPlacement(ids, {class_code: classItem.code, weekday, start_period, allowed_lengths: lengths});
  }

  function editPlacement(placement, weekday, startPeriod) {
    const classId = placement.slots.find((slot) => slot.weekday === weekday && slot.slot_code === startPeriod)?.instructional_class_id;
    const classItem = current.snapshot.classes[String(classId)];
    const pendingIds = new Set(current.pending.map((row) => row.lesson_requirement_id));
    const ids = Object.values(current.snapshot.requirements)
      .filter((item) => item.instructional_class_id === classId && (item.id === placement.lesson_requirement_id || pendingIds.has(item.id)))
      .map((item) => item.id);
    openPlacement(ids, {
      placement_id: placement.id, lesson_requirement_id: placement.lesson_requirement_id,
      weekday: placement.weekday, start_period: placement.start_period, period_count: placement.period_count,
      note: placement.note, is_locked: placement.is_locked, class_code: classItem.code,
      allowed_lengths: [placement.period_count],
    }, true);
  }

  async function savePlacement(event) {
    event.preventDefault();
    const form = placementForm;
    const placementId = form.elements.placement_id.value;
    const payload = {
      expected_revision: current.revision,
      lesson_requirement_id: Number(form.elements.lesson_requirement_id.value),
      weekday: form.elements.weekday.value,
      start_period: form.elements.start_period.value,
      period_count: Number(form.elements.period_count.value),
      note: form.elements.note.value,
    };
    current = await api(placementId
      ? `/timetable/versions/${current.id}/placements/${placementId}`
      : `/timetable/versions/${current.id}/placements`, placementId ? "PUT" : "POST", payload);
    form.hidden = true;
    render();
    notice("Lesson saved to the timetable draft.");
  }

  async function removePlacement() {
    const id = placementForm.elements.placement_id.value;
    current = await api(`/timetable/versions/${current.id}/placements/${id}?expected_revision=${current.revision}`, "DELETE");
    placementForm.hidden = true;
    render();
    notice("Lesson removed from the draft.");
  }

  async function toggleLock() {
    const id = placementForm.elements.placement_id.value;
    const isLocked = placementForm.querySelector("#timetable-lock").dataset.locked !== "true";
    current = await api(`/timetable/versions/${current.id}/placements/${id}/lock`, "PATCH", {expected_revision: current.revision, is_locked: isLocked});
    placementForm.hidden = true;
    render();
    notice(isLocked ? "Lesson locked." : "Lesson unlocked.");
  }

  async function generate() {
    if (!current || current.status !== "DRAFT") return;
    const mode = $("timetable-generation-mode").value;
    if (mode === "REPLACE_UNLOCKED" && !window.confirm("Replace all unlocked lesson blocks in this draft? Locked blocks will remain.")) return;
    const result = await api(`/timetable/versions/${current.id}/generate`, "POST", {
      expected_revision: current.revision,
      mode,
      search_budget: Number($("timetable-search-budget").value),
    });
    current = result.timetable;
    const report = result.generation;
    $("timetable-generation-summary").textContent = report.complete
      ? `Generation complete: ${report.generated_periods} periods added. Draft revision ${current.revision}.`
      : `Generation placed ${report.generated_periods} periods. ${report.unplaced.length} blocks remain; review the pending list. Search limit reached: ${report.search_limit_reached ? "yes" : "no"}.`;
    render();
  }

  async function approve() {
    current = await api(`/timetable/versions/${current.id}/approve`, "POST", {expected_revision: current.revision});
    render();
    await refresh();
    notice("Timetable approved and saved as an immutable version.");
  }

  $("timetable-create-form").addEventListener("submit", (event) => {
    event.preventDefault();
    run(event.currentTarget, async () => {
      const form = event.currentTarget;
      const payload = {
        name: form.elements.name.value,
        academic_year: form.elements.academic_year.value,
        week_start: form.elements.week_start.value,
        class_ids: [...form.elements.class_ids.selectedOptions].map((option) => Number(option.value)),
      };
      current = await api("/timetable/versions", "POST", payload);
      form.hidden = true;
      await refresh();
      render();
      notice("Weekly timetable draft created.");
    });
  });
  placementForm.addEventListener("submit", (event) => run(placementForm, () => savePlacement(event)));
  $("timetable-remove").addEventListener("click", () => run($("timetable-remove"), removePlacement));
  $("timetable-lock").addEventListener("click", () => run($("timetable-lock"), toggleLock));
  $("timetable-cancel-placement").addEventListener("click", () => { placementForm.hidden = true; });
  $("timetable-generate").addEventListener("click", () => run($("timetable-generate"), generate));
  $("timetable-approve").addEventListener("click", () => run($("timetable-approve"), approve));
  $("new-timetable").addEventListener("click", () => {
    const form = $("timetable-create-form");
    form.hidden = !form.hidden;
    if (!form.hidden) form.elements.name.focus();
  });
  $("refresh-timetables").addEventListener("click", () => run($("refresh-timetables"), refresh));
  $("timetable-reload").addEventListener("click", () => run($("timetable-reload"), () => load(current.id)));
  $("timetable-density").addEventListener("change", renderGrid);
  $("timetable-period-form").elements.scope.addEventListener("change", updatePeriodTargets);
  $("timetable-rule-form").elements.target_type.addEventListener("change", updateRuleTargets);
  $("timetable-previous").addEventListener("click", () => { pageOffset = Math.max(0, pageOffset - Number($("timetable-density").value)); renderGrid(); });
  $("timetable-next").addEventListener("click", () => { pageOffset += Number($("timetable-density").value); renderGrid(); });

  return {show, clear};
}
