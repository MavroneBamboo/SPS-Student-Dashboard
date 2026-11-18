from datetime import date, timedelta
from datetime import time as time_value
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    must_change_password: bool = False


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=12, max_length=200)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9._-]+$")
    temporary_password: str = Field(min_length=12, max_length=200)
    role: str = Field(pattern="^(Superuser|IT Administrator|Operator|Executive)$")


class UserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(Superuser|IT Administrator|Operator|Executive)$")
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set or any(value is None for value in self.model_dump(exclude_unset=True).values()):
            raise ValueError("At least one user field must be provided")
        return self


class UserPasswordReset(BaseModel):
    temporary_password: str = Field(min_length=12, max_length=200)


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    must_change_password: bool


class InitialSetupComplete(BaseModel):
    username: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9._-]+$")
    temporary_password: str = Field(min_length=12, max_length=200)


class InitialSetupResponse(BaseModel):
    completed: bool
    administrator: UserResponse


class RuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    max_lessons_per_day: int = Field(default=4, ge=1, le=4)
    allowed_days: list[Literal["MON", "TUE", "WED", "THU", "FRI"]] = Field(
        default_factory=lambda: ["MON", "TUE", "WED", "THU", "FRI"], min_length=1, max_length=5
    )
    allowed_periods: list[Literal["P1", "P2", "P3", "P4"]] = Field(
        default_factory=lambda: ["P1", "P2", "P3", "P4"], min_length=1, max_length=4
    )

    @model_validator(mode="after")
    def unique_slots(self):
        if len(self.allowed_days) != len(set(self.allowed_days)) or len(self.allowed_periods) != len(set(self.allowed_periods)):
            raise ValueError("Allowed days and periods must be unique")
        return self


class RuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, str_to_upper=True)

    academic_year: str = Field(min_length=1, max_length=20)
    target_type: Literal["CLASS", "CLUSTER"]
    target_id: int = Field(gt=0)
    effective_from: date
    effective_to: date | None = None
    rule: RuleDefinition = Field(default_factory=RuleDefinition)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")
        return self


class RuleUpdate(RuleCreate):
    expected_version: int = Field(ge=1)
    is_active: bool


class RuleResponse(BaseModel):
    id: int
    academic_year: str
    target_type: str
    target_id: int | None
    target_key: str
    effective_from: date
    effective_to: date | None
    rule: dict | None
    binding_state: str
    version: int
    is_active: bool


class RuleResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, str_to_upper=True)

    academic_year: str = Field(min_length=1, max_length=20)
    on_date: date
    class_ids: list[int] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_classes(self):
        if any(class_id < 1 for class_id in self.class_ids) or len(self.class_ids) != len(set(self.class_ids)):
            raise ValueError("class_ids must contain unique positive IDs")
        return self


class ResolvedRule(BaseModel):
    instructional_class_id: int
    rule_id: int
    version: int
    target_type: str
    target_id: int
    rule: RuleDefinition


class TimetableDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    academic_year: str = Field(min_length=1, max_length=20)
    week_start: date
    class_ids: list[int] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_week(self):
        if self.week_start.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        try:
            self.week_start + timedelta(days=4)
        except OverflowError as exc:
            raise ValueError("The complete teaching week must be representable") from exc
        if any(class_id < 1 for class_id in self.class_ids) or len(self.class_ids) != len(set(self.class_ids)):
            raise ValueError("class_ids must be unique positive IDs")
        self.academic_year = self.academic_year.upper()
        return self


class TimetableRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


class TimetableRenameRequest(TimetableRevisionRequest):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)


class TimetableMoveRequest(TimetableRevisionRequest):
    weekday: Literal["MON", "TUE", "WED", "THU", "FRI"]
    start_period: Literal["P1", "P2", "P3", "P4"]


class TimetablePlacementWrite(TimetableRevisionRequest):
    lesson_requirement_id: int = Field(gt=0)
    weekday: Literal["MON", "TUE", "WED", "THU", "FRI"]
    start_period: Literal["P1", "P2", "P3", "P4"]
    period_count: int = Field(default=1, ge=1, le=4)
    note: str = Field(default="", max_length=500)


