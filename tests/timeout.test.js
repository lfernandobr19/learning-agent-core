import test from 'node:test';
import { strict as assert } from 'node:assert';

test('Teste com timeout', async (t) => {
  await new Promise((resolve) => setTimeout(resolve, 1000));
  assert.ok(true, 'Teste com timeout passou');
}, { timeout: 2000 });