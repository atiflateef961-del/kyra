import type { Config } from 'tailwindcss';
import defaultTheme from 'tailwindcss/defaultTheme';
import tailwindcssAnimate from 'tailwindcss-animate';

const config: Config = {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
    './components/**/*.{js,ts,jsx,tsx}',
    './lib/**/*.{js,ts,jsx,tsx}',
    './types/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: '#1E3A8A',
        accent: '#22C55E',
        backgroundLight: '#E6E9EF',
        backgroundDark: '#0A0F0D',
        backgroundDarkAlt: '#111714',
      },
      boxShadow: {
        neomorphLight: '8px 8px 15px #c1c4c9, -8px -8px 15px #ffffff',
        neomorphDark: '8px 8px 15px #080a0c, -8px -8px 15px #101416',
      },
    },
    fontFamily: { sans: ['Space Grotesk', 'Avenir Next', 'Segoe UI', ...defaultTheme.fontFamily.sans] },
  },
  plugins: [tailwindcssAnimate],
} as Config;

export default config;
