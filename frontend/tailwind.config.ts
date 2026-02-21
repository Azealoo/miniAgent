import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        klein: {
          DEFAULT: "#002FA7",
          50:  "#e6ecf9",
          100: "#c0ceef",
          200: "#96ade4",
          300: "#6b8cd9",
          400: "#4a72d0",
          500: "#2b59c8",
          600: "#1a4bbf",
          700: "#0d3db4",
          800: "#0030aa",
          900: "#002FA7",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "Roboto",
          "sans-serif",
        ],
        mono: ['"SF Mono"', '"Fira Code"', "Consolas", "monospace"],
      },
      animation: {
        "blink": "blink 1s step-end infinite",
      },
      keyframes: {
        blink: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0" },
        },
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};

export default config;
