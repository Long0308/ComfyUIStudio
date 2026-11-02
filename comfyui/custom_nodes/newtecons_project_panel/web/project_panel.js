import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { assertLocalGraph, bindSnapshot, runSequential } from "./auto_run.js";

const fields = ["domain", "script_path", "shotlist_path", "asset_folder", "run_mode", "scene", "shot",
  "aspect", "generation_size", "output_resolution", "style", "no_image_mode", "min_duration"];
const livePanels = new Map();
let autoOwner = null;

async function contextHash() {
  const { output } = await app.graphToPrompt();
  return hashPrompt(output);
}
async function hashPrompt(output) {
  const graph = JSON.parse(JSON.stringify(output));
  for (const node of Object.values(graph)) {
    delete node._meta;
    if (node.class_type === "NewteconsProjectPanel") {
      for (const key of ["run_mode", "scene", "shot", "auto_shot", "auto_render_key"]) delete node.inputs[key];
    }
  }
  function canonical(value) {
    if (typeof value === "number") {
      if (!Number.isFinite(value)) throw new Error("Graph có số không hữu hạn");
      const buffer = new ArrayBuffer(8);
      new DataView(buffer).setFloat64(0, value === 0 ? 0 : value, false);
      return `n${Array.from(new Uint8Array(buffer), (x) => x.toString(16).padStart(2, "0")).join("")}`;
    }
    if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
    if (value && typeof value === "object") {
      return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
    }
    return JSON.stringify(value);
  }
  const bytes = new TextEncoder().encode(canonical(graph));
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (x) => x.toString(16).padStart(2, "0")).join("");
}

function element(tag, text, parent) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  parent?.append(el);
  return el;
}
async function get(route, query = {}) {
  const response = await api.fetchApi(`${route}?${new URLSearchParams(query)}`, { cache: "no-store" });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}
function mark(node) {
  node.graph?.change?.();
  app.canvas?.setDirty(true, true);
}
function installCSS() {
  if (document.getElementById("newtecons-project-panel-css")) return;
  const css = element("style");
  css.id = "newtecons-project-panel-css";
  css.textContent = `
  .nt-project-panel,.nt-project-browser{font:13px/1.4 system-ui,sans-serif;color:#eee4c5;background:#17150f;
    border:1px solid #95762c;border-radius:9px;padding:12px;box-sizing:border-box}
  .nt-project-panel{width:100%;height:100%;overflow:auto;min-width:330px}
  .nt-project-panel h3{font-size:13px;color:#e8bf57;margin:12px 0 8px;border-bottom:1px solid #5b481e;padding-bottom:5px}
  .nt-project-panel label{display:block;margin:7px 0}.nt-project-panel input,.nt-project-panel select{
    width:100%;box-sizing:border-box;color:#f7edd2;background:#262217;border:1px solid #776233;
    border-radius:4px;padding:6px;min-height:32px}
  .nt-project-panel button,.nt-project-browser button{background:#443719;color:#ffe5a0;border:1px solid #aa883a;
    border-radius:4px;padding:6px 9px;cursor:pointer;margin:4px 5px 4px 0}
  .nt-project-panel button:focus-visible,.nt-project-panel input:focus-visible,.nt-project-panel select:focus-visible,
  .nt-project-browser button:focus-visible{outline:2px solid #ffe29b;outline-offset:2px}
  .nt-project-panel .nt-status{white-space:pre-wrap;overflow-wrap:anywhere;margin-top:8px}
  .nt-project-panel .nt-error{color:#ffb3a8}.nt-project-browser{width:min(740px,90vw);max-height:80vh}
  .nt-project-browser::backdrop{background:#000b}.nt-project-browser .nt-entries{max-height:48vh;overflow:auto}
  .nt-project-browser .nt-entry{display:block;width:100%;text-align:left;overflow-wrap:anywhere}
  .nt-project-browser p{overflow-wrap:anywhere}`;
  document.head.append(css);
}

