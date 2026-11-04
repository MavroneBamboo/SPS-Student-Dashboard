import builtins
import io
import json
from contextlib import nullcontext

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import recover_superuser as recovery_cli
from app.models import AuditEvent, User
from app.security import hash_password, verify_password
from app.superuser_recovery import RecoveryRefused, recover_superuser


@pytest.fixture
def recovery_db():
    engine = create_engine("sqlite://")
    User.__table__.create(engine)
    AuditEvent.__table__.create(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_recovery_activates_superuser_revokes_tokens_requires_rotation_and_audits_without_password(recovery_db):
    target = User(
        username="root-account",
        password_hash=hash_password("old-superuser-password"),
        role="Superuser",
        token_version=4,
        must_change_password=False,
        is_active=False,
    )
    recovery_db.add(target)
    recovery_db.commit()

    user_id = recover_superuser(
        recovery_db,
        " ROOT-ACCOUNT ",
        "it.operator",
        "INC-2048: verified loss of Superuser credentials",
        "new-temporary-recovery-password",
    )

    recovered = recovery_db.get(User, user_id)
    event = recovery_db.scalar(select(AuditEvent).where(AuditEvent.action == "security.superuser.recovered"))
    assert recovered is not None
    assert recovered.is_active and recovered.must_change_password
    assert recovered.token_version == 5
    assert verify_password("new-temporary-recovery-password", recovered.password_hash)
    assert event is not None and event.actor_id == 0 and event.entity_id == str(user_id)
    assert json.loads(event.details_json) == {
        "performed_by": "it.operator",
        "reason": "INC-2048: verified loss of Superuser credentials",
    }
    assert "new-temporary-recovery-password" not in event.details_json


def test_recovery_is_refused_when_another_active_superuser_exists_without_changes(recovery_db):
    target = User(
        username="recovery-target",
        password_hash=hash_password("old-password"),
        role="Superuser",
        is_active=False,
        must_change_password=False,
    )
    other = User(username="other-superuser", password_hash=hash_password("other-password"), role="Superuser", is_active=True)
    recovery_db.add_all([target, other])
    recovery_db.commit()
    old_hash = target.password_hash

    with pytest.raises(RecoveryRefused, match="Another active Superuser exists"):
        recover_superuser(recovery_db, target.username, "it.operator", "INC-2049", "new-temporary-recovery-password")

    recovery_db.refresh(target)
    assert not target.is_active and not target.must_change_password
    assert target.password_hash == old_hash
    assert recovery_db.scalar(select(AuditEvent.id)) is None


@pytest.mark.parametrize(
    ("username", "performed_by", "reason", "password", "message"),
    [
        ("missing-account", "it.operator", "INC-2050", "new-temporary-recovery-password", "existing Superuser"),
        ("operator-account", "it.operator", "INC-2050", "new-temporary-recovery-password", "existing Superuser"),
        ("recovery-root", "", "INC-2050", "new-temporary-recovery-password", "IT operator identity"),
        ("recovery-root", "it.operator", "", "new-temporary-recovery-password", "recovery reason"),
        ("recovery-root", "it.operator", "INC-2050", "short", "between 12 and 200"),
    ],
)
def test_recovery_rejects_invalid_targets_and_metadata(recovery_db, username, performed_by, reason, password, message):
    recovery_db.add_all(
        [
            User(username="recovery-root", password_hash=hash_password("old-password"), role="Superuser", is_active=False),
            User(username="operator-account", password_hash=hash_password("operator-password"), role="Operator", is_active=False),
        ]
    )
    recovery_db.commit()

    with pytest.raises(RecoveryRefused, match=message):
        recover_superuser(recovery_db, username, performed_by, reason, password)

    assert recovery_db.scalar(select(AuditEvent.id)) is None


def test_recovery_cli_requires_interactive_terminal(monkeypatch):
    monkeypatch.setattr(recovery_cli.sys, "stdin", io.StringIO())

    with pytest.raises(SystemExit) as error:
        recovery_cli.main(["--username", "root-account", "--performed-by", "it.operator", "--reason", "INC-2048"])

    assert error.value.code == 2


def test_recovery_cli_cancels_when_password_confirmation_does_not_match(monkeypatch, capsys):
    class InteractiveInput(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(recovery_cli.sys, "stdin", InteractiveInput())
    monkeypatch.setattr(builtins, "input", lambda _prompt: "RECOVER")
    passwords = iter(["first-temporary-password", "different-temporary-password"])
    monkeypatch.setattr(recovery_cli.getpass, "getpass", lambda _prompt: next(passwords))

    assert recovery_cli.main(["--username", "root-account", "--performed-by", "it.operator", "--reason", "INC-2048"]) == 2
    assert "did not match" in capsys.readouterr().err


def test_recovery_cli_prompts_for_secret_and_does_not_print_it(monkeypatch, capsys):
    class InteractiveInput(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(recovery_cli.sys, "stdin", InteractiveInput())
    monkeypatch.setattr(builtins, "input", lambda _prompt: "RECOVER")
    secret = "temporary-superuser-password"
    monkeypatch.setattr(recovery_cli.getpass, "getpass", lambda _prompt: secret)
    calls = []
    db = object()
    monkeypatch.setattr(recovery_cli, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(recovery_cli, "recover_superuser", lambda db, *args: calls.append((db, args)) or 42)

    assert recovery_cli.main(["--username", "root-account", "--performed-by", "it.operator", "--reason", "INC-2048"]) == 0
    output = capsys.readouterr().out
    assert "Recovered Superuser account id 42" in output
    assert secret not in output
    assert calls == [(db, ("root-account", "it.operator", "INC-2048", secret))]
