// Pure helpers shared by the panel and its CPU verification. No saved workflow mutations.
export function imageStepForNode(node, steps) {
  const title = String(node.title || "");
  // Appended pose controls can overlap the old 08/09 rectangles as well as fall outside them.
  if (/^(?:POSESET|POSE CELL|SKELETON CELL|DEPTH CELL|PROMPT CELL|DÙNG CONTROL ĐỘ SÂU|SITE-PPE)/u.test(title)
    && steps.some((s) => s.code === "07")) return "07";
  const own = steps.find((s) => node.pos && node.pos[0] >= s.bounding[0] && node.pos[0] < s.bounding[0] + s.bounding[2]
    && node.pos[1] >= s.bounding[1] && node.pos[1] < s.bounding[1] + s.bounding[3]);
  if (own) return own.code;
  // v006r2/r3 appended pose nodes below the original group rectangles.
  const code = /^(?:BƯỚC|STEP|B\?\?C)\s+(\d{2}[A-Z]?)/iu.exec(title)?.[1];
  if (steps.some((s) => s.code === code)) return code;
  // An unclassified parameter is still reachable, explicitly labelled as outside a group.
  return steps.find((s) => s.code === "00")?.code || steps[0]?.code;
}

export function linkForInput(graph, node, name) {
  const input = node.inputs?.find((p) => (p.widget?.name || p.name) === name && p.link != null);
  if (!input) return null;
  const link = graph.links instanceof Map ? graph.links.get(input.link) : graph.links?.[input.link];
  return { input, link };
}

export function comboValues(widget, node) {
  const values = typeof widget.options?.values === "function"
    ? widget.options.values.call(widget.options, node, widget) : widget.options?.values;
  return Array.isArray(values) ? values : [];
}

export function numberRules(widget) {
  const options = widget.options || {};
  const finite = (x) => typeof x === "number" && Number.isFinite(x);
  // Match installed ComfyUI WidgetInputNumber: LiteGraph's legacy step is scaled by 10.
  const step = finite(options.step2) && options.step2 > 0 ? options.step2
    : finite(options.step) && options.step > 10 ? options.step / 10
      : options.precision === 0 ? 1 : finite(options.precision) ? 10 ** -options.precision : undefined;
  return { min: finite(options.min) ? options.min : undefined, max: finite(options.max) ? options.max : undefined, step,
    integer: options.precision === 0 || /(?:^|_)(?:seed|width|height|length|steps|batch_size|frame_idx)$/u.test(widget.name) };
}

export function parseNumber(raw, widget) {
  if (String(raw).trim() === "") throw new Error("Không được để trống số.");
  const value = Number(raw), { min, max, step, integer } = numberRules(widget);
  if (!Number.isFinite(value)) throw new Error("Cần một số hữu hạn.");
  if (min != null && value < min) throw new Error(`Tối thiểu ${min}.`);
  if (max != null && value > max) throw new Error(`Tối đa ${max}.`);
  if (integer && !Number.isInteger(value)) throw new Error("Cần số nguyên.");
  if (integer && !Number.isSafeInteger(value)) throw new Error("Vượt giới hạn số nguyên chính xác của JavaScript (2^53 − 1).");
  if (step != null) {
    const units = (value - (min ?? 0)) / step;
    if (Math.abs(units - Math.round(units)) > 1e-7 * Math.max(1, Math.abs(units))) throw new Error(`Bước nhảy ${step}, bắt đầu từ ${min ?? 0}.`);
  }
  return value;
}

export function parameterWidget(widget) {
  const type = String(widget.type || "").toLowerCase();
  if (type === "button") return false;
  // Frontend seed controls intentionally serialize:false but DO change generation behaviour.
  if (widget.options?.serialize === false && !["control_after_generate", "control_filter_list"].includes(widget.name)) return false;
  return ["number", "slider", "toggle", "combo", "text", "string", "customtext", "textarea"].includes(type)
    || type.startsWith("converted-widget") || ["string", "number", "boolean"].includes(typeof widget.value);
}
