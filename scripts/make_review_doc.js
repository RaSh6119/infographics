// Arrange rendered pages from runs/ into a Word file for review: one page per prompt, models as
// rows, setups as columns.
//
//   npm install                                   (once, installs the docx library)
//   node scripts/make_review_doc.js --prompts data/prompts/dev_set.jsonl --out results/review/dev.docx
//   node scripts/make_review_doc.js --prompts data/prompts/clinic_set.jsonl --models qwen3.5-9b \
//        --out results/review/qwen_clinic.docx --title "Qwen3.5-9B on the clinic prompts"
//
// Options:
//   --prompts FILE   the prompt set the runs used (required); runs are found as
//                    runs/<setup>__<model>__<file name without .jsonl>/
//   --out FILE       the .docx to write (required). results/review/ is gitignored.
//   --models A,B     model names as in the run folders (default: every model with runs for this set)
//   --setups A,B     default: s1_zero_shot,s2_few_shot
//   --sample N       which sample to show (default 1)
//   --title TEXT     cover title (default: "Setups 1 and 2 on <set>")
//   --note TEXT      an extra line on the cover, e.g. "Draft labels, not for sharing outside the team."
//
// Model settings on the cover come from each run's run.json. Pages that failed to render are
// shown with a red note giving the reason, since their official OCR score is 0.

const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, WidthType,
  AlignmentType, HeadingLevel, BorderStyle, ShadingType, Footer, PageNumber,
} = require("docx");

const ROOT = path.resolve(__dirname, "..");

function parseArgs(argv) {
  const args = { setups: "s1_zero_shot,s2_few_shot", sample: "1" };
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, "");
    if (!["prompts", "out", "models", "setups", "sample", "title", "note"].includes(key) || argv[i + 1] === undefined) {
      fail(`unknown or incomplete option ${argv[i]}`);
    }
    args[key] = argv[i + 1];
  }
  if (!args.prompts || !args.out) fail("--prompts and --out are required");
  return args;
}

function fail(message) {
  console.error(`error: ${message}\nSee the comment at the top of scripts/make_review_doc.js for usage.`);
  process.exit(1);
}

const args = parseArgs(process.argv.slice(2));
const SET = path.basename(args.prompts, ".jsonl");
const SETUPS = args.setups.split(",");
const SETUP_LABELS = { s1_zero_shot: "Setup 1: zero-shot", s2_few_shot: "Setup 2: few-shot",
                       s3_rag_icons: "Setup 3: RAG + icons", s4_direct_image: "Setup 4: direct image" };
const SETUP_DESCRIPTIONS = {
  s1_zero_shot: "system prompt (style guide in words) + the prompt.",
  s2_few_shot: "the same, plus 3 reference pages from the HIV treatment PDF (14E, 5E, 10E) as style examples.",
};
const TYPE_NAMES = { statistical: "Statistical", timeline: "Timeline", process: "Process",
                     comparison: "Comparison", list: "List" };
// Display order and names for the models we know; others are shown as named in their run folder.
const KNOWN_MODELS = [
  ["gpt-5.5", "GPT-5.5"], ["claude-opus-5.5", "Claude Opus 5.5"], ["gemini-3.1-pro", "Gemini 3.1 Pro"],
  ["qwen3.5-9b", "Qwen3.5-9B"], ["gemma4-e4b", "Gemma 4 E4B"],
];
const label = (model) => (KNOWN_MODELS.find(([name]) => name === model) || [, model])[1];

const promptsPath = path.resolve(ROOT, args.prompts);
if (!fs.existsSync(promptsPath)) fail(`prompts file not found: ${args.prompts}`);
const prompts = fs.readFileSync(promptsPath, "utf8").split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l));
const titleOf = (p) => (p.prompt.match(/^Title: (.*)$/m) || [, p.id])[1];

