import { Hono } from "hono";
import { cors } from "hono/cors";
import { spawn } from "node:child_process";
import { resolve } from "node:path";

const PROJECT_ROOT = resolve(import.meta.dir, "..", "..");
const PYTHON = process.env.GPLATES_PYTHON ?? "python";
const RECONSTRUCT_SCRIPT = resolve(PROJECT_ROOT, "scripts/reconstruct.py");
const GLOBE_SCRIPT = resolve(PROJECT_ROOT, "scripts/globe.py");
const MODEL_DIR = process.env.GPLATES_MODEL_DIR ?? resolve(PROJECT_ROOT, "models/muller2022");

type ReconstructResult = {
  present: [number, number];
  age: number;
  paleo: [number, number];
  plate_id: number;
};

function runPython<T>(script: string, args: string[]): Promise<T> {
  return new Promise((resolveP, rejectP) => {
    const child = spawn(PYTHON, [script, ...args, MODEL_DIR], { cwd: PROJECT_ROOT });
    const out: Buffer[] = [];
    let stderr = "";
    child.stdout.on("data", (b) => out.push(b));
    child.stderr.on("data", (b) => (stderr += b));
    child.on("error", rejectP);
    child.on("close", (code) => {
      if (code !== 0) return rejectP(new Error(stderr || `python exited ${code}`));
      const text = Buffer.concat(out).toString("utf8");
      try {
        resolveP(JSON.parse(text) as T);
      } catch {
        rejectP(new Error(`bad json from python (${text.length} bytes)`));
      }
    });
  });
}

const runReconstruct = (lat: number, lon: number, age: number) =>
  runPython<ReconstructResult>(RECONSTRUCT_SCRIPT, [String(lat), String(lon), String(age)]);

const runGlobe = (age: number) =>
  runPython<{ type: "FeatureCollection"; features: unknown[] }>(GLOBE_SCRIPT, [String(age)]);

const app = new Hono();

app.use("*", cors());

app.get("/", (c) =>
  c.json({
    ok: true,
    endpoints: ["/reconstruct?lat=&lng=&age=", "/globe/vector?age="],
  }),
);

app.get("/globe/vector", async (c) => {
  const age = Number(c.req.query("age"));
  if (!Number.isFinite(age) || age < 0) {
    return c.json({ error: "age must be a non-negative number (Ma)" }, 400);
  }

  try {
    const fc = await runGlobe(age);
    c.header("Cache-Control", "public, max-age=86400");
    return c.json(fc);
  } catch (e) {
    return c.json({ error: (e as Error).message }, 500);
  }
});

app.get("/reconstruct", async (c) => {
  const lat = Number(c.req.query("lat"));
  const lng = Number(c.req.query("lng"));
  const age = Number(c.req.query("age"));

  if (!Number.isFinite(lat) || lat < -90 || lat > 90) {
    return c.json({ error: "lat must be a number in [-90, 90]" }, 400);
  }
  if (!Number.isFinite(lng) || lng < -180 || lng > 180) {
    return c.json({ error: "lng must be a number in [-180, 180]" }, 400);
  }
  if (!Number.isFinite(age) || age < 0) {
    return c.json({ error: "age must be a non-negative number (Ma)" }, 400);
  }

  try {
    const result = await runReconstruct(lat, lng, age);
    return c.json(result);
  } catch (e) {
    return c.json({ error: (e as Error).message }, 500);
  }
});

export default {
  port: Number(process.env.PORT ?? 3000),
  fetch: app.fetch,
};
