import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          900: "#1a2332",
          700: "#3a4358",
          500: "#5a6479",
          300: "#9aa0af"
        },
        paper: {
          DEFAULT: "#fafbff",
          deep: "#f5f3ff"
        },
        card: "#ffffff",
        brand: {
          50: "#f5f3ff",
          500: "#7c3aed",
          600: "#6d28d9",
          700: "#5b21b6"
        },
        ok: {
          bg: "#dcfce7",
          text: "#166534"
        },
        warn: {
          bg: "#fef3c7",
          text: "#92400e"
        },
        danger: {
          bg: "#fee2e2",
          text: "#991b1b"
        }
      },
      borderRadius: {
        card: "16px",
        pill: "9999px",
        soft: "10px"
      },
      boxShadow: {
        card: "0 2px 8px rgba(15,23,42,.04), 0 1px 2px rgba(15,23,42,.04)",
        cardH: "0 4px 16px rgba(15,23,42,.08)"
      },
      transitionDuration: {
        micro: "120ms",
        fast: "180ms",
        base: "240ms",
        slow: "320ms"
      },
      transitionTimingFunction: {
        std: "cubic-bezier(0.4, 0, 0.2, 1)",
        in: "cubic-bezier(0, 0, 0.2, 1)",
        out: "cubic-bezier(0.4, 0, 1, 1)",
        sharp: "cubic-bezier(0.4, 0, 0.6, 1)"
      }
    }
  },
  plugins: [animate]
};

export default config;
