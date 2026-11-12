// 单页应用主逻辑：登录 → 会话管理 → 事件流渲染 → 确认卡片/ask_user/上传下载。
// 凭据仅存内存（api.js 闭包），租约 holder 每标签页稳定（sessionStorage）。

import { api, uploadFile, fetchBlob, setToken, getToken, hasToken } from "./api.js";
import { openEventStream, bindAuth } from "./sse.js";
import { renderAgentHtml, enhanceMermaidBlocks } from "./render.js";

bindAuth(getToken);

const SENSITIVE_KEY = /pass|pwd|token|secret|code|verif|auth|phone|mobile|sms/i;
const SUMMARY_KEYS = [
  "brand", "model", "protocol", "protocol_type", "device_type", "device_name",
  "classify", "plan_id", "task_id", "report_id", "file_id", "file_name",
  "template_name", "node_count", "total", "count", "direction", "region",
];

// 工具入参/结果在气泡内的展示上限（超出截断，完整数据走下载产物）
const TOOL_DISPLAY_CAP = 20000;

const state = {
  username: "",
  sessions: [],
  activeId: "",
  stream: null,
  appliedSeq: {},      // session_id -> 已渲染的最大事件 seq（去重/游标）
  gateCards: {},       // session_id:tool:target -> 待确认卡元素（确认前去重刷屏）
  guardNotices: {},    // 弱提示行（内置写护栏/pdf 越界/绝对禁止），按 key 聚合计数
  pendingConfirmations: {},  // session_id -> 唯一会话口令待确认（无参写，供行首 /确认 铸票）
  pendingContinuations: {},  // session_id -> 本轮仍忙时登记的续跑待办（turn_done 补发）
  pendingAttachments: [],    // 当前 composer 待发送附件 {name, file, ref?}（chip 呈现，可删除）
  uploading: false,          // 附件上传中（防 submit 重入与 chip 删除竞态）
  initLock: false,           // 会话初始化中/失败（design D2：写路径锁定）
  lastCreate: null,          // 最近一次创建 {session_id, account_source, pat, remember}（失败回弹）
  turn: newTurnState(),
  replaying: false,
  turnActive: false,   // 当前是否有执行中的轮次（控制“停止”按钮）
  busyEl: null,        // 轮次进行中"转圈"指示元素（渲染在 #pending-cards）
};

const $ = (sel) => document.querySelector(sel);

function newTurnState() {
  return {
    agentBubble: null, agentText: "", agentVisible: false,
    hadToolCall: false, lastTool: "", toolEls: {}, lastToolGroup: null,
    turnGroup: null,   // 本轮工具调用统一折叠容器（懒建）
    renderTimer: null, // 流式节流渲染定时器（design D3）
  };
}

function holderId() {
  let h = sessionStorage.getItem("webchat_holder");
  if (!h) {
    h = Math.random().toString(36).slice(2) + Date.now().toString(36);
    sessionStorage.setItem("webchat_holder", h);
  }
  return h;
}

function notify(msg, isError = false, sticky = false) {
  const el = $("#compose-notice");
  el.textContent = msg;
  el.classList.toggle("error-text", isError);
  el.classList.toggle("notice-text", !isError);
  clearTimeout(notify._t);
  // sticky：上传期间忙碌提示常驻，直至被结果提示替换
  if (!sticky) { notify._t = setTimeout(() => { el.textContent = ""; }, 6000); }
}

// 滚动锚定（design D3）：距底超阈值视为上翻，不强制拉底；贴底恢复跟随
const AUTOSCROLL_THRESHOLD_PX = 120;

function nearBottom(box) {
  return box.scrollHeight - box.scrollTop - box.clientHeight
    < AUTOSCROLL_THRESHOLD_PX;
}

// ── 助手消息富渲染（design D3）：节流重渲染 + 结束时最终精确渲染 ──

const RENDER_THROTTLE_MS = 300;

function scheduleAgentRender() {
  const t = state.turn;
  if (t.renderTimer) { return; }
  t.renderTimer = setTimeout(() => {
    t.renderTimer = null;
    flushAgentRender();
  }, RENDER_THROTTLE_MS);
}

function flushAgentRender() {
  // markdown → 消毒 → 注入当前助手气泡；任一环节失败降级纯文本；
  // mermaid 块异步增强（懒加载，strict 模式）
  const t = state.turn;
  if (!t.agentBubble || !t.agentVisible) { return; }
  const box = $("#messages");
  const stick = nearBottom(box);
  try {
    t.agentBubble.innerHTML = renderAgentHtml(t.agentText);
    enhanceMermaidBlocks(t.agentBubble);
  } catch (_) {
    t.agentBubble.textContent = t.agentText;
  }
  if (stick) { box.scrollTop = box.scrollHeight; }
}

function cancelAgentRenderTimer() {
  const t = state.turn;
  if (t.renderTimer) { clearTimeout(t.renderTimer); t.renderTimer = null; }
}

function push(node) {
  const box = $("#messages");
  const stick = nearBottom(box); // 先取贴底态再入树（新节点会改变 scrollHeight）
  box.appendChild(node);
  if (stick) { box.scrollTop = box.scrollHeight; }
  return node;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) { node.className = cls; }
  if (text !== undefined) { node.textContent = text; }
  return node;
}

// 代码块复制（事件委托）：内容取自消毒后 DOM 文本（与源码一致）；
// Clipboard API 需安全上下文，非安全上下文回退 execCommand
function copyViaExec(text) {
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch (_) {
    return false;
  }
}

function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text).then(() => true)
      .catch(() => copyViaExec(text));
  }
  return Promise.resolve(copyViaExec(text));
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest(".btn-code-copy");
  if (!btn) { return; }
  const block = btn.closest(".code-block");
  const codeEl = block ? block.querySelector("pre code") : null;
  if (!codeEl) { return; }
  copyText(String(codeEl.textContent || "")).then((ok) => {
    if (!ok) { notify("复制失败", true); return; }
    btn.textContent = "已复制";
    setTimeout(() => { btn.textContent = "复制"; }, 1500);
  });
});

// ── 轮次进行中"转圈"指示（渲染在消息流外的 #pending-cards） ──

function showBusy() {
  if (state.replaying || state.busyEl) { return; }
  const box = el("div", "turn-busy");
  box.appendChild(el("span", "spinner", ""));
  box.appendChild(el("span", "", "任务进行中，请稍候…"));
  $("#pending-cards").appendChild(box);
  state.busyEl = box;
}

