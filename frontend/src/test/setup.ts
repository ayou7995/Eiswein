import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// jsdom 25 ships without ResizeObserver; lightweight-charts and any component
// that observes layout needs one. A minimal no-op stub keeps render() happy
// without a heavyweight polyfill dependency.
class StubResizeObserver implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
if (typeof globalThis.ResizeObserver === 'undefined') {
  Object.defineProperty(globalThis, 'ResizeObserver', {
    value: StubResizeObserver,
    configurable: true,
  });
}

afterEach(() => {
  cleanup();
});
