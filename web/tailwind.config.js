import preset from "@cyberdeck/ui/tailwind-preset";

/** @type {import('tailwindcss').Config} */
export default {
  presets: [preset],
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
    "./node_modules/@cyberdeck/ui/dist/**/*.js",
  ],
  theme: {
    container: { center: true, padding: "2rem", screens: { "2xl": "1400px" } },
    extend: {},
  },
};
