import pathlib
f = pathlib.Path('tests/whatsapp/test_concurrency.py')
text = f.read_text('utf-8')
text = text.replace('(id, name, messages_limit) VALUES ($1, 100)', "(id, name, messages_limit) VALUES ($1, 'Test', 100)")
text = text.replace('(id, messages_limit, messages_used_this_period) "\n                "VALUES ($1, $2, 0)', "(id, name, messages_limit, messages_used_this_period) \"\n                \"VALUES ($1, 'Test', $2, 0)")
f.write_text(text, 'utf-8')
