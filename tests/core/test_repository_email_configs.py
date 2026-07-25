import pytest


@pytest.mark.asyncio
async def test_add_and_list_email_configs(repo, sample_org):
    cfg = await repo.add_email_config(
        organization_id=sample_org["id"],
        indirizzo="test@example.com",
    )
    assert cfg["indirizzo"] == "test@example.com"
    assert cfg["is_active"] is True

    configs = await repo.list_email_configs(sample_org["id"])
    assert len(configs) == 1


@pytest.mark.asyncio
async def test_remove_email_config(repo, sample_org):
    await repo.add_email_config(
        organization_id=sample_org["id"],
        indirizzo="test@example.com",
    )
    removed = await repo.remove_email_config(sample_org["id"], "test@example.com")
    assert removed is True
    configs = await repo.list_email_configs(sample_org["id"])
    assert len(configs) == 0


@pytest.mark.asyncio
async def test_duplicate_email_config(repo, sample_org):
    await repo.add_email_config(
        organization_id=sample_org["id"],
        indirizzo="test@example.com",
    )
    with pytest.raises(Exception):
        await repo.add_email_config(
            organization_id=sample_org["id"],
            indirizzo="test@example.com",
        )


@pytest.mark.asyncio
async def test_email_config_org_isolation(repo, sample_org, other_org):
    await repo.add_email_config(
        organization_id=sample_org["id"],
        indirizzo="test@example.com",
    )
    configs = await repo.list_email_configs(other_org["id"])
    assert len(configs) == 0
