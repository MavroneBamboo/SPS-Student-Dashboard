from datetime import date
from datetime import time as time_value

from pydantic import BaseModel, Field, model_validator


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


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    must_change_password: bool


class RuleCreate(BaseModel):
    academic_year: str = Field(min_length=1, max_length=20)
    target_type: str = Field(pattern="^(CLASS|CLUSTER)$")
    target_key: str = Field(min_length=1, max_length=120)
    effective_from: date
    effective_to: date | None = None
    rule: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")
        return self


class RuleResponse(RuleCreate):
    id: int
    is_active: bool


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


class SubjectCreate(BaseModel):
    code: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True


class SubjectResponse(SubjectCreate):
    id: int


class InstructionalClassCreate(BaseModel):
    code: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    reporting_order: int = Field(default=0, ge=0, le=10000)
    is_active: bool = True


class InstructionalClassResponse(InstructionalClassCreate):
    id: int


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


class StudentCreate(BaseModel):
    pris_no: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=240)
    class_name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=40)
    status: str = Field(default="ACTIVE", min_length=1, max_length=40)
    status_effective: date | None = None
    date_of_birth: date | None = None


class StudentResponse(StudentCreate):
    id: int


class StudentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    class_name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=40)
    status: str | None = Field(default=None, min_length=1, max_length=40)
    status_effective: date | None = None
    date_of_birth: date | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one student field must be provided")
        return self


class StudentStatusHistoryResponse(BaseModel):
    previous_status: str | None
    new_status: str
    effective_date: date
    changed_by: int


class AttendanceSessionCreate(BaseModel):
    session_date: date
    session_type: str = Field(pattern="^(MORNING|AFTERNOON|FULL_DAY)$")
    class_name: str = Field(min_length=1, max_length=120)
    expected_count: int = Field(ge=1, le=10000)
    notes: str | None = Field(default=None, max_length=1000)


class AttendanceSessionResponse(AttendanceSessionCreate):
    id: int
    status: str


class AttendanceRecordCreate(BaseModel):
    pris_no: str = Field(min_length=1, max_length=40)
    attendance_status: str = Field(pattern="^(PRESENT|ABSENT|LATE|EXCUSED|MISSING)$")
    correction_reason: str | None = Field(default=None, max_length=1000)


class AttendanceRecordResponse(BaseModel):
    id: int
    session_id: int
    pris_no: str
    student_name: str
    attendance_status: str
    correction_reason: str | None
