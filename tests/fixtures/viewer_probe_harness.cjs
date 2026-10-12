/* Regression harness for demo/genetic-insights/viewer.template.html (L2, L3, L6).
 *
 * Adapted from docs/research/section9_adversarial/rerun_2026-09-17/new_probes/timeline/
 * viewer_stage_probe.cjs: the shipped viewer's own `validate(b)` and stage-grouping
 * source lines are LIFTED OUT OF THE TEMPLATE VERBATIM by literal-text extraction and
 * evaluated, so this measures the product, not a re-implementation of it. The extracted
 * line set below matches the fixed template (adds UNRECOGNIZED_STAGE, knownStages,
 * unrecognizedEvents, renderedStages, eventsForStage; the fixed validate() block carries
 * its own parseEventDate and stage-order check).
 *
 * CLI: node viewer_probe_harness.cjs <bundle.json>
 * Prints one JSON line: {validate, stages, stages_error}.
 */
"use strict";
const fs = require("fs");
const path = require("path");

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const TEMPLATE = path.join(REPO_ROOT, "demo", "genetic-insights", "viewer.template.html");
const template = fs.readFileSync(TEMPLATE, "utf8");

function lineStartingWith(prefix) {
  const line = template.split("\n").find((row) => row.trim().startsWith(prefix));
  if (line === undefined) throw new Error("could not find the template line starting with: " + prefix);
  return line.trim();
}

function blockFrom(opening) {
  const start = template.indexOf(opening);
  if (start < 0) throw new Error("could not find the template block: " + opening);
  let depth = 0;
  for (let index = start; index < template.length; index += 1) {
    if (template[index] === "{") depth += 1;
    if (template[index] === "}") {
      depth -= 1;
      if (depth === 0) return template.slice(start, index + 1);
    }
  }
  throw new Error("unbalanced braces after: " + opening);
}

const ESC_LINE = lineStartingWith("const esc=");
const SAFE_URL_LINE = lineStartingWith("const safeURL=");
const VALIDATE_BLOCK = blockFrom("function validate(b){");

const STAGE_PREFIXES = [
  "const stageNames=",
  "const UNRECOGNIZED_STAGE=",
  "const stageOrder=",
  "const knownStages=",
  "const stages=",
  "const unrecognizedEvents=",
  "const eventsForStage=",
  "const chronologyRank=",
  "const renderedStages=",
];
const STAGE_LINES = STAGE_PREFIXES.map(lineStartingWith).join("\n");
const TIMELINE_LINE = lineStartingWith('$("timeline").innerHTML=');

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
  `${NODE_STUB}\n${ESC_LINE}\n${STAGE_LINES}\n${TIMELINE_LINE}\nreturn {stages: renderedStages, html: __nodes["timeline"].innerHTML};`
);

function readRendered(html) {
  const groups = [];
  const sectionPattern = /<section class="stage-group stage-([^"]*)">.*?<h3 class="stage-title">([^<]*)<small>([^<]*)<\/small><\/h3><div class="stage-events">(.*?)<\/div><\/section>/g;
  let match;
  while ((match = sectionPattern.exec(html)) !== null) {
    const events = [];
    const eventPattern = /data-event="([^"]*)"/g;
    let event;
    while ((event = eventPattern.exec(match[4])) !== null) events.push(event[1]);
    groups.push({ stage: match[1], heading: match[2], range: match[3], events: events });
  }
  return groups;
}

function probe(bundle) {
  let validate = "passed";
  try {
    runValidate(bundle);
  } catch (error) {
    validate = error.constructor.name + ": " + error.message;
  }
  let stages = null;
  let stagesError = null;
  try {
    const result = runStages(bundle);
    const rendered = readRendered(result.html);
    const shown = new Set(rendered.flatMap((group) => group.events));
    stages = {
      groups: rendered,
      events_in_bundle: bundle.events.length,
      events_rendered: shown.size,
      events_dropped: bundle.events.map((e) => e.id).filter((id) => !shown.has(id)),
    };
  } catch (error) {
    stagesError = error.constructor.name + ": " + error.message;
  }
  return { validate: validate, stages: stages, stages_error: stagesError };
}

module.exports = { probe: probe, runValidate: runValidate, runStages: runStages };

if (require.main === module) {
  const bundlePath = process.argv[2];
  const bundle = JSON.parse(fs.readFileSync(bundlePath, "utf8"));
  console.log(JSON.stringify(probe(bundle)));
}
