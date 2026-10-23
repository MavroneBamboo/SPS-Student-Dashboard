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