// Which models have runs for this prompt set, and their settings from run.json.
const runDir = (setup, model) => path.join(ROOT, "runs", `${setup}__${model}__${SET}`);
const found = new Set();
for (const dir of fs.existsSync(path.join(ROOT, "runs")) ? fs.readdirSync(path.join(ROOT, "runs")) : []) {
  const [setup, model, set] = dir.split("__");
  if (set === SET && SETUPS.includes(setup)) found.add(model);
}
let MODELS = args.models ? args.models.split(",") : [...found];
const rank = (m) => { const i = KNOWN_MODELS.findIndex(([name]) => name === m); return i < 0 ? 99 : i; };
MODELS.sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
if (!MODELS.length) fail(`no runs found for ${SET} in runs/`);

function settingsOf(model) {
  for (const setup of SETUPS) {
    const file = path.join(runDir(setup, model), "run.json");
    if (!fs.existsSync(file)) continue;
    const c = JSON.parse(fs.readFileSync(file, "utf8")).config;
    const mc = c.model_config || {};
    const parts = [mc.checkpoint || c.checkpoint];
    if (mc.quantization || c.quantization) parts.push(mc.quantization || c.quantization);
    parts.push(c.temperature == null ? "provider's default temperature" : `temperature ${c.temperature}`);
    const extra = mc.extra_body || {};
    if (extra.reasoning_effort) parts.push(`reasoning effort ${extra.reasoning_effort}`);
    if (mc.effort) parts.push(`effort ${mc.effort}`);
    if (extra.chat_template_kwargs && extra.chat_template_kwargs.enable_thinking === false) parts.push("thinking off");
    return `${label(model)} (${parts.join(", ")})`;
  }
  return `${label(model)} (no runs found)`;
}

// Page layout: US Letter portrait, 0.5" margins, two 3.75" columns.
const PAGE = { size: { width: 12240, height: 15840 }, margin: { top: 720, bottom: 720, left: 720, right: 720 } };
const COL = Math.floor(10800 / SETUPS.length);
const IMG_W = Math.round((COL / 1440) * 96 * 0.9);  // 90% of the column, in pixels at 96 dpi
const NAVY = "08344C";
const thin = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
const borders = { top: thin, bottom: thin, left: thin, right: thin };

const pngSize = (buf) => ({ width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) });
const small = (text, color = "595959") => new TextRun({ text, size: 16, color });

function cell(children, shade) {
  return new TableCell({
    width: { size: COL, type: WidthType.DXA }, borders, children,
    margins: { top: 60, bottom: 60, left: 80, right: 80 },
    ...(shade ? { shading: { fill: shade, type: ShadingType.CLEAR, color: "auto" } } : {}),
  });
}

function reasonOf(failure) {
  if (failure.kind === "broken_asset" && /fonts\.googleapis/.test(failure.detail)) return "loads Google Fonts from the web";
  if (failure.kind === "blank") return "blank page";
  if (failure.kind === "no_html") return "reply had no HTML";
  return failure.kind.replace(/_/g, " ");
}

function imageCell(model, setup, prompt) {
  const dir = path.join(runDir(setup, model), prompt.id, `sample_${args.sample}`);
  const recordFile = path.join(dir, "record.json");
  if (!fs.existsSync(recordFile)) {
    return cell([new Paragraph({ alignment: AlignmentType.CENTER, children: [small("Not run")] })]);
  }
  const record = JSON.parse(fs.readFileSync(recordFile, "utf8"));
  const render = record.files && record.files.render ? path.join(dir, record.files.render) : null;
  const children = [];
  if (render && fs.existsSync(render)) {
    const data = fs.readFileSync(render);
    const size = pngSize(data);
    children.push(new Paragraph({ alignment: AlignmentType.CENTER, children: [new ImageRun({
      type: "png", data,
      transformation: { width: IMG_W, height: Math.round(IMG_W * size.height / size.width) },
      altText: { title: `${model} ${setup} ${prompt.id}`, description: `Render of ${prompt.id}`, name: prompt.id },
    })] }));
  } else {
    children.push(new Paragraph({ alignment: AlignmentType.CENTER, children: [small("No screenshot")] }));
  }
  const notes = [];
  if (!record.render.ok) notes.push(`Official score 0: ${[...new Set(record.render.failures.map(reasonOf))].join(", ")}`);
  if (record.extra && record.extra.finish_reason === "length") notes.push("cut off at the token limit");
  if (notes.length) {
    children.push(new Paragraph({ alignment: AlignmentType.CENTER, children: [small(notes.join("; "), "EB4F41")] }));
  }
  return cell(children);
}