function hideBusy() {
  if (state.busyEl) { state.busyEl.remove(); state.busyEl = null; }
}

function setTurnActive(active) {
  state.turnActive = !!active;
  const btn = $("#btn-send");
  if (!btn) { return; }
  btn.classList.toggle("is-stop", state.turnActive);
  // 初始化锁优先于轮次状态（creating/failed 会话不可发送，design D2）
  btn.disabled = state.initLock;
  btn.textContent = state.turnActive && !state.initLock ? "⏹ 停止" : "发送";
  btn.title = state.turnActive && !state.initLock
    ? "中止当前任务（已完成的写入不回滚）"
    : "发送";
}

// 会话初始化状态：creating 锁写路径并提示进度；ready 解锁；failed 锁定待删
function setSessionInit(status) {
  state.initLock = status === "creating" || status === "failed";
  $("#msg-input").disabled = state.initLock;
  $("#btn-attach").disabled = state.initLock;
  $("#model-select").disabled = state.initLock;
  setTurnActive(state.turnActive);
  if (status === "creating") {
    notify("正在初始化（连接平台/加载模型）…", false, true);
  } else if (status !== "failed") {
    notify(""); // 就绪：清掉 sticky 初始化提示，恢复正常提示流
  }
}

// 本轮所有工具调用/结果折叠进一个可展开容器，避免大任务刷屏
function ensureTurnGroup() {
  const t = state.turn;
  if (t.turnGroup) { return t.turnGroup; }
  const det = el("details", "tool-group");
  const summary = el("summary", "", "🔧 执行中…");
  const body = el("div", "tool-group-body", "");
  det.appendChild(summary);
  det.appendChild(body);
  push(det);
  t.turnGroup = { det, summary, body, count: 0 };
  return t.turnGroup;
}

// ── 登录 / 登出 ──

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("#login-btn");
  $("#login-error").textContent = "";
  btn.disabled = true;
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: { username: $("#login-user").value.trim(), password: $("#login-pass").value },
    });
    setToken(data.session_token);
    state.username = data.username;
    $("#login-pass").value = ""; // 口令不回显不留存
    enterAppView();
  } catch (err) {
    $("#login-error").textContent = err.message || "登录失败";
    $("#login-pass").value = "";
  } finally {
    btn.disabled = false;
  }
});

$("#btn-logout").addEventListener("click", () => { doLogout(true); });

async function doLogout(callApi) {
  if (callApi && hasToken()) {
    try { await api("/api/auth/logout", { method: "POST" }); } catch (_) { /* 忽略 */ }
  }
  if (state.stream) { state.stream.close(); state.stream = null; }
  setToken("");
  state.activeId = "";
  state.appliedSeq = {};
  $("#view-app").classList.add("hidden");
  $("#view-login").classList.remove("hidden");
  // 回登录页复位文档滚动并失焦（键盘收起残留兜底，spec MUST）
  window.scrollTo(0, 0);
  if (document.activeElement instanceof HTMLElement) {
    document.activeElement.blur();
  }
}

function enterAppView() {
  $("#view-login").classList.add("hidden");
  $("#view-app").classList.remove("hidden");
  $("#whoami").textContent = state.username;
  // iOS 键盘收起后残留的文档滚动偏移会顶出顶栏：切视图统一复位并失焦
  window.scrollTo(0, 0);
  if (document.activeElement instanceof HTMLElement) {
    document.activeElement.blur();
  }
  refreshSessions();
}

// 全局 401：登录态失效回登录页
function handleErr(err) {
  if (err && err.status === 401) { doLogout(false); notify("登录状态已失效，请重新登录", true); return; }
  notify(err && err.message ? err.message : "请求失败", true);
}

// ── 会话管理 ──

async function refreshSessions() {
  try {
    const data = await api("/api/sessions");
    state.sessions = data.sessions;
    renderSessionList();
  } catch (err) { handleErr(err); }
}

function renderSessionList() {
  const ul = $("#session-list");
  ul.innerHTML = "";
  for (const s of state.sessions) {
    const li = el("li", "session-item" + (s.session_id === state.activeId ? " active" : "") + (s.closed ? " session-closed" : ""));
    li.dataset.id = s.session_id;
    let label = `会话 ${short(s.session_id)}`;
    if (s.status === "creating") { label = `会话 ${short(s.session_id)}（初始化中…）`; }
    else if (s.status === "failed") { label = `会话 ${short(s.session_id)}（创建失败）`; }
    else if (s.closed) { label = `会话 ${short(s.session_id)}（已结束）`; }
    li.appendChild(el("div", "", label));
    li.appendChild(el("div", "sid", s.session_id));
    const row = el("div", "row");
    const mk = (label, fn, cls = "ghost-btn") => {
      const b = el("button", cls, label);
      b.type = "button";
      b.addEventListener("click", fn);
      row.appendChild(b);
    };
    if (s.status !== "failed") {
      mk("打开", () => openSession(s.session_id));
      if (!s.closed) { mk("结束", async () => { try { await api(`/api/sessions/${s.session_id}/close`, { method: "POST" }); await refreshSessions(); } catch (err) { handleErr(err); } }); }
    }
    mk("删除", async () => {
      try {
        await api(`/api/sessions/${s.session_id}`, { method: "DELETE" });
        if (s.session_id === state.activeId) {
          if (state.stream) { state.stream.close(); state.stream = null; }
          state.activeId = "";
          $("#messages").innerHTML = "";
        }
        await refreshSessions();
      } catch (err) { handleErr(err); }
    });
    li.appendChild(row);
    ul.appendChild(li);
  }
}

function short(id) { return id.slice(0, 8); }

// 会话口令确认：只认行首 /确认（后随空白或行尾），正文中嵌入不触发。
const CHAT_CONFIRM_RE = /^\/确认(?=$|\s)/;

function isChatConfirmCommand(text) {
  return CHAT_CONFIRM_RE.test(String(text || "").trim());
}

// 打开新建会话对话框；errorText/prefill 用于失败回弹回填（design D2）
function openNewSessionDialog(errorText, prefill) {
  $("#new-session-error").textContent = errorText || "";
  const source = prefill ? prefill.account_source : "default";
  $("#byo-pat").value = prefill ? prefill.pat : "";
  $("#remember-pat").checked = prefill ? prefill.remember : false;
  document.querySelector(
    `input[name="account-source"][value="${source}"]`
  ).checked = true;
  syncAccountSource();
  $("#new-session-dialog").classList.remove("hidden");
}

