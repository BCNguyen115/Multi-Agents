"""The knowledge base is not one pool for everybody: a signed-in user reads the shared corpus and their OWN tenant's documents, a document
uploaded from the chat belongs to the uploader's tenant, and nobody can overwrite or delete another tenant's document."""
import pytest

from src.config import settings
from src.gateway.knowledge import _deletable, _readable
from src.ingestion.upload import UploadError
from src.shared.auth import Principal, acting_as, knowledge_tenants

from tests.test_kb_upload import FakeEmbedder, docx_bytes, run_upload, SECTIONED

ALICE = Principal("alice", "acme", "legal", authenticated=True)
ADMIN = Principal("root", "acme", "ops", frozenset({"admin"}), authenticated=True)
PENDING = Principal("newbie", settings.REGISTRATION_TENANT_ID, settings.REGISTRATION_DEPARTMENT_ID, authenticated=True)


def test_a_signed_in_user_reads_the_shared_corpus_and_only_their_own_tenant(monkeypatch):
    monkeypatch.setattr(settings, "RAG_TENANT_IDS", None)
    monkeypatch.setattr(settings, "KNOWLEDGE_TENANT_ISOLATION", True)
    with acting_as(ALICE):
        assert knowledge_tenants() == ["acme", "public"]
    with acting_as(Principal("gus", "globex", "ops", authenticated=True)):
        assert knowledge_tenants() == ["globex", "public"]  # never acme's
    with acting_as(PENDING):
        assert knowledge_tenants() == [PENDING.tenant_id]  # a pending account still sees nothing
    assert knowledge_tenants() is None  # anonymous dev mode: unchanged


def test_the_operators_allow_list_and_the_switch_still_decide(monkeypatch):
    monkeypatch.setattr(settings, "RAG_TENANT_IDS", ["public"])
    with acting_as(ALICE):
        assert knowledge_tenants() == ["public"]  # explicit configuration wins
    monkeypatch.setattr(settings, "RAG_TENANT_IDS", None)
    monkeypatch.setattr(settings, "KNOWLEDGE_TENANT_ISOLATION", False)
    with acting_as(ALICE):
        assert knowledge_tenants() is None  # the old behaviour is one setting away


def test_deleting_is_limited_to_your_own_tenant_unless_you_administer_the_system(monkeypatch):
    monkeypatch.setattr(settings, "RAG_TENANT_IDS", None)
    monkeypatch.setattr(settings, "KNOWLEDGE_TENANT_ISOLATION", True)
    assert _readable(ALICE) == ["acme", "public"] and _deletable(ALICE) == ["acme"]  # may read the shared corpus, may not delete it
    assert _deletable(ADMIN) == ["acme", "public"]


def test_an_upload_is_owned_by_the_uploaders_tenant_and_cannot_overwrite_anothers(tmp_path):
    embedder = FakeEmbedder()
    data = docx_bytes(SECTIONED)
    run_upload(embedder, data, category="msa", tmp_path=tmp_path, tenant_id="acme")
    assert {c.metadata["tenant_id"] for c in embedder.written[-1][1]} == {"acme"}
    assert run_upload(embedder, data, category="msa", tmp_path=tmp_path, tenant_id="acme")["status"] == "unchanged"  # the owner may re-upload
    with pytest.raises(UploadError, match="msa/contract.docx"):
        run_upload(embedder, data, category="msa", tmp_path=tmp_path, tenant_id="globex")  # the same key from another tenant is refused
    assert embedder.pg.owners["msa/contract.docx"] == "acme"
    embedder.pg.owners["policy/shared.docx"] = "public"
    with pytest.raises(UploadError):
        run_upload(embedder, data, name="shared.docx", category="policy", tmp_path=tmp_path, tenant_id="acme")  # nor the shared corpus
