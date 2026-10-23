from datetime import date

from pydantic import BaseModel, Field, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str


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