$("#btn-new-session").addEventListener("click", () => {
  openNewSessionDialog();
});

function syncAccountSource() {
  const byo = document.querySelector('input[name="account-source"]:checked').value === "byo";
  $("#byo-pat-label").classList.toggle("hidden", !byo);
  $("#remember-pat-label").classList.toggle("hidden", !byo);
  if (byo) { prefillRememberedPat(); } else { $("#btn-clear-pat").classList.add("hidden"); }
}

async function prefillRememberedPat() {
  try {
    const r = await api("/api/account/qoder-pat");
    if (r.pat && !$("#byo-pat").value) {
      $("#byo-pat").value = r.pat;
      $("#remember-pat").checked = true;
    }
    $("#btn-clear-pat").classList.toggle("hidden", !r.pat);
  } catch (_) { /* 预填失败不阻塞新建会话 */ }
}

$("#btn-clear-pat").addEventListener("click", async () => {
  try {
    await api("/api/account/qoder-pat", { method: "DELETE" });
    $("#byo-pat").value = "";
    $("#remember-pat").checked = false;
    $("#btn-clear-pat").classList.add("hidden");
  } catch (err) { handleErr(err); }
});
document.querySelectorAll('input[name="account-source"]').forEach((el) => {
  el.addEventListener("change", syncAccountSource);
});

$("#btn-new-session-cancel").addEventListener("click", () => {
  $("#new-session-dialog").classList.add("hidden");
});

$("#new-session-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const notice = $("#new-session-error");
  notice.textContent = "";
  const account_source = document.querySelector('input[name="account-source"]:checked').value;
  const pat = account_source === "byo" ? $("#byo-pat").value.trim() : "";
  const remember = account_source === "byo" && $("#remember-pat").checked;
  const btn = $("#btn-new-session-ok");
  btn.disabled = true;
  try {
    const r = await api("/api/sessions", {
      method: "POST", body: { account_source, pat, remember },
    });
    // 记录本次创建上下文：session_failed 命中时回弹弹窗（自带 PAT 回填）
    state.lastCreate = { session_id: r.session_id, account_source, pat, remember };
    $("#new-session-dialog").classList.add("hidden");
    $("#byo-pat").value = "";
    await refreshSessions();
    await openSession(r.session_id);
  } catch (err) {
    if (err.status === 401) { handleErr(err); return; }
    notice.textContent = err.message || "创建会话失败";
  } finally {
    btn.disabled = false;
  }
});

async function openSession(id) {
  if (state.stream) { state.stream.close(); state.stream = null; }
  hideBusy(); // 切会话清掉上一会话残留的进行中指示
  state.activeId = id;
  state.turn = newTurnState();
  state.gateCards = {}; // 切换会话重置待确认卡去重注册表
  state.guardNotices = {}; // 切换会话重置路径护栏弱提示
  state.pendingAttachments = []; // 切会话清暂存附件，避免串到新会话上传
  renderAttachments();
  delete state.appliedSeq[id]; // 重新回放，避免历史事件被去重丢弃
  $("#messages").innerHTML = "";
  $("#sidebar").classList.remove("open");
  renderSessionList();
  let last = 0;
  try {
    const hist = await api(`/api/sessions/${id}/history`);
    state.replaying = true;
    for (const ev of hist.events) { applyEvent(ev); last = ev.seq; }
    state.replaying = false;
  } catch (err) { handleErr(err); return; }
  await ensureLease(id);
  await loadModels(id);
  const meta = state.sessions.find((s) => s.session_id === id);
  // 按列表 meta.status 设初始态（刷新后同样适用，design D2）
  setSessionInit(meta ? meta.status : "creating");
  setTurnActive(!!(meta && meta.turn_running && !meta.closed));
  state.stream = openEventStream(id, {
    lastSeq: last,
    onEvent: (ev) => applyEvent(ev),
  });
}

// ── 模型选择：清单随账号，消息级切换 ──

async function loadModels(id) {
  const sel = $("#model-select");
  sel.innerHTML = "";
  // 占位 option：加载中/清单为空/请求失败时下拉不得仅余空箭头（spec MUST）
  const ph = document.createElement("option");
  ph.value = "";
  ph.disabled = true;
  ph.selected = true;
  ph.textContent = "模型加载中…";
  sel.appendChild(ph);
  try {
    const r = await api(`/api/sessions/${id}/models`);
    if ((r.models || []).length) { sel.innerHTML = ""; }
    for (const m of r.models || []) {
      const opt = document.createElement("option");
      opt.value = m.value;
      // 成本标记：price_factor 优先（平台 is_free 与系数可能矛盾，实测确认）
      const cost = m.price_factor != null ? `×${m.price_factor}`
        : (m.is_free ? "免费" : "");
      opt.textContent = cost ? `${m.display_name}（${cost}）` : m.display_name;
      sel.appendChild(opt);
    }
    if (r.current_model) { sel.value = r.current_model; }
  } catch (err) { handleErr(err); }
}

$("#model-select").addEventListener("change", async () => {
  if (!state.activeId) { return; }
  const model = $("#model-select").value;
  try {
    await withLease(() => api(`/api/sessions/${state.activeId}/model`, {
      method: "POST", body: { model }, headers: { "x-holder-id": holderId() },
    }));
  } catch (err) {
    handleErr(err);
    await loadModels(state.activeId); // 拒绝时回退到服务端当前值
  }
});

// ── 写租约：先取后发；丢失自动重取，不当作业务失败 ──

async function ensureLease(id, silent = false) {
  const body = { holder_id: holderId() };
  try {
    await api(`/api/sessions/${id}/lease`, { method: "POST", body });
    return true;
  } catch (err) {
    if (err.status === 409) {
      // 同用户其他标签页持有：静默接管（切换持有者不是业务失败）
      try {
        await api(`/api/sessions/${id}/lease`, { method: "POST", body: { ...body, takeover: true } });
        return true;
      } catch (err2) {
        if (!silent) { handleErr(err2); }
        return false;
      }
    }
    if (!silent) { handleErr(err); }
    return false;
  }
}

