import type { Config } from 'tailwindcss';

export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        ink: '#0c0d10',
        steel: '#1f232d',
        fog: '#f6f7fb',
        brand: '#5b7cfa',
        aurora: '#30d5c8'
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(91, 124, 250, 0.2), 0 12px 30px rgba(12, 13, 16, 0.25)'
      }
    }
  },
  plugins: []
} satisfies Config;
