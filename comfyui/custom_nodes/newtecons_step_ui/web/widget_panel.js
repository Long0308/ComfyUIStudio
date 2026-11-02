import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { el } from "./step_dock.js";
import { comboValues, linkForInput, numberRules, parameterWidget, parseNumber } from "./widget_panel_logic.js";

const pending = new Map();
const uploaded = new WeakMap();
const controlStyle = "width:100%;min-width:0;box-sizing:border-box;background:var(--ink);color:var(--text);border:1px solid var(--accl);padding:6px;font:inherit";

export function panelIsEditing(id) {
  const root = document.getElementById(id);
  return Boolean(pending.get(id) || (root?.contains(document.activeElement)
    && document.activeElement?.matches("input,select,textarea")));
}

export function markGraphDirty(graph = app.graph) {
  graph.setDirtyCanvas?.(true, true);
  graph.change?.();
  app.canvas?.setDirty(true, true);
}

function live(graph, node, widget) {
  if (app.graph !== graph || graph.getNodeById(node.id) !== node || !node.widgets?.includes(widget)) {
    throw new Error("Workflow/node đã đổi. Mở lại panel trước khi chỉnh.");
  }
  if (linkForInput(graph, node, widget.name)) throw new Error("Tham số đã được nối từ node khác; chỉnh nguồn liên kết.");
  if (widget.disabled || widget.options?.disabled || widget.options?.read_only || widget.options?.readonly) throw new Error("Widget đang bị node khoá.");
}

function commit(graph, node, widget, value, event) {
  live(graph, node, widget);
  const old = widget.value;
  if (Object.is(old, value)) return;
  graph.beforeChange?.();
  try {
    widget.value = value;
    widget.callback?.call(widget, value, app.canvas, node, app.canvas?.graph_mouse, event);
    node.onWidgetChanged?.(widget.name, widget.value, old, widget);
  } finally {
    // Callback failures must still expose the changed value and dirty state, never silently save.
    graph.afterChange?.();
    markGraphDirty(graph);
  }
}

function makeControl(graph, node, widget, panelId) {
  const label = `#${node.id} ${widget.name}`;
  const message = el("div", { role: "status", "aria-live": "polite", style: "font-size:11px;overflow-wrap:anywhere" });
  const box = el("div", { class: "ntd-param", style: "margin:8px 0" });
  const disabled = Boolean(widget.disabled || widget.options?.disabled || widget.options?.read_only || widget.options?.readonly);
  const type = String(widget.type || "").toLowerCase();
  let input, refresh;
  const apply = (value, event) => {
    try {
      commit(graph, node, widget, value, event);
      input.setCustomValidity?.(""); input.removeAttribute("aria-invalid");
      message.textContent = "Đã đổi graph · Ctrl+S để lưu workflow.";
      return true;
    } catch (error) {
      message.textContent = `Không áp dụng được: ${error.message || error}`;
      input.setCustomValidity?.(message.textContent); input.setAttribute("aria-invalid", "true");
      return false;
    }
  };
  const isFile = /^(?:LoadImage|LoadImageMask|LoadImageOutput)$/u.test(node.type) && widget.name === "image";
  const isAudio = node.type === "LoadAudio" && widget.name === "audio";
  if (type === "combo" || widget.options?.values || isFile || isAudio) {
    input = el("select", { style: controlStyle });
    let values = [];
    refresh = () => {
      values = [...new Set([...comboValues(widget, node), ...(uploaded.get(widget) || [])])];
      input.replaceChildren();
      // Preserve visibly even a stale filename/model; don't fabricate it as a selectable server option.
      if (!values.some((v) => Object.is(v, widget.value))) {
        const missing = el("option", { value: "", text: `${widget.value ?? "—"} (ngoài danh sách hiện tại)`, disabled: true });
        missing.selected = true; input.append(missing);
      }
      values.forEach((v, i) => {
        const option = el("option", { value: String(i), text: String(v) });
        option.selected = Object.is(v, widget.value); input.append(option);
      });
    };
    refresh();
    input.addEventListener("focus", refresh);
    input.addEventListener("change", (event) => {
      const value = values[Number(input.value)];
      if (input.value !== "" && (comboValues(widget, node).includes(value) || uploaded.get(widget)?.includes(value))) apply(value, event);
      else message.textContent = "Lựa chọn không còn trong danh sách của widget.";
    });
  } else if (type === "toggle" || typeof widget.value === "boolean") {
    input = el("input", { type: "checkbox", role: "switch", style: "accent-color:var(--acc)" });
    input.checked = Boolean(widget.value);
    input.addEventListener("change", (event) => {
      if (apply(input.checked, event)) input.checked = Boolean(widget.value);
    });
  } else if (type === "number" || type === "slider" || typeof widget.value === "number") {
    const rules = numberRules(widget);
    input = el("input", { type: "number", min: rules.min, max: rules.max, step: rules.step ?? "any", style: controlStyle });
    input.value = String(widget.value ?? "");
    input.addEventListener("input", () => { input.setCustomValidity(""); input.removeAttribute("aria-invalid"); });
    input.addEventListener("change", (event) => {
      try { if (apply(parseNumber(input.value, widget), event)) input.value = String(widget.value); }
      catch (error) { message.textContent = error.message; input.setCustomValidity(error.message); input.setAttribute("aria-invalid", "true"); input.reportValidity(); }
    });
    message.textContent = `min ${rules.min ?? "—"} · max ${rules.max ?? "—"} · step ${rules.step ?? "any"}`;
  } else {
    const multiline = widget.options?.multiline || /prompt|text|prompts/u.test(widget.name)
      || node.type === "PrimitiveStringMultiline" || String(widget.value || "").includes("\n");
    input = el(multiline ? "textarea" : "input", { style: controlStyle + (multiline ? ";resize:vertical;min-height:90px" : ""), ...(multiline ? { rows: 5 } : { type: "text" }) });
    input.value = String(widget.value ?? "");
    input.addEventListener("change", (event) => apply(input.value, event));
  }
  input.disabled = disabled;
  input.setAttribute("aria-label", label);
  box.append(el("label", { style: "display:block;overflow-wrap:anywhere" }, el("span", { text: label }), input), message);
  if (disabled) message.textContent = "Chỉ đọc: node khoá widget này.";
  if (isFile && node.type !== "LoadImageOutput") {
    const picker = el("input", { type: "file", accept: "image/*", hidden: true, "aria-label": `Upload ảnh cho ${label}` });
    const upload = el("button", { type: "button", class: "ntd-btn", text: "UPLOAD ẢNH", disabled, onclick: () => picker.click() });
    picker.addEventListener("change", async () => {
      const file = picker.files?.[0];
      if (!file) return;
      pending.set(panelId, (pending.get(panelId) || 0) + 1); upload.disabled = true;
      try {
        live(graph, node, widget);
        if (!file.size || (file.type && !file.type.startsWith("image/"))) throw new Error("Cần chọn file ảnh không rỗng.");
        const body = new FormData(); body.append("image", file); body.append("type", "input");
        // No overwrite flag: ComfyUI preserves an existing input with the same name.
        const res = await api.fetchApi("/upload/image", { method: "POST", body });
        if (!res.ok) throw new Error(`Upload HTTP ${res.status}`);
        const result = await res.json();
        if (typeof result.name !== "string" || !result.name || (result.type && result.type !== "input")) throw new Error("Upload trả dữ liệu không hợp lệ.");
        const value = result.subfolder ? `${result.subfolder}/${result.name}` : result.name;
        live(graph, node, widget);
        uploaded.set(widget, [...new Set([...(uploaded.get(widget) || []), value])]);
        let warning = "";
        try {
          const response = await api.fetchApi(`/object_info/${encodeURIComponent(node.type)}`);
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const info = (await response.json())[node.type]?.input;
          const spec = info?.required?.image || info?.optional?.image;
          const values = Array.isArray(spec?.[0]) ? spec[0] : spec?.[1]?.options;
          if (!Array.isArray(values)) throw new Error("Thiếu danh sách image");
          live(graph, node, widget);
          if (Array.isArray(widget.options?.values)) widget.options.values = values;
          else uploaded.set(widget, [...new Set([...values, ...(uploaded.get(widget) || [])])]);
        } catch (error) { warning = ` · tải được file; chưa làm mới toàn bộ danh sách (${error.message})`; }
        if (apply(value)) message.textContent += warning;
        refresh();
      } catch (error) { message.textContent = `Upload lỗi: ${error.message || error}`; }
      finally { pending.set(panelId, Math.max(0, (pending.get(panelId) || 1) - 1)); upload.disabled = disabled; picker.value = ""; }
    });
    box.append(upload, picker);
  }
  return box;
}