async function withLease(fn) {
  try {
    return await fn();
  } catch (err) {
    if (err.status === 409 && /租约/.test(err.detail || "")) {
      if (await ensureLease(state.activeId, true)) {
        return await fn(); // 重取租约后仅重发一次
      }
      throw new Error("租约恢复失败，请稍后重试");
    }
    throw err;
  }
}

// 租约心跳：活跃会话定期续期
setInterval(() => {
  if (state.activeId && hasToken()) { ensureLease(state.activeId, true); }
}, 20000);

// ── 消息发送 / 上传 ──

async function sendMessage(text) {
  if (!state.activeId) { notify("请先新建或打开一个会话", true); return false; }
  try {
    await withLease(() => api(`/api/sessions/${state.activeId}/messages`, {
      method: "POST", body: { text }, headers: { "x-holder-id": holderId() },
    }));
    showBusy(); // 发送成功即进入"任务进行中"态，直到 turn_done/error/待确认
    setTurnActive(true);
    return true;
  } catch (err) {
    if (err.status === 409 && /上一轮仍在执行/.test(err.detail || "")) {
      setTurnActive(true);
    }
    handleErr(err);
    return false;
  }
}

async function abortTurn() {
  if (!state.activeId || !state.turnActive) { return; }
  if (!window.confirm("确定中止当前任务？已完成的建档不会回滚。")) { return; }
  const btn = $("#btn-send");
  btn.disabled = true;
  btn.textContent = "中止中…";
  try {
    const r = await withLease(() => api(`/api/sessions/${state.activeId}/abort`, {
      method: "POST", body: {},
      headers: { "x-holder-id": holderId() },
    }));
    if (r.aborted || (r.tasks_cancelled || []).length) {
      notify("正在中止任务；已完成的写入不会回滚");
      setTurnActive(false); // 复位按钮，不依赖 SSE 事件送达
    } else {
      notify("当前没有执行中的任务");
      setTurnActive(false);
    }
  } catch (err) {
    if (err.status === 404) {
      notify("服务端尚未加载中止接口，请重启 webchat 服务后重试", true);
    } else {
      handleErr(err);
    }
    setTurnActive(state.turnActive);
  }
}

$("#compose-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (state.turnActive) { await abortTurn(); return; }
  if (state.uploading) { return; } // 上传中防重入（避免重复上传同一批附件）
  const input = $("#msg-input");
  const text = input.value.trim();
  const hasAttachments = state.pendingAttachments.length > 0;
  if (!text && !hasAttachments) { return; }
  // 行首 /确认 优先尝试会话口令铸票（无附件时）；否则按普通文本发送。
  if (!hasAttachments && await handleChatConfirm(text)) { input.value = ""; return; }
  if (hasAttachments) { await uploadStagedAttachments(); }
  const refs = state.pendingAttachments.filter((a) => a.ref).map((a) => a.ref);
  const full = [text, ...refs].filter(Boolean).join("\n");
  if (!full) { return; }
  if (await sendMessage(full)) {
    input.value = "";
    // 只清已上传并随消息送出的 chip；上传失败（无 ref）保留以便重试或移除
    state.pendingAttachments = state.pendingAttachments.filter((a) => !a.ref);
    renderAttachments();
  }
});

$("#msg-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("#compose-form").requestSubmit();
  }
});

$("#msg-input").addEventListener("input", () => {
  const ta = $("#msg-input");
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
});

// 占位符双态（design D5）：失焦紧凑短文案，聚焦展开完整前缀释义
// （MODIFIED requirement：语义可达 + 紧凑形态）
const PLACEHOLDER_COMPACT = "输入消息，Enter 发送；可选前缀 /web /xlpa";
const PLACEHOLDER_FULL = "输入消息，Enter 发送（无会话时请先新建）；可选前缀：/web 强制网页检索、/xlpa 强制协议助手（默认自动判断）";
$("#msg-input").addEventListener("focus", () => {
  $("#msg-input").placeholder = PLACEHOLDER_FULL;
});
$("#msg-input").addEventListener("blur", () => {
  // 输入非空时占位符本就不显示，直接恢复紧凑态无副作用
  $("#msg-input").placeholder = PLACEHOLDER_COMPACT;
});

// 上传通道按扩展名自动匹配：选错通道会把 PDF 当建档表格代理，得到上游 400。
const UPLOAD_CHANNEL_BY_EXT = {
  ".xlsx": "archive_table", ".xls": "archive_table", ".xlsm": "archive_table",
  ".png": "screenshot", ".jpg": "screenshot", ".jpeg": "screenshot",
  ".webp": "screenshot", ".bmp": "screenshot", ".gif": "screenshot",
};

function channelForFile(name) {
  const dot = String(name || "").lastIndexOf(".");
  const ext = dot >= 0 ? String(name).slice(dot).toLowerCase() : "";
  return UPLOAD_CHANNEL_BY_EXT[ext] || "document";
}

$("#btn-attach").addEventListener("click", () => {
  if (!state.activeId) { notify("请先新建或打开一个会话", true); return; }
  $("#upload-file").click();
});

$("#upload-file").addEventListener("change", () => {
  const fileEl = $("#upload-file");
  const files = Array.from(fileEl.files || []);
  fileEl.value = "";
  if (!files.length || !state.activeId) { return; }
  // 先暂存（不上传/不解析），发送时才上传；✕ 可在上传前移除
  for (const file of files) {
    state.pendingAttachments.push({ name: file.name, file });
  }
  renderAttachments();
});

function renderAttachments() {
  const wrap = $("#attachment-chips");
  wrap.innerHTML = "";
  state.pendingAttachments.forEach((att, i) => {
    const chip = el("span", "attachment-chip", "");
    chip.appendChild(el("span", "chip-name", att.name));
    const del = el("button", "chip-delete", "✕");
    del.type = "button";
    del.title = "移除附件";
    del.addEventListener("click", () => removeAttachment(i));
    chip.appendChild(del);
    wrap.appendChild(chip);
  });
}

function removeAttachment(i) {
  if (state.uploading) { return; } // 上传中禁删，避免迭代竞态
  state.pendingAttachments.splice(i, 1);
  renderAttachments();
}

