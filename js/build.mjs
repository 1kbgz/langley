import * as esbuild from "esbuild";
import { lessLoader } from "esbuild-plugin-less";
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
    plugins: [lessLoader()],
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
    plugins: [lessLoader()],
    format: "esm",
    jsx: "automatic",
    bundle: true,
    loader: {
      ".html": "text",
    },
    outfile: "dist/cdn/index.js",
  },
];

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
  await Promise.all(BUILD.map((c) => esbuild.build(c))).catch(() =>
    process.exit(1),
  );
  await copy_to_python();
}

build_all();