export function nodeParameters(entries, { panelId } = {}) {
  const graph = app.graph;
  const root = el("div", { class: "ntd-parameters" }, el("h4", { text: "THÔNG SỐ — chỉnh trực tiếp widget của graph" }),
    el("div", { text: "Đổi giá trị rồi rời ô để áp dụng. Không tự lưu hoặc chạy. Node đang tắt vẫn giữ chế độ tắt." }));
  const seen = new Set();
  function add(node, depth = 0) {
    if (!node || seen.has(node.id)) return;
    seen.add(node.id);
    if (/^(?:Note|MarkdownNote)$/u.test(node.type)) return;
    const widgets = (node.widgets || []).filter(parameterWidget);
    const linked = (node.inputs || []).filter((p) => p.widget && p.link != null);
    if (!widgets.length && !linked.length) return;
    const group = el("div", { class: "ntd-slot", style: "margin:8px 0;overflow-wrap:anywhere" },
      el("b", { text: `#${node.id} ${node.title || node.type} · ${node.type}${node.mode ? " · TẮT/BYPASS" : ""}` }));
    root.append(group);
    const names = new Set([...widgets.map((w) => w.name), ...linked.map((p) => p.widget.name || p.name)]);
    for (const name of names) {
      const wire = linkForInput(graph, node, name);
      if (wire) {
        const originId = wire.link?.origin_id ?? wire.link?.[1];
        const origin = originId != null ? graph.getNodeById(originId) : null;
        group.append(el("div", { text: `${name} ← ${origin ? `#${origin.id} ${origin.title || origin.type} (chỉnh nguồn bên dưới)` : "liên kết thiếu nguồn"}` }));
        if (origin && depth < 10) add(origin, depth + 1);
        else group.append(el("div", { text: "Chỉ đọc: không tìm được widget nguồn trong chuỗi liên kết." }));
      } else {
        const widget = widgets.find((w) => w.name === name);
        if (widget) group.append(makeControl(graph, node, widget, panelId));
      }
    }
  }
  for (const [id, type] of entries) {
    const node = graph?.getNodeById(id);
    if (!node || node.type !== type) root.append(el("div", { class: "ntd-warn", text: `#${id} ${type}: THIẾU NODE / SAI TYPE — không gán nhầm widget.` }));
    else add(node);
  }
  return root;
}
