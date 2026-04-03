import { build } from "esbuild";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const vendorDir = join(__dirname, "..", "dark", "vendor");

await build({
  stdin: {
    contents: `export { h, Fragment, hydrate, render } from "preact";`,
    resolveDir: __dirname,
  },
  bundle: true,
  format: "esm",
  platform: "browser",
  outfile: join(vendorDir, "preact-client.bundle.js"),
  minify: true,
});

console.log("Preact client bundle written.");