async function choosePath(kind, current) {
  const dialog = element("dialog");
  dialog.className = "nt-project-browser";
  dialog.setAttribute("aria-label", kind === "folder" ? "Chọn folder Asset" : "Chọn tệp dự án");
  const title = element("h3", "Chọn trong thư mục dự án", dialog);
  title.tabIndex = -1;
  const path = element("p", "Đang tải…", dialog);
  const toolbar = element("div", undefined, dialog);
  const up = element("button", "↑ Thư mục cha", toolbar);
  const accept = element("button", "Chọn folder này", toolbar);
  accept.hidden = kind !== "folder";
  accept.disabled = true;
  const cancel = element("button", "Hủy", toolbar);
  const entries = element("div", undefined, dialog);
  entries.className = "nt-entries";
  const error = element("p", "", dialog);
  error.setAttribute("role", "alert");
  let selected = null, listing = null, sequence = 0;
  async function load(where = "") {
    const request = ++sequence;
    accept.disabled = true;
    try {
      const result = await get("/newtecons/panel/browse", { path: where, kind });
      if (request !== sequence || !dialog.isConnected) return;
      listing = result;
      path.textContent = result.path;
      up.disabled = !result.parent;
      accept.disabled = false;
      error.textContent = "";
      entries.replaceChildren();
      for (const item of result.entries) {
        const btn = element("button", `${item.directory ? "📁" : "📄"} ${item.name}`, entries);
        btn.className = "nt-entry";
        btn.type = "button";
        btn.onclick = () => item.directory ? load(item.path) : finish(item.path);
      }
    } catch (err) {
      error.textContent = err.message;
    }
  }
  const done = new Promise((resolve) => dialog.addEventListener("close", () => {
    sequence++;
    dialog.remove();
    resolve(selected);
  }, { once: true }));
  function finish(value) { selected = value; dialog.close(); }
  up.onclick = () => listing?.parent && load(listing.parent);
  accept.onclick = () => listing && finish(listing.path);
  cancel.onclick = () => finish(null);
  document.body.append(dialog);
  dialog.showModal();
  title.focus();
  // Browser starts at the allowlisted root; current file paths never become arbitrary read requests.
  await load(kind === "folder" ? current : "");
  if (kind === "folder" && current && !listing) await load("");
  return done;
}

