// CPU/browser orchestration only. GPU work uses the normal local ComfyUI queue.
export const QUEUE_LIMIT = 4;

export function assertLocalGraph(output, definitions, hostname) {
  if (!["localhost", "127.0.0.1", "[::1]", "::1"].includes(hostname)) {
    throw new Error("Auto video chỉ chạy trên ComfyUI localhost");
  }
  if (!Object.values(output).some((node) => node.class_type === "NewteconsPanelH3")) {
    throw new Error("Auto video cần Native H3 Adapter local");
  }
  for (const node of Object.values(output)) {
    const info = definitions[node.class_type];
    if (!info || info.api_node || /comfy_api_nodes/.test(info.python_module || "") ||
        /^(Claude|OpenAI|Gemini|Veo|Kling|Luma|Runway|Ideogram|Recraft|StabilityAPI|BFL|FluxKontext|MinimaxAPI)/i.test(node.class_type)) {
      throw new Error(`Auto video chỉ dùng node local: ${node.class_type}`);
    }
  }
}

export function pendingCount(queue) {
  if (!Array.isArray(queue?.queue_pending) || !Array.isArray(queue?.queue_running)) {
    throw new Error("ComfyUI queue response is incomplete");
  }
  return queue.queue_pending.length;
}

export function bindSnapshot(serialized, panelId, selected) {
  const frozen = JSON.parse(JSON.stringify(serialized));
  const panel = frozen.output?.[String(panelId)];
  if (panel?.class_type !== "NewteconsProjectPanel" || !selected?.shot || !selected?.render_key) {
    throw new Error("Auto snapshot is missing its selected panel/shot");
  }
  const savers = Object.entries(frozen.output).filter(([, n]) => n.class_type === "NewteconsPanelSaveVideo");
  if (savers.length !== 1 || String(savers[0][1].inputs?.receipt_json?.[0]) !== String(panelId) ||
      savers[0][1].inputs.receipt_json[1] !== 7) {
    throw new Error("Save + Receipt must consume this panel's receipt output");
  }
  panel.inputs.auto_shot = selected.shot;
  panel.inputs.auto_render_key = selected.render_key;
  return { frozen, saverId: savers[0][0] };
}

export function historyState(history, promptId, saverId, panelId, selected) {
  const entry = history?.[promptId];
  if (!entry) return "waiting";
  const messages = entry.status?.messages || [];
  if (messages.some(([type, detail]) => type === "execution_error" &&
      String(detail?.exception_message || "").startsWith("AUTO_ALREADY_RENDERED:"))) return "already-rendered";
  if (entry.status?.status_str === "error" || messages.some(([type]) =>
    ["execution_error", "execution_interrupted"].includes(type))) {
    throw new Error(`ComfyUI failed/interrupted shot ${selected.shot}`);
  }
  if (!entry.status?.completed) return "waiting";
  if (entry.status.status_str !== "success") throw new Error("ComfyUI history has no successful completion");
  const saved = entry.outputs?.[saverId]?.newtecons_panel || [];
  if (!saved.some((item) => String(item.panel_id) === String(panelId) &&
      item.shot === selected.shot && item.render_key === selected.render_key)) {
    throw new Error(`Shot ${selected.shot} finished without its Save + Receipt`);
  }
  return "complete";
}

export async function runSequential(io, owner) {
  let lastProgress = null;
  const check = async () => {
    if (!owner.cancelled && !await io.current()) {
      owner.cancelled = true;
      owner.stopReason = "Graph/cài đặt thay đổi — Auto đã dừng.";
    }
    return !owner.cancelled;
  };
  while (await check()) {
    const progress = await io.report();
    lastProgress = progress;
    if (!await check()) break;
    io.progress(progress, "Kiểm tra shot còn thiếu");
    if (!progress.pending) return { complete: true, progress };
    // Other jobs are allowed. Wait while four or more prompts are pending.
    const queue = await io.queue();
    if (!await check()) break;
    if (pendingCount(queue) >= QUEUE_LIMIT) {
      io.progress(progress, `Chờ queue: ${queue.queue_pending.length} job đang đợi`);
      await io.wait();
      continue;
    }
    const selected = { shot: progress.shot, scene: progress.scene, render_key: progress.render_key };
    const { frozen, saverId } = await io.snapshot(selected);
    if (!await check()) break;
    // Snapshot serialization can take time; enforce the queue limit again just before submission.
    if (pendingCount(await io.queue()) >= QUEUE_LIMIT) { await io.wait(); continue; }
    // Do not await another serialization/hash after this capacity read.
    if (owner.cancelled || (io.currentSync && !io.currentSync())) {
      owner.cancelled = true;
      owner.stopReason ||= "Graph/cài đặt thay đổi — Auto đã dừng.";
      break;
    }
    io.progress(progress, `Đang xếp shot ${selected.shot}`);
    const answer = await io.submit(frozen);
    if (typeof answer?.prompt_id !== "string" || !answer.prompt_id) throw new Error("ComfyUI chưa nhận prompt_id");
    owner.promptId = answer.prompt_id;
    let absent = 0;
    for (;;) {
      await check();
      // Stop only deletes this run's queued prompt; never POST /interrupt.
      if (owner.cancelled) await io.cancelPending(owner.promptId);
      const history = await io.history(owner.promptId);
      if (historyState(history, owner.promptId, saverId, owner.panelId, selected) !== "waiting") {
        const verified = await io.report();
        const receipt = verified.shots.find((item) => item.shot === selected.shot &&
          item.render_key === selected.render_key && item.rendered);
        if (!receipt) throw new Error(`Receipt/output hash không khớp: ${selected.shot}`);
        lastProgress = verified;
        owner.promptId = null;
        io.progress(verified, `Đã lưu shot ${selected.shot}`);
        break;
      }
      const live = await io.queue();
      pendingCount(live);
      const present = [...live.queue_pending, ...live.queue_running].some((item) => item[1] === owner.promptId);
      absent = present ? 0 : absent + 1;
      if (absent >= 4) {
        if (owner.cancelled) {
          owner.promptId = null;
          return { complete: false, progress: lastProgress };
        }
        throw new Error(`Prompt ${selected.shot} không còn trong queue/history; Auto đã dừng`);
      }
      io.progress(progress, `${owner.cancelled ? "Đã dừng Auto; đang chờ lưu" : "Đang render/chờ"} ${selected.shot}`);
      await io.wait();
    }
  }
  return { complete: false, progress: lastProgress };
}