class TimetableSwapRequest(TimetableRevisionRequest):
    first_placement_id: int = Field(gt=0)
    second_placement_id: int = Field(gt=0)

    @model_validator(mode="after")
    def different_blocks(self):
        if self.first_placement_id == self.second_placement_id:
            raise ValueError("Swap requires two different blocks")
        return self


class TimetableLockRequest(TimetableRevisionRequest):
    is_locked: bool


class TimetableGenerateRequest(TimetableRevisionRequest):
    mode: Literal["FILL_PENDING", "REPLACE_UNLOCKED"] = "FILL_PENDING"
    search_budget: int = Field(default=2000, ge=1, le=10000)


WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI")
TEACHING_PERIODS = ("P1", "P2", "P3", "P4")


class TeacherCreate(BaseModel):
    short_code: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    full_name: str = Field(min_length=1, max_length=160)
    is_adjunct: bool = False
    availability: dict[str, list[str]] = Field(default_factory=lambda: {day: list(TEACHING_PERIODS) for day in WEEKDAYS})
    is_active: bool = True

    @model_validator(mode="after")
    def validate_availability(self):
        if set(self.availability) != set(WEEKDAYS):
            raise ValueError("availability must provide exactly MON, TUE, WED, THU, and FRI")
        for day, periods in self.availability.items():
            if len(periods) != len(set(periods)) or not set(periods) <= set(TEACHING_PERIODS):
                raise ValueError(f"{day} availability must contain unique teaching periods P1 through P4 only")
        return self


class TeacherResponse(TeacherCreate):
    id: int
    is_composite: bool = False
    member_ids: list[int] = Field(default_factory=list)
    revision: str


class TeacherUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    short_code: str | None = Field(default=None, min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    is_adjunct: bool | None = None
    availability: dict[str, list[str]] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_update(self):
        if not self.model_fields_set - {"expected_revision"}:
            raise ValueError("At least one teacher field must be provided")
        if any(getattr(self, field) is None for field in self.model_fields_set - {"expected_revision"}):
            raise ValueError("Teacher fields cannot be null")
        if self.availability is not None:
            TeacherCreate(
                short_code=self.short_code or "TEMP",
                full_name=self.full_name or "Temporary profile",
                availability=self.availability,
            )
        return self


class TeacherGroupCreate(BaseModel):
    short_code: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    full_name: str = Field(min_length=1, max_length=160)
    member_ids: list[int] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_members(self):
        if any(member_id <= 0 for member_id in self.member_ids) or len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError("A teacher group requires at least two distinct positive teacher IDs")
        return self


class LessonRequirementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, str_to_upper=True)

    academic_year: str = Field(min_length=1, max_length=20)
    instructional_class_id: int = Field(gt=0)
    teacher_id: int = Field(gt=0)
    subject_id: int = Field(gt=0)
    weekly_count: int = Field(ge=1, le=20)
    block_length: int = Field(default=1, ge=1, le=4)


class LessonRequirementUpdate(LessonRequirementCreate):
    expected_version: int = Field(ge=1)
    is_active: bool


class LessonRequirementResponse(LessonRequirementCreate):
    id: int
    version: int
    is_active: bool


class SubjectCreate(BaseModel):
    code: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True


class SubjectResponse(SubjectCreate):
    id: int
    revision: str


class SubjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    code: str | None = Field(default=None, min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set - {"expected_revision"}:
            raise ValueError("At least one subject field must be provided")
        if any(getattr(self, field) is None for field in self.model_fields_set & {"code", "name", "is_active"}):
            raise ValueError("Subject fields cannot be null")
        return self


class InstructionalClassCreate(BaseModel):
    code: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    reporting_order: int = Field(default=0, ge=0, le=10000)
    is_active: bool = True


class InstructionalClassResponse(InstructionalClassCreate):
    id: int
    revision: str


class InstructionalClassUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    code: str | None = Field(default=None, min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    reporting_order: int | None = Field(default=None, ge=0, le=10000)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set - {"expected_revision"}:
            raise ValueError("At least one instructional-class field must be provided")
        if any(getattr(self, field) is None for field in self.model_fields_set & {"code", "name", "reporting_order", "is_active"}):
            raise ValueError("Instructional-class fields cannot be null")
        return self


class StudentClassMappingCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    source_workbook: Literal["STUDENT_INTAKE_2021", "STUDENT_INTAKE_2023"] = "STUDENT_INTAKE_2023"
    source_label: str = Field(min_length=1, max_length=120)
    instructional_class_id: int = Field(ge=1)


class StudentClassMappingUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    expected_version: int = Field(ge=1)
    instructional_class_id: int | None = Field(default=None, ge=1)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set - {"expected_version"}:
            raise ValueError("At least one mapping field must be provided")
        if ("instructional_class_id" in self.model_fields_set and self.instructional_class_id is None) or (
            "is_active" in self.model_fields_set and self.is_active is None
        ):
            raise ValueError("Mapping fields cannot be null")
        return self


class StudentClassMappingResponse(BaseModel):
    id: int
    source_workbook: str
    source_label: str
    instructional_class_id: int
    class_code: str
    class_name: str
    is_active: bool
    version: int


class AttendanceClassMappingCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    student_class_name: str = Field(min_length=1, max_length=120)
    instructional_class_id: int = Field(ge=1)


class AttendanceClassMappingUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    expected_version: int = Field(ge=1)
    instructional_class_id: int | None = Field(default=None, ge=1)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set - {"expected_version"}:
            raise ValueError("At least one mapping field must be provided")
        if ("instructional_class_id" in self.model_fields_set and self.instructional_class_id is None) or (
            "is_active" in self.model_fields_set and self.is_active is None
        ):
            raise ValueError("Mapping fields cannot be null")
        return self


class AttendanceClassMappingResponse(BaseModel):
    id: int
    student_class_name: str
    instructional_class_id: int
    class_code: str
    instructional_class_name: str
    active_students: int
    is_active: bool
    version: int


class ClusterCreate(BaseModel):
    code: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True


class ClusterResponse(ClusterCreate):
    id: int
    class_ids: list[int] = Field(default_factory=list)


class ClusterMemberCreate(BaseModel):
    instructional_class_id: int = Field(gt=0)


class PeriodCreate(BaseModel):
    scope: str = Field(pattern="^(DEFAULT|CLASS|CLUSTER)$")
    target_id: int | None = Field(default=None, gt=0)
    slot_code: str = Field(pattern="^(P1|P2|LUNCH|P3|P4)$")
    label: str = Field(min_length=1, max_length=80)
    starts_at: time_value | None = None
    ends_at: time_value | None = None

    @model_validator(mode="after")
    def validate_period_definition(self):
        if (self.scope == "DEFAULT") != (self.target_id is None):
            raise ValueError("DEFAULT periods have no target_id; CLASS and CLUSTER periods require one")
        if self.starts_at is None or self.ends_at is None:
            raise ValueError("Every period definition requires start and end times")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        if self.slot_code == "LUNCH" and self.label.strip().upper() != "LUNCH":
            raise ValueError("Lunch must remain labelled Lunch and requires a time interval")
        return self


class PeriodResponse(BaseModel):
    id: int
    scope: str
    target_id: int | None
    slot_code: str
    display_order: int
    label: str
    starts_at: time_value | None
    ends_at: time_value | None
    is_schedulable: bool
    is_active: bool = True


class PeriodUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    starts_at: time_value | None = None
    ends_at: time_value | None = None

    @model_validator(mode="after")
    def require_ordered_times(self):
        if not self.model_fields_set:
            raise ValueError("At least one period field must be provided")
        if ("starts_at" in self.model_fields_set) != ("ends_at" in self.model_fields_set):
            raise ValueError("Update both starts_at and ends_at together")
        if "starts_at" in self.model_fields_set and (self.starts_at is None or self.ends_at is None):
            raise ValueError("Period start and end times cannot be cleared")
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        if any(value is None for value in self.model_dump(exclude_unset=True).values()):
            raise ValueError("Period fields cannot be null")
        return self


class FixedEventSlot(BaseModel):
    weekday: Literal["MON", "TUE", "WED", "THU", "FRI"]
    slot_code: Literal["P1", "P2", "P3", "P4"]


class TimetableFixedEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    academic_year: str = Field(min_length=1, max_length=20)
    label: str = Field(min_length=1, max_length=120)
    audience_type: Literal["CLASS", "TEACHER"]
    target_mode: Literal["ALL", "SELECTED"]
    target_ids: list[int] = Field(default_factory=list)
    slots: list[FixedEventSlot] = Field(min_length=1, max_length=20)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_event(self):
        if self.target_mode == "ALL" and self.target_ids:
            raise ValueError("ALL fixed events must not include target_ids")
        if self.target_mode == "SELECTED" and not self.target_ids:
            raise ValueError("SELECTED fixed events require at least one target_id")
        if len(self.target_ids) != len(set(self.target_ids)) or any(target_id < 1 for target_id in self.target_ids):
            raise ValueError("target_ids must be unique positive IDs")
        keys = [(slot.weekday, slot.slot_code) for slot in self.slots]
        if len(keys) != len(set(keys)):
            raise ValueError("Fixed event slots must be unique")
        if not self.academic_year.strip() or not self.label.strip():
            raise ValueError("Academic year and event label are required")
        return self


class TimetableFixedEventUpdate(TimetableFixedEventCreate):
    expected_version: int = Field(ge=1)


class TimetableFixedEventResponse(TimetableFixedEventCreate):
    id: int
    version: int


class StudentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    pris_no: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=240)
    class_name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=40)
    institution: str | None = Field(default=None, max_length=120)
    status: str = Field(default="ACTIVE", min_length=1, max_length=40)
    status_effective: date | None = None
    date_of_birth: date | None = None
    edr_ros: str | None = Field(default=None, max_length=80)
    ic_number: str | None = Field(default=None, max_length=40)
    admission_type: str | None = Field(default=None, max_length=80)
    exam_level: str | None = Field(default=None, max_length=80)
    academic_year: str | None = Field(default=None, max_length=20)
    age_in_academic_year: int | None = Field(default=None, ge=0, le=120)
    gender: str | None = Field(default=None, max_length=40)
    language_1: str | None = Field(default=None, max_length=120)
    language_2: str | None = Field(default=None, max_length=120)
    math_1: str | None = Field(default=None, max_length=120)
    math_2: str | None = Field(default=None, max_length=120)
    cpa: str | None = Field(default=None, max_length=120)
    science: str | None = Field(default=None, max_length=120)
    humanities: str | None = Field(default=None, max_length=120)
    commerce_1: str | None = Field(default=None, max_length=120)
    commerce_2: str | None = Field(default=None, max_length=120)
    commerce_3: str | None = Field(default=None, max_length=120)
    aa: str | None = Field(default=None, max_length=120)
    nationality: str | None = Field(default=None, max_length=120)
    citizenship: str | None = Field(default=None, max_length=120)
    birthplace: str | None = Field(default=None, max_length=240)
    religion: str | None = Field(default=None, max_length=120)
    race: str | None = Field(default=None, max_length=120)
    marital_status: str | None = Field(default=None, max_length=80)
    next_of_kin_name: str | None = Field(default=None, max_length=240)
    next_of_kin_nric: str | None = Field(default=None, max_length=40)
    next_of_kin_relationship: str | None = Field(default=None, max_length=120)
    next_of_kin_contact: str | None = Field(default=None, max_length=80)
    next_of_kin_address_ports: str | None = Field(default=None, max_length=1500)
    next_of_kin_address_from_student: str | None = Field(default=None, max_length=1500)
    student_contact: str | None = Field(default=None, max_length=80)
    verification_note: str | None = Field(default=None, max_length=500)
    elective: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def pair_age_with_academic_year(self):
        if self.age_in_academic_year is not None and not self.academic_year:
            raise ValueError("academic_year is required when age_in_academic_year is provided")
        return self


