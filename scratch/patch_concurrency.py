import pathlib

f = pathlib.Path('tests/concurrency/test_concurrency.py')
text = f.read_text('utf-8')

new_fixtures = """@pytest.fixture(scope="session")
def postgres_container():
    from testcontainers.postgres import PostgresContainer
    with PostgresContainer("postgres:16") as pg:
        yield pg

@pytest.fixture
async def pool(postgres_container):"""

text = text.replace('async def pool():', new_fixtures)
text = text.replace('pool = await asyncpg.create_pool(DB_DSN, min_size=5, max_size=20)', 'dsn = postgres_container.get_connection_url().replace("+psycopg2", "")\n    pool = await asyncpg.create_pool(dsn, min_size=5, max_size=20)')
text = text.replace('DROP TABLE IF EXISTS messages;', 'DROP TABLE IF EXISTS messages CASCADE;')
text = text.replace('DROP TABLE IF EXISTS organizations;', 'DROP TABLE IF EXISTS organizations CASCADE;')

f.write_text(text, 'utf-8')
