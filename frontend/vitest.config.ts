import path from "node:path";
import { configDefaults, defineConfig } from "vitest/config";

const oxcConfig = {
  jsx: {
    runtime: "automatic",
    importSource: "react",
  },
  tsconfig: {
    compilerOptions: {
      jsx: "react-jsx",
      jsxImportSource: "react",
    },
  },
} as const;

export default defineConfig({
  oxc: oxcConfig as never,
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    environmentOptions: {
      jsdom: {
        url: "http://127.0.0.1:3000/",
      },
    },
    exclude: [...configDefaults.exclude, "e2e/**"],
    setupFiles: ["./src/test/setup.ts"],
  },
});