async function uploadStagedAttachments() {
  // 发送时上传暂存附件；成功标记 ref（chip 保留至发送成功），失败保留 file 以便重试
  const btn = $("#btn-attach");
  btn.disabled = true;
  state.uploading = true; // 防 submit 重入与 chip 删除竞态
  for (const att of state.pendingAttachments) {
    if (att.ref) { continue; } // 已上传，复用 ref（发送失败重试不重复上传）
    const channel = channelForFile(att.name); // 通道按扩展名自动匹配
    notify(`上传中… ${att.name}`, false, true);
    try {
      const res = await uploadFile(`/api/sessions/${state.activeId}/artifacts/upload`, channel, att.file);
      // 引用文案按通道语义：图片双落盘（原图 + OCR 兜底）；OCR 失败显式说明
      let ref;
      if (res.file_id) {
        ref = `建档表格已上传 file_id=${res.file_id}`;
      } else if (res.ocr_error) {
        ref = `已上传图片 ${res.path}（助手可直接查看）；OCR 识别失败：${res.ocr_error}`;
      } else if (res.ocr_path) {
        ref = `已上传图片 ${res.path}（助手可直接查看）；OCR 文本 ${res.ocr_path}（读不了图时用）`;
      } else {
        ref = `已上传文件 ${res.path}`;
      }
      if (res.text_status === "pending") {
        ref = `已上传文件 ${res.path}（PDF 内容自动结构化提取到 ${res.path.replace(/\.pdf$/, ".pdf.md")}，读取内容请用后者）`;
        notify(`上传成功：${att.name}；PDF 文本提取在后台进行，完成后会提示`);
      } else if (res.warning) {
        notify(`上传成功：${att.name}；${res.warning}`, true);
      } else {
        notify(`上传成功：${att.name}${res.text_path ? `；已提取文本 ${res.text_path}` : ""}`);
      }
      att.ref = ref;
    } catch (err) {
      handleErr(err); // 失败保留 file（无 ref），下次重试
    }
  }
  btn.disabled = false;
  state.uploading = false;
  renderAttachments();
}

// ── 事件渲染 ──

function applyEvent(ev) {
  if (!ev || typeof ev.type !== "string") { return; }
  const seen = state.appliedSeq[ev.session_id] || 0;
  if (ev.seq && ev.seq <= seen) { return; } // 重放/重连去重
  if (ev.seq) { state.appliedSeq[ev.session_id] = ev.seq; }
  const t = state.turn;
  switch (ev.type) {
    case "session_started":
      if (ev.payload.username) { push(el("div", "sys-line", "会话已开始")); }
      break;
    case "session_ready":
      // 初始化完成：解锁输入区并加载模型清单（重放路径同样生效）
      setSessionInit("ready");
      notify("会话已就绪");
      loadModels(ev.session_id);
      break;
    case "session_failed": {
      const p = ev.payload || {};
      hideBusy();
      push(el("div", "banner-error",
        `会话初始化失败：${p.message || "未知原因"}`));
      if (state.lastCreate
          && state.lastCreate.session_id === ev.session_id
          && state.lastCreate.account_source === "byo") {
        // 自带 PAT 失败：重开创建对话框回填原因与输入（不丢已输内容）
        openNewSessionDialog(p.message || "创建失败", state.lastCreate);
      } else {
        notify("会话创建失败，可在会话列表删除后重试", true);
      }
      state.lastCreate = null;
      refreshSessions();
      break;
    }
    case "text_delta": {
      const text = ev.payload.text || "";
      if (!text) { break; }
      if (ev.payload.role === "user") {
        // 用户消息保持纯文本（design D8，不按 markdown 解释）
        push(el("div", "bubble user", text));
      } else {
        if (!t.agentBubble) { t.agentBubble = push(el("div", "bubble agent", "")); }
        t.agentText += text;
        t.agentVisible = true;
        scheduleAgentRender(); // 节流富渲染：未闭合语法按文本兜底
      }
      break;
    }
    case "tool_call":
      t.hadToolCall = true;
      renderToolCall(ev);
      break;
    case "tool_result":
      renderToolResult(ev);
      break;
    case "gate_blocked": {
      // 仅「需用户决策」的拦截才暂停转圈并弹卡：写入/删除确认可解除
      // （confirmable!==false），或参数表单卡（需补充信息）。护栏自纠错
      // （guard）与绝对禁止类（confirmable===false，如 login/读越界）不
      // 打断进度——后者本就无法经确认解除，助手会自纠错或本就应拒绝。
      const _gp = ev.payload || {};
      const _blocking = !_gp.guard && _gp.confirmable !== false;
      if (_blocking) { hideBusy(); }
      renderGateCard(ev);
      break;
    }
    case "ask_user":
      hideBusy(); // 等待用户补充：暂停转圈
      renderAskCard(ev);
      break;
    case "artifact":
      renderArtifact(ev);
      break;
    case "upload_text": {
      const p = ev.payload || {};
      if (p.warning) {
        push(el("div", "banner-error", `PDF 文本提取失败：${p.warning}`));
      } else if (p.text_path) {
        push(el("div", "sys-line",
          `已提取 PDF 文本：${p.text_path}（${p.text_chars || 0} 字）`));
      }
      break;
    }
    case "turn_aborted": {
      const p = ev.payload || {};
      const tasks = (p.tasks_cancelled || []).length;
      push(el("div", "sys-line",
        `任务已中止${tasks ? `（已请求中止 ${tasks} 个服务端批次）` : ""}；已完成的写入不会回滚`));
      hideBusy();
      setTurnActive(false);
      cancelAgentRenderTimer();
      flushAgentRender(); // 中止前把已到达文本精确渲染，不丢内容
      state.turn = newTurnState();
      // 中止：清空本轮被阻塞的续跑待办（避免向已终止的轮次补发）。
      delete state.pendingContinuations[ev.session_id];
      break;
    }
    case "turn_done":
      finishTurn(ev);
      break;
    case "error":
      hideBusy();
      push(el("div", "banner-error", `执行错误：${ev.payload.message || "未知"}`));
      break;
    case "session_closed":
      push(el("div", "sys-line", "会话已结束"));
      setTurnActive(false);
      break;
    default:
      // unknown 等未定义语义事件：安全忽略，不中断渲染流
      break;
  }
}

