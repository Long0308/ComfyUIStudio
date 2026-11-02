// Pure logic of the "ONE SHOT = ONE FULL PIPELINE" view (10 stages). Display-only: every number and every command comes
// from shots[].pipeline written by `jjv video ui-state` (engine/video/ui_pipeline.py). Nothing here is typed by hand;
// there is NO run button — GPU commands are shown as text to copy (gpu: true) and are never sent from the browser.
export const PIPELINE_SCHEMA = "jjv/video-ui-pipeline/v1";
export const STATUS_LABEL = {
  missing: "CHƯA CÓ", generated: "ĐÃ TẠO", "pending-review": "CHỜ DUYỆT", approved: "ĐÃ DUYỆT", refused: "BỊ CHẶN",
};
export const STATUS_COLOR = { missing: "#5C6795", generated: "#0B4FD9", "pending-review": "#B45309", approved: "#3E8914", refused: "#D00000" };
const KNOWN = Object.keys(STATUS_LABEL);

const str = (v) => (typeof v === "string" ? v : v == null ? "" : String(v));
export function esc(v) {
  return str(v).replace(/[&<>"']/gu, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
export function shortSha(sha) { return typeof sha === "string" && sha.length >= 12 ? sha.slice(0, 12) : "—"; }
const SAFE_URL = /^\/(?!\/)/u;

function normCmd(c) {
  if (!c || typeof c.text !== "string" || !c.text) return null;
  return { text: c.text, gpu: c.gpu === true, placeholders: Array.isArray(c.placeholders) ? c.placeholders.map(str) : [] };
}

export function normStage(raw) {
  const known = KNOWN.includes(raw?.status);
  return {
    code: str(raw?.code), key: str(raw?.key), label: str(raw?.label), status: known ? raw.status : "missing",
    statusRaw: known ? null : str(raw?.status), reason: raw?.reason ? str(raw.reason) : null,
    ins: Array.isArray(raw?.in) ? raw.in : [], outs: Array.isArray(raw?.out) ? raw.out : [],
    detail: raw?.detail && typeof raw.detail === "object" ? raw.detail : {}, approval: normCmd(raw?.approval), next: normCmd(raw?.next),
  };
}

// The review box ("CHỜ DUYỆT"): only for generated-but-unapproved stages. Carries what to look at + both commands.
export function reviewBox(stage) {
  if (stage.status !== "pending-review") return null;
  const look = stage.outs.map((o) => ({
    name: str(o.name || o.path || o.kind), sha: o.sha256 || null, url: SAFE_URL.test(str(o.url)) ? o.url : null,
    seconds: o.seconds ?? null, text: o.text ? str(o.text) : null,
  }));
  return {
    look, approvalCommand: stage.approval, nextCommand: stage.next, reason: stage.reason,
    note: stage.approval ? null : str(stage.detail?.approval_note || "engine chưa cung cấp lệnh duyệt cho bước này"),
  };
}

// "CHƯA CÓ" box: the exact next command (or null when the engine has none for it).
export function missingBox(stage) {
  return stage.status === "missing" ? { text: "CHƯA CÓ", reason: stage.reason, command: stage.next } : null;
}
export function refusedBox(stage) {
  return stage.status === "refused" ? { reason: stage.reason, unblocks: str(stage.detail?.unblocks) || null } : null;
}

export function pipelineViewModel(shot) {
  const p = shot?.pipeline;
  if (!p || !Array.isArray(p.stages)) return { id: shot?.id ?? null, present: false, stages: [], pending: 0 };
  const stages = p.stages.map(normStage).map((s) => ({ ...s, review: reviewBox(s), missingBox: missingBox(s), refused: refusedBox(s) }));
  return {
    id: shot?.id ?? null, present: true, stages, pending: stages.filter((s) => s.review).length,
    counts: Object.fromEntries(KNOWN.map((k) => [k, stages.filter((s) => s.status === k).length])),
  };
}

function cmdHtml(label, c) {
  if (!c) return "";
  const ph = c.placeholders.length ? ` <i>(điền: ${esc(c.placeholders.join(", "))})</i>` : "";
  const gpu = c.gpu ? ' <b class="gpu">LỆNH GPU — chỉ chép, trình duyệt không chạy</b>' : "";
  return `<div class="cmd"><span>${esc(label)}${gpu}${ph}</span><code data-copy="${esc(c.text)}">${esc(c.text)}</code></div>`;
}

function outHtml(o) {
  const bits = [o.text ? `<q>${esc(o.text)}</q>` : esc(o.name || o.path || o.kind), o.sha256 ? `sha ${shortSha(o.sha256)}` : "",
    o.seconds != null ? `${esc(o.seconds)} s` : "", o.exists === false ? "<b>file không còn trên đĩa</b>" : ""].filter(Boolean);
  const thumb = SAFE_URL.test(str(o.url)) && /image/u.test(str(o.kind)) ? `<img src="${esc(o.url)}" alt="" loading="lazy">` : "";
  return `<li>${thumb}${bits.join(" · ")}</li>`;
}

export function renderStageHtml(s) {
  const files = s.outs.length ? `<ul>${s.outs.map(outHtml).join("")}</ul>` : "";
  const facts = Object.entries(s.detail || {}).filter(([, v]) => v != null && typeof v !== "object")
    .map(([k, v]) => `${esc(k)}: <b>${esc(v)}</b>`).join(" · ");
  const checks = (s.detail?.wardrobe_checks || [])
    .map((c) => `<span class="chk ${c.present ? "ok" : "no"}">áo ref ${esc(c.prefix)}: ${c.present ? "có" : "THIẾU"}</span>`).join(" ");
  const rv = s.review ? `<div class="review"><b>CHỜ DUYỆT</b> — xem file ở trên (sha, số liệu), rồi chạy lệnh duyệt; sau đó chạy lệnh bước kế.
    ${cmdHtml("LỆNH DUYỆT", s.review.approvalCommand)}${s.review.note ? `<div class="note">${esc(s.review.note)}</div>` : ""}${cmdHtml("LỆNH CHẠY TIẾP", s.review.nextCommand)}</div>` : "";
  const mb = s.missingBox ? `<div class="miss"><b>CHƯA CÓ</b>${s.missingBox.reason ? ` — ${esc(s.missingBox.reason)}` : ""}${cmdHtml("LỆNH KẾ TIẾP", s.missingBox.command)}</div>` : "";
  const rf = s.refused ? `<div class="refused"><b>BỊ CHẶN</b> — ${esc(s.refused.reason)}${s.refused.unblocks ? `<br>Mở khóa: ${esc(s.refused.unblocks)}` : ""}</div>` : "";
  return `<section class="stage" data-stage="${esc(s.key)}" data-status="${esc(s.status)}"><h4><span class="n">${esc(s.code)}</span> ${esc(s.label)}
    <span class="st" style="color:${STATUS_COLOR[s.status]}">${STATUS_LABEL[s.status]}</span></h4>${s.statusRaw ? `<div class="note">status lạ: ${esc(s.statusRaw)}</div>` : ""}
    ${files}${facts ? `<div class="facts">${facts}</div>` : ""}${checks ? `<div>${checks}</div>` : ""}${rv}${mb}${rf}</section>`;
}

export function renderPipelineHtml(vm) {
  if (!vm.present) return '<div class="miss"><b>CHƯA CÓ</b> — dữ liệu ui-state chưa có pipeline cho shot này (chạy <code>jjv video ui-state --pipeline-config …</code>)</div>';
  return `<div class="pipeline"><h3>Shot ${esc(vm.id)} — toàn bộ pipeline · ${vm.pending} bước chờ duyệt</h3>${vm.stages.map(renderStageHtml).join("")}</div>`;
}

export const PIPELINE_CSS = `body{background:#fff;color:#0A2540;font:14px/1.45 system-ui,sans-serif;margin:16px}
.pipeline h3{margin:0 0 8px}.stage{border:1px solid #cfd8e6;border-radius:6px;padding:8px 10px;margin:8px 0;background:#F7FAFD}
.stage h4{margin:0 0 4px}.n{background:#0B4FD9;color:#fff;border-radius:3px;padding:0 6px;margin-right:4px}.st{float:right;font-weight:700}
.stage ul{margin:4px 0;padding-left:18px}.stage img{height:48px;vertical-align:middle;margin-right:6px;border:1px solid #cfd8e6}
.review{border:2px solid #B45309;background:#FFF;border-radius:4px;padding:6px 8px;margin-top:6px}.review>b{color:#B45309}
.miss{color:#5C6795;margin-top:6px}.refused{border:2px solid #D00000;border-radius:4px;padding:6px 8px;margin-top:6px;color:#D00000}
.cmd{margin:4px 0}.cmd span{display:block;font-size:12px;color:#5C6795}.cmd code{display:block;background:#0A2540;color:#fff;padding:4px 6px;border-radius:3px;word-break:break-all;cursor:copy}
.gpu{color:#D00000}.note{font-size:12px;color:#5C6795}.facts{font-size:12px;color:#5C6795}.chk.ok{color:#3E8914}.chk.no{color:#D00000;font-weight:700}`;
