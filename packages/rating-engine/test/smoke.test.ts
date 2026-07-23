import { describe, expect, it } from 'vitest';
import { DEFAULT_PARAMS, validateParams } from '../src/index.js';

describe('smoke', () => {
  it('exposes DEFAULT_PARAMS with the spec-anchored mu0', () => {
    expect(DEFAULT_PARAMS.mu0).toBe(1000);
  });

  it('DEFAULT_PARAMS passes validateParams', () => {
    expect(() => validateParams(DEFAULT_PARAMS)).not.toThrow();
  });
});
