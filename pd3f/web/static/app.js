"use strict";

const STORE = "pd3f-jobs";
const $ = (id) => document.getElementById(id);
// the text and decisions of the job on display
let shown = { text: "", decisions: [] };

function stored() {
  try {
    return JSON.parse(localStorage.getItem(STORE)) || [];
  } catch {
    return [];
  }
}

function store(list) {
  try {
    localStorage.setItem(STORE, JSON.stringify(list));
  } catch {
    // without storage, the list of jobs lasts as long as the page
  }
}

function say(text, error = false) {
  if ($("status").textContent === text) return;
  $("status").textContent = text;
  $("status").classList.toggle("error", error);
}

function listJobs() {
  const ul = $("jobs");
  ul.replaceChildren();
  for (const job of stored()) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = `#${job.id}`;
    a.textContent = `${job.filename} (${new Date(job.created).toLocaleString()})`;
    li.append(a);
    ul.append(li);
  }
}

function forget(id) {
  store(stored().filter((job) => job.id !== id));
  listJobs();
}

// the first of the browser's languages that the form offers
function preferLanguage() {
  const offered = [...$("lang").options].map((o) => o.value);
  const lang = navigator.languages
    .map((l) => l.slice(0, 2).toLowerCase())
    .find((l) => offered.includes(l));
  if (lang) $("lang").value = lang;
}

// each option as it would read, the chosen one first
function described(d) {
  const text = (i) => d.texts[i].replaceAll("\n", " ↵ ");
  const others = d.texts.map((_, i) => i).filter((i) => i !== d.chosen);
  return [`chosen: ${text(d.chosen)}`, ...others.map((i) => `other: ${text(i)}`)].join("\n");
}

// the marks of the uncertain decisions in the text's order; overlapping ones share a mark
function uncertain(decisions) {
  const marks = [];
  const placed = decisions.filter((d) => d.uncertain && d.start !== null);
  for (const d of placed.sort((a, b) => a.start - b.start)) {
    const last = marks.at(-1);
    if (last && d.start < last.end) {
      last.end = Math.max(last.end, d.end);
      last.decisions.push(d);
    } else {
      marks.push({ start: d.start, end: d.end, decisions: [d] });
    }
  }
  return marks;
}

// the text, with each uncertain decision in a <mark> that shows the options if asked for
function render() {
  // the offsets count characters, while a string's indices count UTF-16 code units
  const chars = Array.from(shown.text);
  const slice = (start, end) => chars.slice(start, end).join("");
  const marks = $("show-marks").checked ? uncertain(shown.decisions) : [];
  const out = $("text");
  out.replaceChildren();
  let at = 0;
  for (const m of marks) {
    out.append(slice(at, m.start));
    const mark = document.createElement("mark");
    mark.tabIndex = 0;
    mark.title = m.decisions.map(described).join("\n\n");
    mark.dataset.options = mark.title;
    mark.textContent = slice(m.start, m.end);
    out.append(mark);
    at = m.end;
  }
  out.append(slice(at));
}

function downloads(id, status) {
  const files = ["text.txt", "text.md", "decisions.json"];
  if (status.ocr_pages.length) files.push("ocr.pdf");
  for (let i = 1; i <= status.tables; i++) files.push(`tables/${i}.csv`);
  $("downloads").replaceChildren(
    ...files.map((name) => {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = `/jobs/${id}/${name}?download=1`;
      a.textContent = name;
      li.append(a);
      return li;
    }),
  );
}

function progress(status) {
  if (status.state !== "running" || !status.step) return status.state;
  if (!status.total) return status.step;
  return `${status.step}, page ${status.done} of ${status.total}`;
}

async function show(id) {
  // another job chosen meanwhile is shown instead
  const stale = () => location.hash !== `#${id}`;
  $("result").hidden = true;
  let status;
  for (;;) {
    const response = await fetch(`/jobs/${id}`);
    if (stale()) return;
    if (response.status === 404) {
      forget(id);
      say("This job does not exist (any more).", true);
      return;
    }
    status = await response.json();
    if (stale()) return;
    if (status.state === "done" || status.state === "failed") break;
    say(`${status.filename}: ${progress(status)}…`);
    await new Promise((resolve) => setTimeout(resolve, 1000));
    if (stale()) return;
  }
  if (status.state === "failed") {
    say(`${status.filename}: failed. ${status.error}`, true);
    return;
  }
  const [text, decisions] = await Promise.all([
    fetch(`/jobs/${id}/text.txt`).then((r) => r.text()),
    fetch(`/jobs/${id}/decisions.json`).then((r) => r.json()),
  ]);
  if (stale()) return;
  shown = { text, decisions };
  render();
  const ocr = status.ocr_pages.length
    ? ` OCR on pages ${status.ocr_pages.join(", ")}.`
    : "";
  $("summary").textContent =
    `${status.filename}: ${status.pages} pages, ${status.decisions} decisions, ` +
    `${status.uncertain} of them uncertain.${ocr}`;
  downloads(id, status);
  $("pdf-view").src = `/jobs/${id}/input.pdf`;
  $("result").hidden = false;
  say(`${status.filename}: done.`);
  $("result-title").focus();
}

function isPdf(file) {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

const form = $("upload");

form.addEventListener("dragover", (event) => {
  event.preventDefault();
  form.classList.add("dropping");
});

form.addEventListener("dragleave", (event) => {
  if (!form.contains(event.relatedTarget)) form.classList.remove("dropping");
});

form.addEventListener("drop", (event) => {
  event.preventDefault();
  form.classList.remove("dropping");
  const pdfs = new DataTransfer();
  for (const file of event.dataTransfer.files) if (isPdf(file)) pdfs.items.add(file);
  $("pdf").files = pdfs.files;
  const n = pdfs.files.length;
  if (n) say(`${n} PDF${n === 1 ? "" : "s"} chosen.`);
  else say("None of the dropped files is a PDF.", true);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const options = new FormData(form);
  const files = options.getAll("pdf");
  options.delete("pdf");
  const ids = [];
  for (const [i, file] of files.entries()) {
    say(`Uploading ${file.name} (${i + 1} of ${files.length})…`);
    const body = new FormData();
    for (const [name, value] of options) body.append(name, value);
    body.append("pdf", file);
    const response = await fetch("/jobs", { method: "POST", body });
    const job = await response.json();
    if (!response.ok) {
      say(`Upload of ${file.name} failed: ${job.error}`, true);
      break;
    }
    store([{ id: job.id, filename: file.name, created: Date.now() }, ...stored()]);
    ids.push(job.id);
  }
  listJobs();
  // after a failed upload, its message stays; the others are in the list
  if (ids.length === files.length) location.hash = ids[0];
});

$("show-marks").addEventListener("change", render);

$("copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(shown.text);
    say("The text is copied.");
  } catch {
    say("Copying failed; select the text and copy it by hand.", true);
  }
});

$("delete").addEventListener("click", async () => {
  const id = location.hash.slice(1);
  const response = await fetch(`/jobs/${id}`, { method: "DELETE" });
  if (!response.ok && response.status !== 404) {
    say(`Deleting failed: ${(await response.json()).error}`, true);
    return;
  }
  forget(id);
  $("result").hidden = true;
  $("pdf-view").removeAttribute("src");
  history.replaceState(null, "", location.pathname);
  say("The job is deleted.");
});

window.addEventListener("hashchange", () => {
  if (location.hash.length > 1) show(location.hash.slice(1));
});

preferLanguage();
listJobs();
if (location.hash.length > 1) show(location.hash.slice(1));
