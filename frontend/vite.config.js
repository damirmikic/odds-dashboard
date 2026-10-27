import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const here = fileURLToPath(new URL(".", import.meta.url));

// Hash of everything the bundle is built from, written into the build as source-hash.txt. The Python tests
// (BuildSyncTests, same algorithm) recompute it, so a source change committed without `npm run build` fails.
// Line endings are normalised: git may check the files out with CRLF.
function sourceHash() {
  const files = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else files.push(path);
    }
  };
  walk(join(here, "dashboard"));
  files.push(...["package.json", "package-lock.json", "vite.config.js"].map((name) => join(here, name)));
  const hash = createHash("sha256");
  for (const path of files.map((file) => relative(here, file).split(sep).join("/")).sort()) {
    const content = readFileSync(join(here, path)).toString("latin1").replaceAll("\r\n", "\n");
    hash.update(path, "utf8").update("\0").update(content, "latin1").update("\0");
  }
  return hash.digest("hex");
}

export default defineConfig({
  root: "dashboard",
  plugins: [
    react(),
    {
      name: "source-hash",
      apply: "build",
      generateBundle() {
        this.emitFile({ type: "asset", fileName: "source-hash.txt", source: `${sourceHash()}\n` });
      },
    },
  ],
  server: {
    port: 5175,
    proxy: {
      "/api": "http://127.0.0.1:8070",
    },
  },
  build: {
    outDir: "../../static/dashboard_build",
    emptyOutDir: true,
  },
});
