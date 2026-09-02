/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        fpt: {
          blue: '#005697',
          orange: '#F37021',
          green: '#10B981',
          bg: '#F8F9FA',
          'text-main': '#212529',
          'text-sub': '#495057',
        },
        brand: {
          50: '#f0f7ff',
          100: '#e0effe',
          500: '#005697',
          600: '#004880',
          700: '#005697',
          800: '#003e6d',
          900: '#002949',
        },
      },
    },
  },
  plugins: [],
};
