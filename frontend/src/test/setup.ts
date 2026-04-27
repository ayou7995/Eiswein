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

// jsdom 25 also lacks `matchMedia`, which lightweight-charts probes via
// fancy-canvas to track device-pixel-ratio changes. A no-op stub is
// enough for tests that only mount-and-render the chart.
if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    value: (query: string): MediaQueryList => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
    configurable: true,
  });
}

afterEach(() => {
  cleanup();
});
