"""Password hashing cost: the production setting is the OWASP minimum, old hashes still work and are upgraded at sign-in."""
import pytest

from src.config import settings
from src.shared.auth import hash_password, needs_rehash, verify_password
from tests.test_registration import gateway, sign_in  # noqa: F401  (fixture reused)


def test_the_production_cost_is_n_2_16_r_8_p_2_and_verifies(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_SCRYPT_LOG2_N", 16)
    stored = hash_password("a long enough password")
    assert stored.startswith("scrypt$65536$8$2$")
    assert verify_password("a long enough password", stored) and not verify_password("another password", stored)


def test_a_hash_made_at_a_lower_cost_still_verifies_and_is_marked_for_upgrade(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_SCRYPT_LOG2_N", 10)
    old = hash_password("a long enough password")
    monkeypatch.setattr(settings, "AUTH_SCRYPT_LOG2_N", 12)
    assert verify_password("a long enough password", old)
    assert needs_rehash(old) and not needs_rehash(hash_password("a long enough password"))
    assert not needs_rehash("not a hash")


def test_a_stored_hash_cannot_ask_for_an_absurd_amount_of_memory():
    assert verify_password("x", "scrypt$1073741824$8$1$00$00") is False


def test_a_successful_sign_in_replaces_a_cheaper_hash(gateway, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "AUTH_SCRYPT_LOG2_N", 10)
    cheap = hash_password("a long enough password")
    monkeypatch.setattr(settings, "AUTH_SCRYPT_LOG2_N", 12)
    gateway.pg_client.rows["carol"] = {"username": "carol", "display_name": "", "password_hash": cheap, "recovery_hash": None,
                                       "roles": [], "tenant_id": "t", "department_id": "d"}
    assert sign_in(gateway, "carol", "a long enough password").user["user"] == "carol"
    upgraded = gateway.pg_client.rows["carol"]["password_hash"]
    assert upgraded.split("$")[1] == str(4096) and verify_password("a long enough password", upgraded)


def test_a_wrong_password_leaves_the_stored_hash_alone(gateway, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "AUTH_SCRYPT_LOG2_N", 10)
    cheap = hash_password("a long enough password")
    monkeypatch.setattr(settings, "AUTH_SCRYPT_LOG2_N", 12)
    gateway.pg_client.rows["carol"] = {"username": "carol", "display_name": "", "password_hash": cheap, "recovery_hash": None,
                                       "roles": [], "tenant_id": "t", "department_id": "d"}
    with pytest.raises(gateway.HTTPException):
        sign_in(gateway, "carol", "not my password")
    assert gateway.pg_client.rows["carol"]["password_hash"] == cheap