function briefInput(input) {
  // 前端侧同样做白名单+敏感键过滤（工具调用实时展示用）
  const parts = [];
  for (const key of SUMMARY_KEYS) {
    const v = input && input[key];
    if (typeof v !== "string" && typeof v !== "number") { continue; }
    if (SENSITIVE_KEY.test(key)) { continue; }
    let s = String(v);
    if (s.length > 40) { s = s.slice(0, 39) + "…"; }
    parts.push(`${key}=${s}`);
    if (parts.length >= 6) { break; }
  }
  return parts.join(" · ");
}

function sanitizeValue(v) {
  // 递归遮蔽敏感键值，展开体不得回显原始凭据（spec 4.1：无原始凭据）
  if (Array.isArray(v)) { return v.map(sanitizeValue); }
  if (v && typeof v === "object") {
    const out = {};
    for (const [k, val] of Object.entries(v)) {
      out[k] = SENSITIVE_KEY.test(k) ? "***" : sanitizeValue(val);
    }
    return out;
  }
  return v;
}

function redactText(text) {
  // 结果为结构化 JSON 时按敏感键遮蔽；纯文本按业务数据原样展示
  const trimmed = (text || "").trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) { return text; }
  try {
    return JSON.stringify(sanitizeValue(JSON.parse(trimmed)), null, 1);
  } catch (_) {
    return text;
  }
}

function renderToolCall(ev) {
  const t = state.turn;
  const rawName = ev.payload.name || "";
  const name = rawName.split("__").pop() || rawName;
  t.lastTool = name;
  const brief = briefInput(ev.payload.input);
  const tg = ensureTurnGroup();
  tg.count += 1;
  tg.summary.textContent = `🔧 执行中 · 已调用 ${tg.count} 个工具`;
  // 连续同名工具调用聚合为一行（×N），避免逐个刷屏
  let grp = t.lastToolGroup;
  if (!grp || grp.name !== name) {
    const det = el("details", "tool");
    const summary = el("summary", "", "");
    det.appendChild(summary);
    const body = el("div", "tool-body", "");
    det.appendChild(body);
    tg.body.appendChild(det);
    grp = { name, det, summary, body, count: 0 };
    t.lastToolGroup = grp;
  }
  grp.count += 1;
  grp.summary.textContent =
    `🔧 ${name}${grp.count > 1 ? ` ×${grp.count}` : ""}${brief ? `（${brief}）` : ""}`;
  const inputStr = JSON.stringify(sanitizeValue(ev.payload.input || {}), null, 1);
  grp.body.textContent += `\n▶ 调用 #${grp.count}${brief ? `（${brief}）` : ""}\n${inputStr.slice(0, TOOL_DISPLAY_CAP)}`;
  if (ev.payload.id) { t.toolEls[ev.payload.id] = { det: grp.det, body: grp.body }; }
}

function renderToolResult(ev) {
  const t = state.turn;
  let text = "";
  const content = ev.payload.content;
  if (typeof content === "string") { text = content; }
  else if (Array.isArray(content)) {
    text = content.map((b) => (typeof b === "string" ? b : (b && b.text) || "")).join("\n");
  }
  const slot = t.toolEls[ev.payload.tool_use_id];
  const safeText = redactText(text);
  const truncated = safeText.length > TOOL_DISPLAY_CAP;
  const target = slot ? slot.body : (() => {
    const tg = ensureTurnGroup();
    const det = el("details", "tool");
    det.appendChild(el("summary", "", "📦 工具结果"));
    const body = el("div", "tool-body", "");
    det.appendChild(body);
    tg.body.appendChild(det);
    return body;
  })();
  let shown = safeText.slice(0, TOOL_DISPLAY_CAP);
  if (truncated) {
    shown += `\n…（内容较大，已截断显示，完整约 ${fmtSize(safeText.length)}）`;
  }
  target.textContent += `\n— 结果${ev.payload.is_error ? "（失败）" : ""} —\n${shown}`;
  if (ev.payload.is_error && slot) { slot.det.classList.add("err"); }
}

