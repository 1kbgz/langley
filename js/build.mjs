<<<<<<< before updating
import * as esbuild from "esbuild";
import { transform } from "lightningcss";
=======
import { bundle } from "./tools/bundle.mjs";
import { bundle_css } from "./tools/css.mjs";
import { node_modules_external } from "./tools/externals.mjs";
>>>>>>> after updating
import { getarg } from "./tools/getarg.mjs";

import { transform } from "lightningcss";
import fs from "fs";
import cpy from "cpy";

const BUNDLES = [
  {
<<<<<<< before updating
    define: COMMON_DEFINE,
    entryPoints: ["src/ts/index.tsx"],
    packages: "external",
    format: "esm",
    jsx: "automatic",
    bundle: true,
    loader: {
      ".html": "text",
    },
    outfile: "dist/esm/index.js",
  },
  {
    define: COMMON_DEFINE,
    entryPoints: ["src/ts/index.tsx"],
    format: "esm",
    jsx: "automatic",
    bundle: true,
    loader: {
      ".html": "text",
    },
=======
    entryPoints: ["src/ts/index.ts"],
    plugins: [node_modules_external()],
    outfile: "dist/esm/index.js",
  },
  {
    entryPoints: ["src/ts/index.ts"],
>>>>>>> after updating
    outfile: "dist/cdn/index.js",
  },
];

<<<<<<< before updating
async function compile_css() {
  const process_path = (src_path, out_path) => {
    fs.mkdirSync(out_path, { recursive: true });
    fs.readdirSync(src_path, { withFileTypes: true }).forEach((entry) => {
      const input = `${src_path}/${entry.name}`;
      const output = `${out_path}/${entry.name}`;
      if (entry.isDirectory()) {
        process_path(input, output);
      } else if (entry.isFile() && entry.name.endsWith(".css")) {
        const source = fs.readFileSync(input);
        const { code } = transform({
          filename: entry.name,
          code: source,
          minify: !DEBUG,
          sourceMap: false,
        });
        fs.writeFileSync(output, code);
      }
    });
  };
  process_path("src/css", "dist/cdn");
  process_path("src/css", "dist/esm");
}

async function copy_html() {
=======
async function build() {
  // Bundle css
  await bundle_css();

  // Copy HTML
>>>>>>> after updating
  fs.mkdirSync("dist/html", { recursive: true });
  cpy("src/html/*", "dist/html");
  cpy("src/html/*", "dist/");

<<<<<<< before updating
async function copy_to_python() {
=======
  // Copy images
  fs.mkdirSync("dist/img", { recursive: true });
  cpy("src/img/*", "dist/img");

  await Promise.all(BUNDLES.map(bundle)).catch(() => process.exit(1));

  // Copy from dist to python
>>>>>>> after updating
  fs.mkdirSync("../langley/extension", { recursive: true });
  cpy("dist/**/*", "../langley/extension");
}

<<<<<<< before updating
async function build_all() {
  await copy_html();
  await compile_css();
  await Promise.all(BUILD.map((c) => esbuild.build(c))).catch(() =>
    process.exit(1),
  );
  await copy_to_python();
}

build_all();
=======
build();
>>>>>>> after updating
