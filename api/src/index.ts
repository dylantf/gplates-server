import { Hono } from "hono";
import { cors } from "hono/cors";
import { spawn } from "node:child_process";
import { mkdir, readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";

const PROJECT_ROOT = resolve(import.meta.dir, "..", "..");
const PYTHON = process.env.GPLATES_PYTHON ?? "python";
const RECONSTRUCT_SCRIPT = resolve(PROJECT_ROOT, "scripts/reconstruct.py");
const TOPO_SCRIPT = resolve(PROJECT_ROOT, "scripts/render_topo.py");
const MODEL_DIR = process.env.GPLATES_MODEL_DIR ?? resolve(PROJECT_ROOT, "models/paleomap");
const TOPO_CACHE_DIR = resolve(PROJECT_ROOT, "data/cache/topo");

type ReconstructPoint = {
  present: [number, number];
  paleo: [number, number] | null;
  plate_id: number | null;
};

type ReconstructBatchResult = {
  age: number;
  results: ReconstructPoint[];
};

function runPython<T>(script: string, args: string[], stdinInput?: string): Promise<T> {
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
    if (stdinInput !== undefined) {
      child.stdin.write(stdinInput);
    }
    child.stdin.end();
  });
}

const runReconstructBatch = (age: number, points: [number, number][]) =>
  runPython<ReconstructBatchResult>(
    RECONSTRUCT_SCRIPT,
    [],
    JSON.stringify({ age, points }),
  );

async function fileExists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

function snapAge(age: number): number {
  // PaleoDEM files come at 5-Myr steps.
  return Math.round(age / 5) * 5;
}

async function renderTopo(age: number): Promise<{ path: string; snapped: number }> {
  const snapped = snapAge(age);
  await mkdir(TOPO_CACHE_DIR, { recursive: true });
  const out = resolve(TOPO_CACHE_DIR, `${String(snapped).padStart(3, "0")}.png`);
  if (await fileExists(out)) return { path: out, snapped };

  await new Promise<void>((resolveP, rejectP) => {
    const child = spawn(PYTHON, [TOPO_SCRIPT, String(snapped), out], { cwd: PROJECT_ROOT });
    let stderr = "";
    child.stderr.on("data", (b) => (stderr += b));
    child.on("error", rejectP);
    child.on("close", (code) =>
      code === 0 ? resolveP() : rejectP(new Error(stderr || `python exited ${code}`)),
    );
  });
  return { path: out, snapped };
}

const app = new Hono();

app.use("*", cors());

app.get("/", (c) =>
  c.json({
    ok: true,
    endpoints: [
      "POST /reconstruct  (body: {age, points: [[lat,lng],...]})",
      "GET  /globe/topo?age=",
    ],
  }),
);

app.get("/globe/topo", async (c) => {
  const age = Number(c.req.query("age"));
  if (!Number.isFinite(age) || age < 0 || age > 750) {
    return c.json({ error: "age must be a number in [0, 750] (Ma)" }, 400);
  }
  try {
    const { path, snapped } = await renderTopo(age);
    const png = await readFile(path);
    c.header("Content-Type", "image/png");
    c.header("Cache-Control", "public, max-age=86400");
    c.header("X-Snapped-Age", String(snapped));
    return c.body(png);
  } catch (e) {
    return c.json({ error: (e as Error).message }, 500);
  }
});

const MAX_BATCH = 10000;

function validatePoint(p: unknown, i: number): string | null {
  if (!Array.isArray(p) || p.length !== 2) return `points[${i}] must be [lat, lng]`;
  const [lat, lng] = p as [unknown, unknown];
  if (typeof lat !== "number" || !Number.isFinite(lat) || lat < -90 || lat > 90)
    return `points[${i}].lat must be a number in [-90, 90]`;
  if (typeof lng !== "number" || !Number.isFinite(lng) || lng < -180 || lng > 180)
    return `points[${i}].lng must be a number in [-180, 180]`;
  return null;
}

app.post("/reconstruct", async (c) => {
  let body: unknown;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "body must be JSON" }, 400);
  }
  if (!body || typeof body !== "object") return c.json({ error: "body must be an object" }, 400);
  const { age, points } = body as { age?: unknown; points?: unknown };

  if (typeof age !== "number" || !Number.isFinite(age) || age < 0) {
    return c.json({ error: "age must be a non-negative number (Ma)" }, 400);
  }
  if (!Array.isArray(points) || points.length === 0) {
    return c.json({ error: "points must be a non-empty array of [lat, lng]" }, 400);
  }
  if (points.length > MAX_BATCH) {
    return c.json({ error: `batch size ${points.length} exceeds max ${MAX_BATCH}` }, 400);
  }
  for (let i = 0; i < points.length; i++) {
    const err = validatePoint(points[i], i);
    if (err) return c.json({ error: err }, 400);
  }

  try {
    const result = await runReconstructBatch(age, points as [number, number][]);
    return c.json(result);
  } catch (e) {
    return c.json({ error: (e as Error).message }, 500);
  }
});

export default {
  port: Number(process.env.PORT ?? 3000),
  fetch: app.fetch,
};
