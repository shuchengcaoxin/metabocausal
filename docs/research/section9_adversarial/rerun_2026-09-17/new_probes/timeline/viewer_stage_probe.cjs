/* The HTML half of the PR #14 lifecycle timeline, measured by running the shipped code.
 *
 * `demo/genetic-insights/viewer.template.html` owns two things the python renderer does
 * not: its own `validate(b)`, used by the "load a snapshot" file input, and the stage
 * grouping that turns `evidence_stage` into the rendered lifecycle. Re-implementing
 * either here would measure this probe instead of the product, so both are LIFTED OUT OF
 * THE TEMPLATE VERBATIM by literal-text extraction and evaluated against the bundles
 * `probe_timeline.py` already wrote to artifacts/lifecycle/.
 *
 * Offline, deterministic, no browser, no network. Run after probe_timeline.py:
 *
 *     node docs/research/section9_adversarial/rerun_2026-09-17/new_probes/timeline/viewer_stage_probe.cjs
 *
 * Writes artifacts/viewer_stages.json and artifacts/viewer_stages.txt. Exits non-zero if
 * a lifted block cannot be found, because a silently skipped check is not a measurement.
 */

const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, "..", "..", "..", "..", "..", "..");
const TEMPLATE = path.join(REPO_ROOT, "demo", "genetic-insights", "viewer.template.html");
const LIFECYCLE = path.join(HERE, "artifacts", "lifecycle");

const template = fs.readFileSync(TEMPLATE, "utf8");

function lineStartingWith(prefix) {
  const line = template.split("\n").find((row) => row.trim().startsWith(prefix));
  if (line === undefined) {
    console.error("could not find the template line starting with: " + prefix);
    process.exit(2);
  }
  return line.trim();
}

function blockFrom(opening) {
  const start = template.indexOf(opening);
  if (start < 0) {
    console.error("could not find the template block: " + opening);
    process.exit(2);
  }
  let depth = 0;
  for (let index = start; index < template.length; index += 1) {
    if (template[index] === "{") depth += 1;
    if (template[index] === "}") {
      depth -= 1;
      if (depth === 0) return template.slice(start, index + 1);
    }
  }
  console.error("unbalanced braces after: " + opening);
  process.exit(2);
}

// --- the exact shipped source, lifted ---------------------------------------------
const ESC_LINE = lineStartingWith("const esc=");
const SAFE_URL_LINE = lineStartingWith("const safeURL=");
const STAGE_NAMES_LINE = lineStartingWith("const stageNames=");
const STAGE_ORDER_LINE = lineStartingWith("const stageOrder=");
const STAGES_LINE = lineStartingWith("const stages=");
const TIMELINE_LINE = lineStartingWith('$("timeline").innerHTML=');
const VALIDATE_BLOCK = blockFrom("function validate(b){");

const NODE_STUB = `
const __nodes={};
const $=id=>(__nodes[id]=__nodes[id]||{innerHTML:"",style:{setProperty(){}}});
`;

const runValidate = new Function(
  "bundle",
  `${ESC_LINE}\n${SAFE_URL_LINE}\n${VALIDATE_BLOCK}\nvalidate(bundle);\nreturn "passed";`
);

const runStages = new Function(
  "bundle",
  `${NODE_STUB}\n${ESC_LINE}\n${STAGE_NAMES_LINE}\n${STAGE_ORDER_LINE}\n${STAGES_LINE}\n${TIMELINE_LINE}\nreturn {stages: stages, html: __nodes["timeline"].innerHTML};`
);

// --- what the rendered timeline actually shows -------------------------------------

function readRendered(html) {
  const groups = [];
  const sectionPattern = /<section class="stage-group stage-([^"]*)">.*?<h3 class="stage-title">([^<]*)<small>([^<]*)<\/small><\/h3><div class="stage-events">(.*?)<\/div><\/section>/g;
  let match;
  while ((match = sectionPattern.exec(html)) !== null) {
    const events = [];
    const eventPattern = /data-event="([^"]*)"/g;
    let event;
    while ((event = eventPattern.exec(match[4])) !== null) events.push(event[1]);
    groups.push({
      stage: match[1],
      heading: match[2],
      range: match[3],
      events: events,
    });
  }
  return groups;
}

// --- run every bundle probe_timeline.py wrote --------------------------------------

const rows = [];
for (const caseId of fs.readdirSync(LIFECYCLE).sort()) {
  const bundlePath = path.join(LIFECYCLE, caseId, "bundle.json");
  if (!fs.existsSync(bundlePath)) continue;
  const bundle = JSON.parse(fs.readFileSync(bundlePath, "utf8"));

  let validate = "passed";
  try {
    runValidate(bundle);
  } catch (error) {
    validate = error.constructor.name + ": " + error.message;
  }

  let rendered = [];
  let renderError = "";
  try {
    rendered = readRendered(runStages(bundle).html);
  } catch (error) {
    renderError = error.constructor.name + ": " + error.message;
  }

  const shown = new Set(rendered.flatMap((group) => group.events));
  const dropped = bundle.events
    .map((event) => event.id)
    .filter((id) => !shown.has(id));

  rows.push({
    case: caseId,
    js_validate: validate,
    render_error: renderError,
    stage_groups: rendered.map((group) => ({
      stage: group.stage,
      heading: group.heading,
      range: group.range,
      events: group.events,
    })),
    events_in_bundle: bundle.events.length,
    events_rendered: shown.size,
    events_dropped: dropped,
  });
}

fs.writeFileSync(
  path.join(HERE, "artifacts", "viewer_stages.json"),
  JSON.stringify(
    {
      template: path.relative(REPO_ROOT, TEMPLATE).split(path.sep).join("/"),
      template_sha256: require("crypto").createHash("sha256").update(fs.readFileSync(TEMPLATE)).digest("hex"),
      lifted: {
        stageNames: STAGE_NAMES_LINE,
        stageOrder: STAGE_ORDER_LINE,
        stages: STAGES_LINE,
      },
      cases: rows,
    },
    null,
    2
  ) + "\n",
  "utf8"
);

const lines = [];
for (const row of rows) {
  lines.push("== " + row.case);
  lines.push("   viewer validate(): " + row.js_validate);
  if (row.render_error) lines.push("   render error: " + row.render_error);
  for (const group of row.stage_groups) {
    lines.push(
      "   stage " + group.stage + " -> heading " + JSON.stringify(group.heading) +
      " range " + JSON.stringify(group.range) + " events " + group.events.join(", ")
    );
  }
  lines.push(
    "   events in bundle " + row.events_in_bundle +
    ", rendered " + row.events_rendered +
    ", dropped [" + row.events_dropped.join(", ") + "]"
  );
}
fs.writeFileSync(path.join(HERE, "artifacts", "viewer_stages.txt"), lines.join("\n") + "\n", "utf8");
console.log(lines.join("\n"));