function renderGateCard(ev) {
  const p = ev.payload;
  // 内置写入路径护栏属"自纠错型"拒绝：弱化为一行提示，不渲染禁止卡
  if (p.guard === "builtin_write_path") {
    renderWriteGuardNotice(ev);
    return;
  }
  if (p.guard === "pdf_binary") {
    // 自纠错型拒绝：把“读 PDF”引导为“读同名 .pdf.md”，不渲染禁止卡
    const key = `pdf:${ev.session_id}`;
    const prevPdf = state.guardNotices[key];
    if (prevPdf) {
      prevPdf.count += 1;
      prevPdf.line.textContent =
        `已拦截 ${prevPdf.count} 次直接读取 PDF，请助手改读同名 .pdf.md`;
      return;
    }
    const line = push(el("div", "sys-line guard-line",
      "已拦截 1 次直接读取 PDF，请助手改读同名 .pdf.md"));
    state.guardNotices[key] = { line, count: 1 };
    return;
  }
  // 绝对禁止 / 无需用户决策的拦截（confirmable===false，如 login、读越界）：
  // 降级为一行弱提示，不渲染阻断卡、不打断进度（助手会自纠错或本就禁止）。
  if (p.confirmable === false) {
    renderForbiddenNotice(ev);
    return;
  }
  // 无参写入（会话口令确认）：不弹模态卡，记唯一 pending + 弱提示，
  // 由模型在会话播报摘要并请求行首 /确认，确认后转新一轮带票重跑。
  if (p.confirm_kind === "chat_confirm") {
    renderChatConfirmPrompt(ev);
    return;
  }
  // 去重刷屏：同一 tool+target 确认前反复被拦截（模型重试）时复用同一张卡，
  // 仅累加「已拦截 N 次」，不再堆叠新卡（键含 session_id，跨会话不串）。
  const gateKey = `${ev.session_id}:${p.tool_name || ""}:${p.target || ""}`;
  const prev = state.gateCards[gateKey];
  if (prev && prev.card && !prev.card.classList.contains("done")) {
    prev.retries += 1;
    if (prev.badge) {
      prev.badge.textContent = `⚠️ 待确认：${p.tool_name || ""}（已拦截 ${prev.retries} 次）`;
    }
    return;
  }
  const card = el("div", "card-gate");
  const retries = 1;
  let badge = null;
  const fields = Array.isArray(p.param_schema) ? p.param_schema : [];
  const hasForm = fields.length > 0;
  card.appendChild(el("h3", "", hasForm
    ? `请补充信息：${p.tool_name || ""}`
    : `⚠️ 待确认：${p.tool_name || ""}`));
  badge = card.querySelector("h3");
  state.gateCards[gateKey] = { card, badge, retries };
  card.appendChild(el("p", "reason", p.reason || ""));
  const form = {};
  if (hasForm) {
    // 参数表单：被门拦下且该工具登记了入参时，首张卡即收集所需参数，
    // 敏感字段以 password 型掩码；确认时铸票并把参数随续跑消息转达助手。
    for (const f of fields) {
      const lab = el("label", "gate-field", "");
      lab.appendChild(el("span", "gate-label",
        `${f.label || f.name}${f.required ? " *" : "（可选）"}`));
      const input = el("input");
      input.type = f.sensitive ? "password" : "text";
      input.name = f.name;
      input.required = !!f.required;
      if (f.prefilled) { input.value = String(f.prefilled); }
      input.placeholder = f.sensitive ? "（输入后掩码保存，不回显）" : "请输入";
      lab.appendChild(input);
      card.appendChild(lab);
      form[f.name] = { input, required: !!f.required, label: f.label || f.name };
    }
  } else {
    const summary = p.arg_summary || {};
    if (Object.keys(summary).length) {
      const table = document.createElement("table");
      for (const [k, v] of Object.entries(summary)) {
        const tr = document.createElement("tr");
        tr.appendChild(el("td", "k", k));
        tr.appendChild(el("td", "", String(v)));
        table.appendChild(tr);
      }
      card.appendChild(table);
    }
    // 无登记参数时保留通用补充说明框（随确认一并发送）
    const noteInput = el("input");
    noteInput.type = "text";
    noteInput.placeholder = "可补充说明，随确认一并发送";
    card.appendChild(noteInput);
    form.__note = { input: noteInput, required: false, label: "补充说明" };
  }
  const result = el("p", "result", "");
  const row = el("div", "row");
  const okBtn = el("button", "primary-btn", hasForm ? "确认并提交" : "确认");
  const noBtn = el("button", "ghost-btn", "忽略");
  okBtn.type = "button";
  noBtn.type = "button";
  okBtn.addEventListener("click", async () => {
    // 校验必填；缺失则提示不发请求。收集已填参数（含 prefilled）。
    const collected = [];
    let missing = false;
    for (const key of Object.keys(form)) {
      const item = form[key];
      const val = (item.input.value || "").trim();
      if (item.required && !val) { item.input.classList.add("invalid"); missing = true; continue; }
      item.input.classList.remove("invalid");
      if (val) { collected.push({ name: key === "__note" ? "note" : key, label: item.label, val }); }
    }
    if (missing) {
      result.textContent = "请填写标 * 的必填项后再确认";
      result.style.color = "var(--danger)";
      return;
    }
    okBtn.disabled = true;
    try {
      const r = await withLease(() => api(`/api/sessions/${ev.session_id}/confirm`, {
        method: "POST", body: { target: p.target || p.tool_name, tool_name: p.tool_name || "" },
        headers: { "x-holder-id": holderId() },
      }));
      card.classList.add("done");
      card.querySelector("h3").textContent = `✅ 已确认：${p.tool_name || ""}`;
      const until = r.expires_at ? new Date(r.expires_at * 1000).toLocaleTimeString() : "";
      result.textContent = `已确认，窗口内同目标调用放行${until ? `（至 ${until}）` : ""}`;
      // 同会话轮次串行：本轮仍在执行时不直接发续跑（会 409 且打乱轮次），
      // 登记为待办，待本轮 turn_done 自动补发（修复“立刻点确认”竞态丢弃）。
      if (!state.replaying && ev.session_id === state.activeId) {
        let cont = "（已确认，请继续执行之前被暂停的任务）";
        if (collected.length) {
          const lines = collected.map((c) => `- ${c.name}（${c.label}）：${c.val}`).join("\n");
          cont = `（已确认，请使用以下我补充的参数重新调用 ${p.tool_name || ""} 完成任务）\n${lines}`;
        }
        if (r.turn_running) {
          state.pendingContinuations[ev.session_id] = { text: cont };
          result.textContent += "，已排队，本轮结束后自动继续";
        } else {
          result.textContent += "，正在继续任务…";
          await sendMessage(cont);
        }
      }
    } catch (err) {
      okBtn.disabled = false;
      result.textContent = err.message || "确认失败";
      result.style.color = "var(--danger)";
    }
  });
  noBtn.addEventListener("click", () => {
    card.classList.add("done");
    card.querySelector("h3").textContent = `已忽略：${p.tool_name || ""}`;
    result.textContent = "已忽略（未铸票，平台零写入）";
  });
  row.appendChild(noBtn);
  row.appendChild(okBtn);
  card.appendChild(row);
  card.appendChild(result);
  push(card);
}

// ── 会话口令确认（无参写入）：不弹模态卡，记唯一 pending，行首 /确认 铸票续跑 ──

function renderChatConfirmPrompt(ev) {
  const p = ev.payload || {};
  const target = p.target || p.tool_name || "";
  // 一次只挂一个 pending：后到的待确认写覆盖先到的（供行首 /确认 复用铸票）。
  state.pendingConfirmations[ev.session_id] = {
    target,
    tool_name: p.tool_name || "",
    reason: p.reason || "",
  };
  const key = `chat_confirm:${ev.session_id}`;
  const prev = state.guardNotices[key];
  if (prev) {
    prev.count += 1;
    prev.line.textContent =
      `检测到 ${prev.count} 次待确认写入：请在下方回复行首 /确认 授权（拒绝则无需回复）`;
    return;
  }
  const line = push(el("div", "sys-line guard-line",
    "写入待确认：请在下方回复行首 /确认 授权（拒绝则无需回复）"));
  state.guardNotices[key] = { line, count: 1 };
}

function queueOrSendContinuation(sid, text, turnRunning) {
  // 带票续跑：本轮仍在跑则登记待办（turn_done 自动补发），否则立即发起新一轮。
  if (state.replaying || !sid || sid !== state.activeId || !text) { return Promise.resolve(); }
  if (turnRunning) {
    state.pendingContinuations[sid] = { text };
    return Promise.resolve();
  }
  return sendMessage(text);
}

function flushPendingContinuation(sid) {
  // turn_done 后补发被本轮阻塞的续跑（若有）。
  if (state.replaying || !sid || sid !== state.activeId) { return; }
  const pc = state.pendingContinuations[sid];
  if (!pc || !pc.text) { return; }
  delete state.pendingContinuations[sid];
  sendMessage(pc.text);
}

