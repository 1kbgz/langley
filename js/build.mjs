import * as esbuild from "esbuild";
import { transform } from "lightningcss";
import { getarg } from "./tools/getarg.mjs";
import fs from "fs";
import cpy from "cpy";

const DEBUG = getarg("--debug");

const COMMON_DEFINE = {
  global: "window",
  "process.env.DEBUG": `${DEBUG}`,
};

const BUILD = [
  {
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
    outfile: "dist/cdn/index.js",
  },
];

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
  fs.mkdirSync("dist/html", { recursive: true });
  cpy("src/html/*", "dist/html");
  cpy("src/html/*", "dist/");
}

async function copy_to_python() {
  fs.mkdirSync("../langley/extension", { recursive: true });
  cpy("dist/**/*", "../langley/extension");
}

async function build_all() {
  await copy_html();
  await compile_css();
  await Promise.all(BUILD.map((c) => esbuild.build(c))).catch(() =>
    process.exit(1),
  );
  await copy_to_python();
}

build_all();
