/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // Light-theme only (per Change C plan). The `darkMode: 'class'` flag is left
  // off so accidental `dark:` variants don't escape into the build.
  theme: {
    extend: {
      colors: {
        // Aliases preserved so the existing `text-signal-green` / etc. classes
        // sprinkled across *EnhancedDetail.tsx, chart options, and badge
        // presets remap to the new light-theme accents without a giant
        // search-replace. Hex values come from Tailwind's emerald-600 /
        // amber-600 / rose-600 to stay in palette family.
        signal: {
          green: '#059669',
          yellow: '#d97706',
          red: '#e11d48',
        },
      },
      fontFamily: {
        sans: [
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          '"PingFang TC"',
          '"Microsoft JhengHei"',
          'sans-serif',
        ],
      },
    },
  },
  plugins: [],
};
