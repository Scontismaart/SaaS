import uuid

import pytest

pytestmark = pytest.mark.usefixtures("reset_db")

@pytest.mark.asyncio
async def test_create_document_and_add_chunks(repo, sample_org):
    doc = await repo.create_document(
        organization_id=sample_org["id"],
        nome="menu_estivo.pdf",
        tipo="upload",
        fonte="dashboard",
    )
    assert doc["nome"] == "menu_estivo.pdf"

    chunk = await repo.add_chunk(
        organization_id=sample_org["id"],
        document_id=doc["id"],
        chunk_index=0,
        content="Antipasto misto della casa: 12€",
        embedding=[0.1] * 384,
        metadata={"fonte": "menu_estivo.pdf"},
    )
    assert chunk["chunk_index"] == 0
    assert chunk["content"] == "Antipasto misto della casa: 12€"


@pytest.mark.asyncio
async def test_search_similar_returns_chunks(repo, sample_org):
    doc = await repo.create_document(
        organization_id=sample_org["id"],
        nome="menu.pdf", tipo="upload",
    )
    await repo.add_chunk(
        organization_id=sample_org["id"], document_id=doc["id"],
        chunk_index=0, content="Pizza margherita: 8€",
        embedding=[0.1] * 384,
    )
    await repo.add_chunk(
        organization_id=sample_org["id"], document_id=doc["id"],
        chunk_index=1, content="Pasta carbonara: 12€",
        embedding=[0.2] * 384,
    )

    results = await repo.search_similar(
        organization_id=sample_org["id"],
        embedding=[0.15] * 384,
        k=2,
    )
    assert len(results) >= 1
    contents = [r["content"] for r in results]
    assert any("Pizza" in c or "Pasta" in c for c in contents)


@pytest.mark.asyncio
async def test_document_chunk_cross_tenant_trigger(repo, sample_org, other_org):
    doc = await repo.create_document(
        organization_id=sample_org["id"],
        nome="doc1.pdf", tipo="upload",
    )
    with pytest.raises(Exception, match="organization_id mismatch"):
        await repo.add_chunk(
            organization_id=other_org["id"],
            document_id=doc["id"],
            chunk_index=0, content="test",
            embedding=[0.1] * 384,
        )


@pytest.mark.asyncio
async def test_list_documents(repo, sample_org):
    await repo.create_document(
        organization_id=sample_org["id"],
        nome="doc1.pdf", tipo="upload",
    )
    await repo.create_document(
        organization_id=sample_org["id"],
        nome="doc2.pdf", tipo="upload",
    )
    docs = await repo.list_documents(sample_org["id"])
    assert len(docs) == 2


@pytest.mark.asyncio
async def test_count_chunks(repo, sample_org, other_org):
    doc = await repo.create_document(organization_id=sample_org["id"], nome="doc.pdf", tipo="upload")
    await repo.add_chunk(organization_id=sample_org["id"], document_id=doc["id"],
                         chunk_index=0, content="c1", embedding=[0.1] * 384)
    await repo.add_chunk(organization_id=sample_org["id"], document_id=doc["id"],
                         chunk_index=1, content="c2", embedding=[0.2] * 384)
    assert await repo.count_chunks(sample_org["id"]) == 2
    assert await repo.count_chunks(other_org["id"]) == 0


@pytest.mark.asyncio
async def test_list_sources_groups_by_document(repo, sample_org):
    doc = await repo.create_document(organization_id=sample_org["id"], nome="menu.pdf", tipo="upload", fonte="dashboard")
    await repo.add_chunk(organization_id=sample_org["id"], document_id=doc["id"],
                         chunk_index=0, content="c1", embedding=[0.1] * 384)
    await repo.add_chunk(organization_id=sample_org["id"], document_id=doc["id"],
                         chunk_index=1, content="c2", embedding=[0.2] * 384)
    fonti = await repo.list_sources(sample_org["id"])
    assert len(fonti) == 1
    assert fonti[0]["nome"] == "menu.pdf"
    assert fonti[0]["chunk"] == 2
    assert str(fonti[0]["id"]) == str(doc["id"])


@pytest.mark.asyncio
async def test_delete_document_org_scoped(repo, sample_org, other_org):
    doc = await repo.create_document(organization_id=sample_org["id"], nome="doc.pdf", tipo="upload")
    await repo.add_chunk(organization_id=sample_org["id"], document_id=doc["id"],
                         chunk_index=0, content="c1", embedding=[0.1] * 384)
    # org sbagliata non tocca nulla
    assert await repo.delete_document(other_org["id"], doc["id"]) == 0
    # org giusta elimina documento + chunk via cascade
    assert await repo.delete_document(sample_org["id"], doc["id"]) == 1
    assert await repo.count_chunks(sample_org["id"]) == 0
