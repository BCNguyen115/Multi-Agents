"""A fresh self-registration lands in the pending tenant: it sees no knowledge-base document and no database row."""
import asyncio

import pytest
from fastapi import HTTPException

from src.config import settings
from src.shared import auth
from src.shared.auth import Principal, knowledge_tenants
from tests.test_registration import gateway, request, sign_up  # noqa: F401  (fixture reused)


def principal(tenant: str, authenticated: bool = True) -> Principal:
    return Principal("carol", tenant, "dept", frozenset(), authenticated=authenticated)


@pytest.fixture
def as_caller():
    """Set the request's principal the way `authenticate` does, and put it back afterwards."""
    tokens = []

    def use(p: Principal) -> None:
        tokens.append(auth._current.set(p))

    yield use
    for token in reversed(tokens):
        auth._current.reset(token)


def test_only_a_signed_in_account_in_the_pending_tenant_is_unassigned():
    assert principal(settings.REGISTRATION_TENANT_ID).unassigned
    assert not principal(settings.RLS_TENANT_ID).unassigned
    assert not principal(settings.REGISTRATION_TENANT_ID, authenticated=False).unassigned  # AUTH_MODE=off: nobody is "pending"


def test_a_sign_up_lands_in_the_pending_tenant_and_the_ui_is_told(gateway):  # noqa: F811
    response = sign_up(gateway)
    assert response.user["tenant_id"] == settings.REGISTRATION_TENANT_ID
    assert response.user["department_id"] == settings.REGISTRATION_DEPARTMENT_ID
    assert response.user["access_pending"] is True
    stored = gateway.pg_client.rows["carol"]
    assert (stored["tenant_id"], stored["department_id"]) == (settings.REGISTRATION_TENANT_ID, settings.REGISTRATION_DEPARTMENT_ID)


def test_retrieval_is_confined_to_the_callers_tenant_when_unassigned(as_caller, monkeypatch):
    monkeypatch.setattr(settings, "RAG_TENANT_IDS", None)
    as_caller(principal(settings.RLS_TENANT_ID))
    assert knowledge_tenants() is None  # an assigned account: the operator's setting (None = the whole corpus)
    as_caller(principal(settings.REGISTRATION_TENANT_ID))
    assert knowledge_tenants() == [settings.REGISTRATION_TENANT_ID]  # no chunk is stored under it: nothing comes back


def test_the_operator_setting_still_applies_to_assigned_accounts(as_caller, monkeypatch):
    monkeypatch.setattr(settings, "RAG_TENANT_IDS", ["acme"])
    as_caller(principal(settings.RLS_TENANT_ID))
    assert knowledge_tenants() == ["acme"]


def test_listing_and_viewing_documents_is_refused_while_unassigned():
    from src.gateway import knowledge

    pending = principal(settings.REGISTRATION_TENANT_ID)
    with pytest.raises(HTTPException) as listing:
        asyncio.run(knowledge.list_documents(request=None, category=None, principal=pending))
    assert listing.value.status_code == 403
    with pytest.raises(HTTPException) as page:
        asyncio.run(knowledge.page_image(doc_key="nda/a.pdf", page=1, q="", scale=1.0, principal=pending))
    assert page.value.status_code == 403