class StudentResponse(StudentCreate):
    id: int
    version: int


class StudentUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    class_name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=40)
    institution: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, min_length=1, max_length=40)
    status_effective: date | None = None
    date_of_birth: date | None = None
    edr_ros: str | None = Field(default=None, max_length=80)
    ic_number: str | None = Field(default=None, max_length=40)
    admission_type: str | None = Field(default=None, max_length=80)
    exam_level: str | None = Field(default=None, max_length=80)
    academic_year: str | None = Field(default=None, max_length=20)
    age_in_academic_year: int | None = Field(default=None, ge=0, le=120)
    gender: str | None = Field(default=None, max_length=40)
    language_1: str | None = Field(default=None, max_length=120)
    language_2: str | None = Field(default=None, max_length=120)
    math_1: str | None = Field(default=None, max_length=120)
    math_2: str | None = Field(default=None, max_length=120)
    cpa: str | None = Field(default=None, max_length=120)
    science: str | None = Field(default=None, max_length=120)
    humanities: str | None = Field(default=None, max_length=120)
    commerce_1: str | None = Field(default=None, max_length=120)
    commerce_2: str | None = Field(default=None, max_length=120)
    commerce_3: str | None = Field(default=None, max_length=120)
    aa: str | None = Field(default=None, max_length=120)
    nationality: str | None = Field(default=None, max_length=120)
    citizenship: str | None = Field(default=None, max_length=120)
    birthplace: str | None = Field(default=None, max_length=240)
    religion: str | None = Field(default=None, max_length=120)
    race: str | None = Field(default=None, max_length=120)
    marital_status: str | None = Field(default=None, max_length=80)
    next_of_kin_name: str | None = Field(default=None, max_length=240)
    next_of_kin_nric: str | None = Field(default=None, max_length=40)
    next_of_kin_relationship: str | None = Field(default=None, max_length=120)
    next_of_kin_contact: str | None = Field(default=None, max_length=80)
    next_of_kin_address_ports: str | None = Field(default=None, max_length=1500)
    next_of_kin_address_from_student: str | None = Field(default=None, max_length=1500)
    student_contact: str | None = Field(default=None, max_length=80)
    verification_note: str | None = Field(default=None, max_length=500)
    elective: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set - {"expected_version"}:
            raise ValueError("At least one student field must be provided")
        for field in ("name", "class_name", "category", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class StudentStatusHistoryResponse(BaseModel):
    previous_status: str | None
    new_status: str
    effective_date: date
    changed_by: int


class StudentReferenceValueCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    effective_from: date | None = None
    effective_to: date | None = None

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")
        return self


class StudentReferenceValueUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    effective_from: date | None = None
    effective_to: date | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change_and_ordered_dates(self):
        if not self.model_fields_set - {"expected_version"}:
            raise ValueError("At least one catalog field must be provided")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        if "is_active" in self.model_fields_set and self.is_active is None:
            raise ValueError("is_active cannot be null")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")
        return self


class StudentReferenceValueResponse(BaseModel):
    id: int
    catalog_type: str
    name: str
    description: str | None
    effective_from: date | None
    effective_to: date | None
    is_active: bool
    version: int


class AttendanceSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    session_date: date
    session_type: str = Field(pattern="^(MORNING|AFTERNOON|FULL_DAY)$")
    class_name: str = Field(min_length=1, max_length=120)
    expected_count: int = Field(ge=1, le=10000)
    notes: str | None = Field(default=None, max_length=1000)
    timetable_version_id: int | None = Field(default=None, ge=1)
    instructional_class_id: int | None = Field(default=None, ge=1)


class AttendanceSessionResponse(AttendanceSessionCreate):
    id: int
    version: int
    status: str
    roster_snapshot_state: str


class AttendanceRosterEntryResponse(BaseModel):
    student_id: int
    pris_no: str
    student_name: str
    student_status: str | None
    attendance_status: str | None


class AttendanceRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_session_version: int = Field(ge=1)
    pris_no: str = Field(min_length=1, max_length=40)
    attendance_status: str = Field(pattern="^(PRESENT|ABSENT|LATE|EXCUSED|MISSING)$")
    correction_reason: str | None = Field(default=None, min_length=1, max_length=1000)


class AttendanceRecordCorrection(AttendanceRecordCreate):
    expected_version: int = Field(ge=1)
    correction_reason: str = Field(min_length=1, max_length=1000)


class AttendanceSessionClose(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=1)
    allow_incomplete: bool = False
    reason: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def explain_incomplete(self):
        if self.allow_incomplete and not self.reason:
            raise ValueError("A reason is required to close incomplete attendance")
        return self


class AttendanceSessionCount(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=1)
    expected_count: int = Field(ge=1, le=10000)
    reason: str = Field(min_length=1, max_length=1000)


class AttendanceRecordResponse(BaseModel):
    id: int
    version: int
    session_version: int
    session_id: int
    pris_no: str
    student_name: str
    attendance_status: str
    correction_reason: str | None