async function handleChatConfirm(text) {
  // 仅行首 /确认 且会话有唯一 pending 时转铸票；否则交回普通发送路径。
  if (!isChatConfirmCommand(text)) { return false; }
  const sid = state.activeId;
  const pending = sid ? state.pendingConfirmations[sid] : null;
  if (!pending) {
    // 模型在文本中主动要求 /确认 但尚未实际调用工具（无 gate_blocked），
    // 降级为普通文本发送——让模型收到确认意图后去调用工具，
    // 如果工具需要授权会正常触发 gate_blocked 流程。
    return false;
  }
  try {
    const r = await withLease(() => api(`/api/sessions/${sid}/confirm`, {
      method: "POST",
      body: { target: pending.target, tool_name: pending.tool_name || "" },
      headers: { "x-holder-id": holderId() },
    }));
    delete state.pendingConfirmations[sid];
    const cn = state.guardNotices[`chat_confirm:${sid}`];
    if (cn && cn.line) {
      cn.line.textContent = "✅ 已确认：本任务窗口内同目标写入放行";
    }
    const extra = text.replace(/^\/确认/, "").trim();
    const base = "（已确认，请继续执行之前等待授权的操作）";
    await queueOrSendContinuation(sid, extra ? `${base}${extra}` : base, !!(r && r.turn_running));
    return true;
  } catch (err) { handleErr(err); return true; }
}

function renderWriteGuardNotice(ev) {
  // 同一会话多次越界重试只保留一行，并累加计数（避免连续刷屏）
  const prev = state.guardNotices[ev.session_id];
  if (prev) {
    prev.count += 1;
    prev.line.textContent = `已拦截 ${prev.count} 次写入（路径不在 xlpa-output/），助手会自动改写到产物目录`;
    return;
  }
  const line = push(el("div", "sys-line guard-line",
    "已拦截 1 次写入（路径不在 xlpa-output/），助手会自动改写到产物目录"));
  state.guardNotices[ev.session_id] = { line, count: 1 };
}

function renderForbiddenNotice(ev) {
  // 绝对禁止类拦截（login / 读越界等，confirmable===false）：确认也解除不了，
  // 无需用户决策。降级为一行弱提示、不停转圈；同一会话同一工具只保留一行。
  const p = ev.payload || {};
  const key = `forb:${ev.session_id}:${p.tool_name || ""}`;
  const label = p.tool_name || "操作";
  const prev = state.guardNotices[key];
  if (prev) {
    prev.count += 1;
    prev.line.textContent = `已拦截 ${prev.count} 次 ${label}：${p.reason || "该操作被策略禁止，无需确认"}`;
    return;
  }
  const line = push(el("div", "sys-line guard-line",
    `已拦截 ${label}：${p.reason || "该操作被策略禁止，无需确认"}`));
  state.guardNotices[key] = { line, count: 1 };
}

function renderAskCard(ev) {
  const card = el("div", "card-ask");
  card.appendChild(el("p", "q", `❓ ${ev.payload.message || "Agent 需要您补充信息"}`));
  const input = el("input");
  input.type = "text";
  input.placeholder = "补充说明后回车提交";
  const btn = el("button", "primary-btn", "提交补充");
  btn.type = "button";
  const submit = async () => {
    const text = input.value.trim();
    if (!text) { return; }
    if (await sendMessage(text)) { input.disabled = true; btn.disabled = true; }
  };
  btn.addEventListener("click", submit);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { submit(); } });
  card.appendChild(input);
  card.appendChild(btn);
  push(card);
  if (!state.replaying) { input.focus(); }
}

function renderArtifact(ev) {
  const p = ev.payload;
  const rowEl = el("div", "artifact-row");
  rowEl.appendChild(el("span", "", `📄 ${p.name || p.artifact_id}`));
  rowEl.appendChild(el("span", "size", p.size ? `${fmtSize(p.size)}` : ""));
  const btn = el("button", "ghost-btn", "下载");
  btn.type = "button";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      // 一次性 grant 经请求头取回，URL 无凭据、不进浏览器历史
      const g = await api(`/api/sessions/${ev.session_id}/artifacts/${p.artifact_id}/grant`, { method: "POST" });
      const blob = await fetchBlob(`/api/sessions/${ev.session_id}/artifacts/${p.artifact_id}/download`, { "X-Artifact-Grant": g.grant });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = p.name || p.artifact_id;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (err) { handleErr(err); } finally { btn.disabled = false; }
  });
  rowEl.appendChild(btn);
  push(rowEl);
}

function fmtSize(n) {
  return n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

function finishTurn(ev) {
  setTurnActive(false);
  const t = state.turn;
  const turn = ev.payload.turn;
  const ms = ev.payload.duration_ms;
  cancelAgentRenderTimer();
  flushAgentRender(); // 最终精确渲染：修正流式期间未闭合语法的临时形态
  hideBusy(); // 本轮结束：收起"任务进行中"转圈
  if (t.turnGroup) {
    t.turnGroup.summary.textContent =
      `🔧 本轮共调用 ${t.turnGroup.count} 个工具（点击展开）`;
  }
  if (!t.agentVisible) {
    // 本轮无任何可见文本：回落展示最终结果，不产生空白气泡
    if (t.lastTool) { push(el("div", "sys-line", `本轮无文本输出，结果见工具调用「${t.lastTool}」`)); }
    else { push(el("div", "sys-line", "本轮已结束（无文本输出）")); }
  }
  push(el("div", "sys-line", `── 第 ${Number.isFinite(turn) ? turn : "?"} 轮结束${Number.isFinite(ms) ? ` · ${ms} ms` : ""} ──`));
  if (!state.replaying && t.agentVisible && !t.hadToolCall && /[?？]\s*$/.test(t.agentText)) {
    // 本轮结束型提问：呈现补充输入入口（沿用输入框续跑）
    notify("助手似乎在等待您的回答，可在下方输入补充后发送");
    $("#msg-input").focus();
  }
  state.turn = newTurnState();
  flushPendingContinuation(ev.session_id);
}

// ── 视图杂项 ──

$("#btn-sessions").addEventListener("click", () => {
  $("#sidebar").classList.toggle("open");
});