function attach(node) {
  installCSS();
  node.color = "#634d1b";
  node.bgcolor = "#251f12";
  const root = element("div");
  root.className = "nt-project-panel";
  root.addEventListener("pointerdown", (event) => event.stopPropagation());
  root.addEventListener("keydown", (event) => event.stopPropagation());
  const controls = new Map();
  let shots = [], refreshVersion = 0, debounce;
  const widget = (name) => node.widgets?.find((w) => w.name === name);
  const value = (name) => widget(name)?.value;
  const status = element("div");
  status.className = "nt-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  function message(text, error = false) {
    status.textContent = text;
    status.classList.toggle("nt-error", error);
  }
  function stopAuto(text = "Đã dừng Auto; shot đang chạy vẫn được lưu.") {
    if (autoOwner?.node === node) {
      autoOwner.cancelled = true;
      autoOwner.stopReason = text;
    }
    message(text);
  }
  function set(name, val) {
    if (autoOwner?.node === node) stopAuto("Cài đặt thay đổi — Auto đã dừng.");
    const w = widget(name);
    if (!w) return;
    w.value = val;
    if (controls.has(name)) controls.get(name).value = val;
    mark(node);
  }
  function populate(name, options, selected) {
    const control = controls.get(name);
    control.replaceChildren();
    for (const option of options) element("option", option, control).value = option;
    const chosen = options.includes(selected) ? selected : options[0];
    control.value = chosen;
    const w = widget(name);
    w.options = { ...w.options, values: options };
    w.value = chosen;
  }
  function shotOptions() {
    const options = shots.filter((s) => value("scene") === "ALL" || s.scene === value("scene")).map((s) => s.shot);
    populate("shot", options.length ? options : ["SELECT"], value("shot"));
  }
  async function refresh() {
    const version = ++refreshVersion;
    const path = value("shotlist_path");
    const domain = value("domain");
    shots = [];
    populate("scene", ["ALL"], value("scene"));
    populate("shot", ["SELECT"], value("shot"));
    if (!path) { message("Chọn shotlist để nạp Scene / Shot."); return; }
    try {
      const data = await get("/newtecons/panel/shots", { shotlist: path, domain });
      if (version !== refreshVersion || value("shotlist_path") !== path || value("domain") !== domain) return;
      shots = data.shots;
      populate("scene", ["ALL", ...data.scenes], savedScene);
      shotOptions();
      if (shots.some((s) => s.shot === savedShot && (value("scene") === "ALL" || s.scene === value("scene")))) {
        widget("shot").value = savedShot;
        controls.get("shot").value = savedShot;
      }
      message(`${shots.length} shot • ${data.scenes.length} scene`);
      mark(node);
    } catch (err) {
      if (version === refreshVersion) message(err.message, true);
    }
  }
  let savedScene = value("scene"), savedShot = value("shot");
  function changed(name) {
    if (name === "domain") {
      set("style", value("domain") === "newtecons_live_action" ? "Live-action photoreal" : "3D cartoon");
    }
    if (name === "scene") { savedScene = value("scene"); shotOptions(); }
    if (name === "shot") savedShot = value("shot");
    if (["shotlist_path", "domain"].includes(name)) {
      refreshVersion++;
      clearTimeout(debounce);
      debounce = setTimeout(refresh, 200);
    }
  }
  function field(name, title, kind) {
    const label = element("label", title, root);
    const w = widget(name);
    const isCombo = Array.isArray(w?.options?.values);
    const control = element(isCombo ? "select" : "input", undefined, label);
    if (isCombo) for (const option of w.options.values) {
      const label = name === "run_mode" && option === "Auto: missing shots"
        ? "Tự động: render lần lượt các shot chưa có" : option;
      element("option", label, control).value = option;
    }
    if (name === "min_duration") { control.type = "number"; control.min = "0.1"; control.max = "150"; control.step = "0.1"; }
    else if (!isCombo) control.type = "text";
    control.value = value(name) ?? "";
    controls.set(name, control);
    control.onchange = () => {
      set(name, name === "min_duration" ? Number(control.value) : control.value);
      changed(name);
    };
    if (kind) {
      const button = element("button", kind === "folder" ? "Chọn folder…" : "Chọn file…", label);
      button.type = "button";
      button.onclick = async (event) => {
        event.preventDefault();
        try {
          const selected = await choosePath(kind, value(name));
          if (selected) { set(name, selected); changed(name); }
        } catch (err) { message(err.message, true); }
      };
    }
  }
  element("h3", "NEWTECONS PROJECT PANEL", root);
  field("domain", "Domain");
  element("h3", "1 KỊCH BẢN & SHOTLIST", root);
  field("script_path", "Kịch bản (.docx / .txt)", "script");
  field("shotlist_path", "Shotlist (.xlsx / .csv)", "shotlist");
  const reload = element("button", "Nạp lại Scene / Shot", root);
  reload.onclick = () => { savedScene = value("scene"); savedShot = value("shot"); refresh(); };
  element("h3", "2 ASSET", root);
  field("asset_folder", "Folder Asset", "folder");
  element("h3", "3 SHOT CẦN RENDER", root);
  field("run_mode", "Chế độ chạy"); field("scene", "Scene"); field("shot", "Shot");
  element("h3", "4 KHUNG HÌNH & ĐỘ PHÂN GIẢI", root);
  field("aspect", "Tỷ lệ"); field("generation_size", "Kích thước sinh H3");
  field("output_resolution", "Độ phân giải đầu ra (mục tiêu upscale)");
  element("h3", "5 HÌNH ẢNH", root);
  field("style", "Phong cách mặc định");
  field("no_image_mode", "Shot không có ảnh"); field("min_duration", "Thời lượng tối thiểu (s)");
  const auto = element("button", "Chạy Auto", root);
  const stop = element("button", "Dừng Auto", root);
  stop.onclick = () => stopAuto();
  root.append(status);
  const settings = () => Object.fromEntries(fields.map((key) => [key, value(key)]));
  stop.disabled = true;
  function progress(info, detail) {
    message(`${info.completed}/${info.total} đã lưu · ${info.missing} còn thiếu\n${detail}\nReceipt render kỹ thuật; chưa duyệt nội dung.`);
  }
  auto.onclick = async () => {
    if (autoOwner) { message("Một Project Panel đang Auto hoặc đang lưu shot cuối. Dùng Dừng Auto để hủy phần còn lại.", true); return; }
    if (value("run_mode") !== "Auto: missing shots") { message("Chọn chế độ Auto trước.", true); return; }
    const graphNodes = app.graph?._nodes || [];
    if (graphNodes.filter((n) => n.type === "NewteconsProjectPanel").length !== 1 ||
        graphNodes.filter((n) => n.type === "NewteconsPanelSaveVideo").length !== 1) {
      message("Auto cần đúng một Project Panel và một Save + Receipt trong graph.", true); return;
    }
    // A fixed WAV/guide from S02 must never be reused silently for another shot.
    if (graphNodes.some((n) => /^(LoadAudio|LoadImage|LoadVideo)$/.test(n.type) &&
        n.outputs?.some((o) => o.links?.length))) {
      message("Auto bị chặn: graph còn WAV/ảnh/video cố định. Dùng adapter đầu vào theo shot; S02_A chỉ chạy One shot.", true);
      return;
    }
    if (graphNodes.some((n) => n.widgets?.some((w) => w.name === "control_after_generate" && w.value !== "fixed"))) {
      message("Auto cần seed ở chế độ fixed để xác định shot đã render.", true); return;
    }
    // Acquire ownership synchronously, before graphToPrompt/hash awaits: double-click cannot start two loops.
    const owner = { node, panelId: String(node.id), graph: app.graph,
      values: settings(), signature: JSON.stringify(settings()), cancelled: false, promptId: null };
    autoOwner = owner;
    auto.disabled = true;
    stop.disabled = false;
    try {
      const initial = JSON.parse(JSON.stringify(await app.graphToPrompt()));
      const initialGraphState = JSON.stringify(owner.graph.serialize());
      const definitions = await get("/object_info");
      assertLocalGraph(initial.output, definitions, location.hostname);
      owner.context = await hashPrompt(initial.output);
      const current = async () => {
        if (autoOwner !== owner || app.graph !== owner.graph) return false;
        const context = await contextHash();
        return autoOwner === owner && app.graph === owner.graph && node.graph === owner.graph &&
          owner.signature === JSON.stringify(settings()) && context === owner.context;
      };
      if (!await current() || owner.cancelled) return;
      const report = () => get("/newtecons/panel/pending", {
        ...owner.values, render_context_sha256: owner.context,
      });
      const result = await runSequential({
        current, report, progress,
        currentSync: () => autoOwner === owner && app.graph === owner.graph && node.graph === owner.graph &&
          owner.signature === JSON.stringify(settings()) && JSON.stringify(owner.graph.serialize()) === initialGraphState,
        queue: () => get("/queue"),
        history: (id) => get(`/history/${encodeURIComponent(id)}`),
        wait: () => new Promise((resolve) => setTimeout(resolve, 1500)),
        snapshot: async (selected) => {
          const serialized = JSON.parse(JSON.stringify(await app.graphToPrompt()));
          if (await hashPrompt(serialized.output) !== owner.context) throw new Error("Graph đã thay đổi");
          return bindSnapshot(serialized, node.id, selected);
        },
        submit: (frozen) => api.queuePrompt(0, frozen),
        cancelPending: async (id) => {
          const queue = await get("/queue");
          if (!Array.isArray(queue.queue_pending)) throw new Error("Không đọc được queue để dừng Auto");
          if (!queue.queue_pending.some((item) => item[1] === id)) return false;
          const response = await api.fetchApi("/queue", { method: "POST",
            headers: { "Content-Type": "application/json" }, body: JSON.stringify({ delete: [id] }) });
          if (!response.ok) throw new Error(`Không hủy được job đang đợi: HTTP ${response.status}`);
          return true;
        },
      }, owner);
      if (result.complete) progress(result.progress, "Auto hoàn tất: mọi shot có render và hash khớp.");
      else if (result.progress) progress(result.progress, owner.stopReason || "Đã dừng Auto.");
      else message(owner.stopReason || "Đã dừng Auto.");
    } catch (err) { message(`Auto dừng: ${err.message}`, true); }
    finally {
      if (autoOwner === owner) autoOwner = null;
      auto.disabled = false;
      stop.disabled = true;
    }
  };
  const dom = node.addDOMWidget("project_panel_ui", "NEWTECONS_PROJECT_PANEL", root, { serialize: false });
  dom.computeSize = () => [420, 900];
  // Backend widgets remain serializable and connectable, but the DOM panel is the visible editor.
  for (const name of [...fields, "auto_shot", "auto_render_key"]) {
    const w = widget(name);
    if (w) { w.type = "converted-widget"; w.computeSize = () => [0, -4]; }
  }
  node.setSize([460, 990]);
  livePanels.set(node, { refresh, sync: () => {
    for (const [name, control] of controls) control.value = value(name) ?? "";
    savedScene = value("scene"); savedShot = value("shot"); refresh();
  } });
  const oldConfigure = node.onConfigure;
  node.onConfigure = function (...args) {
    oldConfigure?.apply(this, args);
    livePanels.get(node)?.sync();
  };
  const oldRemoved = node.onRemoved;
  node.onRemoved = function (...args) {
    clearTimeout(debounce); refreshVersion++;
    if (autoOwner?.node === node) stopAuto("Panel đã đóng — Auto đã dừng.");
    livePanels.delete(node);
    oldRemoved?.apply(this, args);
  };
  // Restored widget values must be captured by onConfigure before refresh clears the dropdowns.
  setTimeout(() => { if (refreshVersion === 0) livePanels.get(node)?.sync(); }, 0);
}

app.registerExtension({
  name: "Newtecons.ProjectPanel",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "NewteconsProjectPanel") return;
    const previous = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      const result = previous?.apply(this, args);
      attach(this);
      return result;
    };
  },
});
