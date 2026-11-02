import { buildArgs, episodeFor, missingHint, prefill } from "./video_step_defaults.js";
// Staged renderer for NEWTECONS VIDEO tabs 06–08. Every operation is sent as typed JSON.
const OPS = {
  "06": { "SeedVR2 plan (preview)": ["seedvr2.plan", ["out", "segments_root", "reads", "tail_map"]],
          "SeedVR2 execute (dry-run only)": ["seedvr2.execute", ["plan"]] },
  "07": { "Post logo": ["post.logo", ["video", "out"]] },
  "08": { "Timing words": ["timing.words", ["dialogue", "out"]],
          "Captions burn": ["captions.burn", ["video", "timing", "timing_receipt", "subtitles", "font", "wav", "out"]],
          "Edit assemble": ["edit.assemble", ["edl", "out_dir", "tag", "base"]] },
};

export function renderVideoStep(step, m, api, el, refresh) {
  const operations = OPS[step.code];
  if (!operations) return null;
  const children = [el("h3", { text: `${step.code} ${step.label} · NEWTECONS LIVE-ACTION` }),
    el("p", { text: "Preview mặc định. Runner chỉ chạy trong workspace NEWTECONS; không có cờ GPU approval hoặc final." })];
  const select = el("select", { "aria-label": "Tác vụ" }, Object.keys(operations).map((name) => el("option", { value: name, text: name })));
  children.push(select);
  let targetSelect, tileSelect, logoToggle;
  if (step.code === "06") {
    targetSelect = el("select", { "aria-label": "Target (recipe assertion)" }, ["1920x1080", "2560x1440"].map((v) => el("option", { value: v, text: v })));
    tileSelect = el("select", { "aria-label": "Tile (recipe assertion)" }, [512, 768, 1024].map((v) => el("option", { value: String(v), text: String(v) })));
    children.push(el("p", { text: "Target/tile là giá trị recipe hiển thị để so khớp; CLI jjv seedvr2 plan không nhận override. NEWTECONS vẫn cần pilot/recipe đã duyệt." }), targetSelect, tileSelect);
  }
  if (step.code === "07") { logoToggle = el("input", { type: "checkbox", checked: true, "data-logo-enabled": "1" }); children.push(el("label", {}, logoToggle, " Bật logo")); }
  if (step.code === "08") children.push(el("label", {}, "Kiểu highlight: ",
    el("select", { "aria-label": "Kiểu highlight" }, el("option", { value: "single_word", text: "Tô sáng từng từ (được hỗ trợ)" }),
      el("option", { value: "cumulative", text: "Tích lũy (chưa có trong jjv)", disabled: true }))));
  const fields = el("div", { class: "ntd-step-job-fields" });
  const status = el("pre", { text: "Receipt gần nhất: chưa có yêu cầu từ tab này." });
  const log = el("pre", { class: "ntd-step-job-log", text: "Log: chưa có." });
  const preview = el("div", {});
  const jobKey = () => `ntc-step-job:${m.episode_id}:${m.shot}:${operations[select.value][0]}`;
  async function showSavedJob() {
    status.textContent = "Đang đọc trạng thái receipt gần nhất…"; log.textContent = ""; preview.replaceChildren();
    const id = localStorage.getItem(jobKey());
    if (!id) { status.textContent = "Receipt gần nhất: chưa có yêu cầu từ tab này."; return; }
    try {
      const current = await (await fetch(api.apiURL(`/newtecons/step/run/${id}`), { cache: "no-store" })).json();
      status.textContent = `Receipt: ${current.receipt || "—"}\nStatus: ${current.status}\nExit: ${current.exit_code ?? "đang chạy"}`;
      log.textContent = current.log_tail || "Chưa có log.";
      if (current.preview_url) preview.append(el("video", { controls: true, src: api.apiURL(current.preview_url), style: "max-width:100%;max-height:320px" }));
    } catch (error) { status.textContent = `Không đọc được trạng thái receipt: ${error.message}`; }
  }
  let defaults = null;
  const defaultsUrl = new URL("./data/video/step_defaults.json", import.meta.url).href;
  const loadDefaults = () => defaults ? Promise.resolve(defaults) : fetch(defaultsUrl, { cache: "no-store" })
    .then((r) => r.ok ? r.json() : null).catch(() => null).then((d) => (defaults = d || {}));
  const episodeSlug = () => episodeFor(m, defaults);
  function renderFields() {
    const [, keys] = operations[select.value];
    fields.replaceChildren(...keys.map((key) => key === "out" && step.code === "06"
      ? el("input", { type: "hidden", name: key, value: "AUTO" })
      : el("label", { class: "ntd-f" }, el("span", { text: key }),
        el("input", { type: "text", name: key, autocomplete: "off", placeholder: `đường dẫn ${key}`,
          value: prefill(operations[select.value][0], m.shot, episodeSlug(), defaults)[key] || "" }))));
    if (step.code === "07") fields.append(el("input", { type: "hidden", name: "enabled", value: "true" }));
    if (step.code === "08" && select.value === "Captions burn") fields.append(el("input", { type: "hidden", name: "style", value: "single_word" }));
  }
  select.addEventListener("change", () => { renderFields(); showSavedJob(); }); renderFields(); children.push(fields);
  loadDefaults().then(() => renderFields()); // fill after the defaults table arrives (user edits happen later)
  showSavedJob();
  const button = el("button", { type: "button", text: "Chạy (preview)" });
  button.addEventListener("click", async () => {
    button.disabled = true; status.textContent = "Đang gửi yêu cầu…";
    try {
      const [verb] = operations[select.value];
      await loadDefaults();
      const raw = Object.fromEntries([...fields.querySelectorAll("input")].filter((i) => i.name).map((i) => [i.name, i.value]));
      const { args, missing } = buildArgs(verb, raw);
      if (missing.length) { status.textContent = missingHint(missing, Boolean(m.shot && defaults?.shots?.[m.shot])); return; }
      if (step.code === "07") args.enabled = Boolean(logoToggle.checked);
      if (step.code === "06") {
        args.target = targetSelect.value;
        args.tile_size = Number(tileSelect.value);
      }
      const episode = episodeSlug();
      if (!episode) throw new Error("Episode slug chưa được chọn trong metadata.");
      const response = await fetch(api.apiURL("/newtecons/step/run"), { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verb, shot: m.shot, episode, args }) });
      const queued = await response.json(); if (!response.ok) throw new Error(queued.error || `HTTP ${response.status}`);
      localStorage.setItem(jobKey(), queued.job_id);
      for (;;) {
        await new Promise((resolve) => setTimeout(resolve, 1200));
        const current = await (await fetch(api.apiURL(`/newtecons/step/run/${queued.job_id}`), { cache: "no-store" })).json();
        status.textContent = `Receipt: ${current.receipt || "—"}\nStatus: ${current.status}\nExit: ${current.exit_code ?? "đang chạy"}`;
        log.textContent = current.log_tail || "Đang chờ host runner.";
        preview.replaceChildren(); if (current.preview_url) preview.append(el("video", { controls: true, src: api.apiURL(current.preview_url), style: "max-width:100%;max-height:320px" }));
        if (["COMPLETE", "FAILED", "REJECTED", "SKIPPED", "UNCERTAIN"].includes(current.status)) break;
      }
      refresh?.();
    } catch (error) { status.textContent = `Từ chối/lỗi: ${error.message}`; }
    finally { button.disabled = false; }
  });
  children.push(button, status, log, preview);
  return el("section", { class: "ntd-step-job" }, children);
}