const bold = (text) => new TextRun({ text, bold: true });
const coverLine = (key, text) => new Paragraph({ spacing: { after: 60 }, children: [bold(`${key}: `), new TextRun(text)] });

const children = [
  new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun(args.title || `Setups 1 and 2 on ${SET}`)] }),
  new Paragraph({ spacing: { after: 120 }, children: [new TextRun(
    `${prompts.length} prompts x ${MODELS.length} model${MODELS.length > 1 ? "s" : ""} x ${SETUPS.length} setups, ` +
    `sample ${args.sample}. One page per prompt; ${MODELS.length > 1 ? "rows are models, " : ""}columns are setups.`)] }),
  ...SETUPS.filter((s) => SETUP_DESCRIPTIONS[s]).map((s) => coverLine(SETUP_LABELS[s] || s, SETUP_DESCRIPTIONS[s])),
  coverLine("Prompts", path.relative(ROOT, promptsPath).replace(/\\/g, "/")),
  coverLine("Models", MODELS.length === 1 ? settingsOf(MODELS[0]) : ""),
  ...(MODELS.length > 1 ? MODELS.map((m) => new Paragraph({ spacing: { after: 40 }, indent: { left: 360 },
    children: [new TextRun(settingsOf(m))] })) : []),
  coverLine("Required text", "listed under each prompt's title; every phrase should appear on the page exactly as given."),
  coverLine("Red notes", "pages that failed to render score 0 on the official OCR score; the reason is given."),
  ...(args.note ? [coverLine("Note", args.note)] : []),
];

prompts.forEach((prompt, i) => {
  children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true,
    children: [new TextRun(`${i + 1}. ${TYPE_NAMES[prompt.type] || prompt.type}: ${titleOf(prompt)}`)] }));
  children.push(new Paragraph({ spacing: { after: 120 }, children: [
    small(`${prompt.id}. Required text: ${prompt.required_text.join(" | ")}`)] }));

  const rows = [new TableRow({ tableHeader: true, children: SETUPS.map((s) =>
    cell([new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: SETUP_LABELS[s] || s, bold: true, color: "FFFFFF", size: 20 })] })], NAVY)) })];
  for (const model of MODELS) {
    rows.push(new TableRow({ cantSplit: true, children: SETUPS.map(() =>
      // keepNext holds the model's name on the same page as its images
      cell([new Paragraph({ keepNext: true, children: [new TextRun({ text: label(model), bold: true, size: 18, color: NAVY })] })], "EAF4F9")) }));
    rows.push(new TableRow({ cantSplit: true, children: SETUPS.map((s) => imageCell(model, s, prompt)) }));
  }
  children.push(new Table({ width: { size: COL * SETUPS.length, type: WidthType.DXA },
    columnWidths: SETUPS.map(() => COL), rows }));
});

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 20 } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", next: "Normal",
        run: { font: "Arial", size: 40, bold: true, color: NAVY },
        paragraph: { spacing: { before: 0, after: 240 }, keepNext: true } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Arial", size: 28, bold: true, color: NAVY },
        paragraph: { spacing: { before: 0, after: 60 }, keepNext: true, outlineLevel: 0 } },
    ],
  },
  sections: [{
    properties: { page: PAGE },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [new TextRun({ children: ["Page ", PageNumber.CURRENT], size: 16, color: "808080" })] })] }) },
    children,
  }],
});

const out = path.resolve(ROOT, args.out);
Packer.toBuffer(doc).then((buf) => {
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, buf);
  console.log(`wrote ${path.relative(ROOT, out)}: ${prompts.length} prompts, models ${MODELS.join(", ")} ` +
              `(${(buf.length / 1e6).toFixed(1)} MB)`);
});
