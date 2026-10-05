import json


def test_digest():
    jsonl_text = '''{"id": 1234567890},{"id": 2}`
    results = []
    for line in jsonl_text.split('\n'):
        line = line.strip()
        if not line:
            continue

        try:
            data = json.loads(line)
            results.append(data)
        except ValueError as e:
            raise Exception(f"Invalid JSONL at line {len(results) + 1}: {e}")

    assert len(results) == 2