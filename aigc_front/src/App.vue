<script setup>
import { onMounted, ref } from "vue";
import {
  createProject,
  downloadUrl,
  fetchNovelMeta,
  fetchPortfolio,
  getProject,
  posterUrl,
} from "./api";

const STAGE_LABELS = {
  pending: "排队中",
  parsing: "AI 分镜",
  imaging: "生成画面",
  audio: "配音合成",
  motion: "镜头动效",
  subtitles: "生成字幕",
  assembling: "成片合成",
  done: "已完成",
  failed: "失败",
};

const novelName = ref("");
const episode = ref(1);
const narrativeMode = ref("protagonist_focus");
const protagonistName = ref("");
const protagonistLocked = ref(false);
const supportingNames = ref("");
const plot = ref("");
const messages = ref([]);
const history = ref([]);
const projectId = ref(null);
const status = ref(null);
const progress = ref(0);
const currentStage = ref("");
const error = ref("");
const generating = ref(false);
const genMode = ref("video");
const videoUrl = ref("");
const activeView = ref("chat");
const portfolioItems = ref([]);
const portfolioLoading = ref(false);
const portfolioError = ref("");
const selectedWork = ref(null);
const alertDialog = ref({
  visible: false,
  title: "",
  message: "",
  items: [],
});

function collectMissingRequired() {
  const missing = [];
  if (!novelName.value.trim()) missing.push("短剧名称");
  if (!(Number(episode.value) >= 1)) missing.push("集数");
  if (!plot.value.trim()) missing.push("剧情正文");
  return missing;
}

function showAlertDialog({ title, message = "", items = [] }) {
  alertDialog.value = { visible: true, title, message, items };
}

function closeAlertDialog() {
  alertDialog.value.visible = false;
}

function promptMissingRequired(missing) {
  showAlertDialog({
    title: "请完善必填信息",
    message: "以下项目尚未填写，补充后再生成：",
    items: missing,
  });
}

/** 单行输入：去首尾空白，连续空格合并为一个 */
function normalizeLineField(value) {
  return value.trim().replace(/[ \u3000]+/g, " ");
}

/** 人名列表：去空白、统一用分号分隔 */
function normalizeNameListField(value) {
  return value
    .trim()
    .split(/[;；,\，、\s]+/)
    .map((s) => s.trim().replace(/[ \u3000]+/g, " "))
    .filter(Boolean)
    .join("；");
}

/** 剧情正文：去行首尾空白、合并连续空行、去掉首尾空行 */
function normalizePlot(value) {
  const lines = value.replace(/\t/g, " ").replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let prevBlank = false;
  for (let line of lines) {
    line = line.trim().replace(/[ \u3000]{2,}/g, " ");
    if (!line) {
      if (!prevBlank && out.length > 0) out.push("");
      prevBlank = true;
      continue;
    }
    prevBlank = false;
    out.push(line);
  }
  while (out.length && out[out.length - 1] === "") out.pop();
  return out.join("\n");
}

function normalizeAllInputs() {
  novelName.value = normalizeLineField(novelName.value);
  if (protagonistName.value.trim()) {
    protagonistName.value = normalizeNameListField(protagonistName.value);
  }
  if (supportingNames.value.trim()) {
    supportingNames.value = normalizeNameListField(supportingNames.value);
  }
  plot.value = normalizePlot(plot.value);
}

function onNovelNameBlur() {
  novelName.value = normalizeLineField(novelName.value);
  loadNovelProtagonist();
}

function onPlotBlur() {
  plot.value = normalizePlot(plot.value);
}

function loadHistory() {
  try {
    history.value = JSON.parse(localStorage.getItem("aigc_history") || "[]");
  } catch {
    history.value = [];
  }
}

function saveHistory(item) {
  const list = [item, ...history.value.filter((h) => h.id !== item.id)].slice(
    0,
    20
  );
  history.value = list;
  localStorage.setItem("aigc_history", JSON.stringify(list));
}

function addMessage(role, content, extra = {}) {
  messages.value.push({ id: Date.now() + Math.random(), role, content, ...extra });
}

function formatUserPrompt() {
  return `《${novelName.value.trim()}》 第 ${episode.value} 集\n\n${plot.value.trim()}`;
}

async function pollUntilDone(id, mode = "video") {
  const maxMs = 30 * 60 * 1000;
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    const data = await getProject(id, mode);
    status.value = data.status;
    progress.value = data.progress;
    currentStage.value = data.current_stage || data.status;
    error.value = data.error || "";

    if (data.status === "done") {
      videoUrl.value = downloadUrl(id, mode) + "&t=" + Date.now();
      return data;
    }
    if (data.status === "failed") {
      throw new Error(data.error || "生成失败");
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error("生成超时，请稍后在历史记录中重试查询");
}

async function loadNovelProtagonist() {
  const name = novelName.value.trim();
  if (!name) {
    protagonistLocked.value = false;
    return;
  }
  try {
    const meta = await fetchNovelMeta(name);
    if (!meta) return;
    if (meta.protagonist_names?.length) {
      protagonistName.value = meta.protagonist_names.join("；");
    } else if (meta.protagonist_name) {
      protagonistName.value = meta.protagonist_name;
    }
    protagonistLocked.value = Boolean(meta.protagonist_locked);
  } catch {
    /* ignore */
  }
}

async function handleGenerate(mode = "video") {
  if (generating.value) {
    showAlertDialog({
      title: "请稍候",
      message: "当前任务正在生成中，完成后再试。",
    });
    return;
  }

  normalizeAllInputs();
  const missing = collectMissingRequired();
  if (missing.length) {
    promptMissingRequired(missing);
    return;
  }

  genMode.value = mode;
  generating.value = true;
  videoUrl.value = "";
  error.value = "";
  status.value = "pending";
  progress.value = 0;

  const prompt = formatUserPrompt();
  addMessage("user", prompt);

  const kindLabel = mode === "anime" ? "动画" : "短视频";
  const stageHint =
    mode === "anime"
      ? "分镜 → 生图 → 多角色配音 → I2V/口型动画 → 合成"
      : "分镜 → 生图 → 配音 → 合成";

  try {
    const created = await createProject({
      novel_name: novelName.value.trim(),
      episode: Number(episode.value),
      text: plot.value.trim(),
      mode,
      narrative_mode: narrativeMode.value,
      protagonist_name: protagonistName.value.trim() || undefined,
      supporting_names: supportingNames.value.trim() || undefined,
    });

    projectId.value = created.project_id;
    addMessage(
      "assistant",
      `正在为你生成《${created.novel_name}》第 ${created.episode} 集${kindLabel}，预计需要数分钟，请稍候…\n\n当前阶段会依次进行：${stageHint}。`,
      { loading: true }
    );

    saveHistory({
      id: created.project_id,
      novel_name: created.novel_name,
      episode: created.episode,
      mode,
      time: new Date().toISOString(),
    });

    await pollUntilDone(created.project_id, mode);

    const last = messages.value[messages.value.length - 1];
    if (last?.loading) last.loading = false;

    addMessage("assistant", `你的${kindLabel}生成好啦。`, {
      video: true,
      downloadName: `${created.novel_name}_第${String(created.episode).padStart(2, "0")}集.mp4`,
    });
    loadPortfolio();
  } catch (e) {
    error.value = e.message || String(e);
    const last = messages.value[messages.value.length - 1];
    if (last?.loading) last.loading = false;
    addMessage("assistant", `生成失败：${error.value}`, { error: true });
  } finally {
    generating.value = false;
  }
}

function loadFromHistory(item) {
  activeView.value = "chat";
  novelName.value = item.novel_name;
  episode.value = item.episode;
  projectId.value = item.id;
}

function newChat() {
  activeView.value = "chat";
  messages.value = [];
  videoUrl.value = "";
  error.value = "";
  status.value = null;
  progress.value = 0;
}

function formatSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

async function loadPortfolio() {
  portfolioLoading.value = true;
  portfolioError.value = "";
  try {
    const data = await fetchPortfolio();
    portfolioItems.value = data.items || [];
  } catch (e) {
    portfolioError.value = e.message || String(e);
    portfolioItems.value = [];
  } finally {
    portfolioLoading.value = false;
  }
}

function openPortfolio() {
  activeView.value = "portfolio";
  selectedWork.value = null;
  loadPortfolio();
}

function openWork(item) {
  selectedWork.value = item;
}

function closeWorkDetail() {
  selectedWork.value = null;
}

function workVideoUrl(projectId, mode = "video") {
  return downloadUrl(projectId, mode) + "&t=" + Date.now();
}

onMounted(() => {
  loadHistory();
  loadPortfolio();
});
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <span class="logo">✦</span>
        <span>短剧 AIGC</span>
      </div>
      <nav class="nav-tabs">
        <button
          type="button"
          :class="['nav-tab', activeView === 'chat' && 'active']"
          @click="newChat"
        >
          生成
        </button>
        <button
          type="button"
          :class="['nav-tab', activeView === 'portfolio' && 'active']"
          @click="openPortfolio"
        >
          作品集
        </button>
      </nav>
      <button class="btn-new" type="button" @click="newChat">开启新任务</button>

      <div class="history-title">生成记录</div>
      <div v-if="!history.length" class="history-empty">暂无记录，生成后会出现在这里</div>
      <ul v-else class="history-list">
        <li
          v-for="h in history"
          :key="h.id"
          class="history-item"
          @click="loadFromHistory(h)"
        >
          <div class="history-name">{{ h.novel_name }}</div>
          <div class="history-meta">第 {{ h.episode }} 集</div>
        </li>
      </ul>

    </aside>

    <main class="main">
      <section v-if="activeView === 'portfolio'" class="portfolio">
        <header class="portfolio-header">
          <h1>作品集</h1>
          <p>已完成的成片会出现在这里，可直接预览与下载</p>
          <button
            type="button"
            class="btn-refresh"
            :disabled="portfolioLoading"
            @click="loadPortfolio"
          >
            {{ portfolioLoading ? "加载中…" : "刷新" }}
          </button>
        </header>

        <p v-if="portfolioError" class="portfolio-error">{{ portfolioError }}</p>
        <p v-else-if="!portfolioLoading && !portfolioItems.length" class="portfolio-empty">
          暂无成片。生成完成后会自动收录。
        </p>

        <div v-else class="portfolio-grid">
          <article
            v-for="item in portfolioItems"
            :key="item.project_id"
            class="work-card"
            @click="openWork(item)"
          >
            <div class="work-cover">
              <img
                v-if="item.has_poster"
                :src="posterUrl(item.project_id, item.mode)"
                :alt="item.novel_name"
                loading="lazy"
              />
              <span v-else class="work-cover-placeholder">🎬</span>
              <span class="work-badge">第 {{ item.episode }} 集</span>
              <span class="work-mode-badge">{{ item.mode === "anime" ? "动画" : "视频" }}</span>
            </div>
            <div class="work-info">
              <h3>{{ item.novel_name }}</h3>
              <p class="work-meta">
                {{ formatTime(item.finished_at) }}
                <span v-if="item.video_size_bytes">
                  · {{ formatSize(item.video_size_bytes) }}
                </span>
              </p>
            </div>
          </article>
        </div>

        <div v-if="selectedWork" class="work-detail">
          <div class="work-detail-backdrop" @click="closeWorkDetail" />
          <div class="work-detail-panel">
            <button type="button" class="work-detail-close" @click="closeWorkDetail">
              ✕
            </button>
            <h2>
              {{ selectedWork.novel_name }} · 第 {{ selectedWork.episode }} 集
              <span class="work-mode-badge">{{ selectedWork.mode === "anime" ? "动画" : "视频" }}</span>
            </h2>
            <video
              :key="selectedWork.project_id"
              :src="workVideoUrl(selectedWork.project_id, selectedWork.mode)"
              controls
              class="work-detail-player"
            />
            <a
              class="btn-download"
              :href="downloadUrl(selectedWork.project_id, selectedWork.mode)"
              :download="`${selectedWork.novel_name}_第${String(selectedWork.episode).padStart(2, '0')}集.mp4`"
            >
              ↓ 下载{{ selectedWork.mode === "anime" ? "动画" : "视频" }}
            </a>
          </div>
        </div>
      </section>

      <template v-else>
      <div v-if="!messages.length" class="hero">
        <div class="hero-icon">🎬</div>
        <h1>小说转短视频</h1>
        <p>填写短剧名称、集数与剧情，一键生成手绘动漫风格竖屏短片</p>
      </div>

      <div class="chat" ref="chatRef">
        <div
          v-for="msg in messages"
          :key="msg.id"
          :class="['msg-row', msg.role]"
        >
          <div v-if="msg.role === 'user'" class="bubble user">
            <pre class="prompt-text">{{ msg.content }}</pre>
          </div>
          <div v-else class="bubble assistant">
            <p class="assistant-text">{{ msg.content }}</p>
            <div v-if="msg.loading && generating" class="progress-box">
              <div class="progress-bar">
                <div class="progress-fill" :style="{ width: progress + '%' }" />
              </div>
              <span class="progress-label">
                {{ STAGE_LABELS[currentStage] || currentStage }} ·
                {{ progress.toFixed(0) }}%
              </span>
            </div>
            <div v-if="msg.video && videoUrl" class="video-card">
              <span class="ai-tag">AI 生成</span>
              <video :src="videoUrl" controls class="player" />
              <a
                class="btn-download"
                :href="videoUrl"
                :download="msg.downloadName"
              >
                ↓ 下载视频
              </a>
            </div>
          </div>
        </div>
      </div>

      <div class="composer">
        <div class="composer-card">
          <div class="field-row">
            <label>
              <span class="label">短剧名称 <em>*</em></span>
              <input
                v-model="novelName"
                type="text"
                placeholder="例如：盘龙"
                maxlength="200"
                @blur="onNovelNameBlur"
              />
            </label>
            <label class="episode-field protagonist-field">
              <span class="label">全书主角</span>
              <input
                v-model="protagonistName"
                type="text"
                placeholder="林雷 或 林雷；德林"
                maxlength="300"
                :disabled="protagonistLocked"
                :title="
                  protagonistLocked
                    ? '该小说主角已锁定'
                    : '多个主角用分号、逗号或空格分隔，首次生成后锁定'
                "
                @blur="protagonistName = normalizeNameListField(protagonistName)"
              />
            </label>
            <label class="episode-field">
              <span class="label">集数 <em>*</em></span>
              <input
                v-model.number="episode"
                type="number"
                min="1"
                max="9999"
                placeholder="1"
              />
            </label>
            <label class="episode-field">
              <span class="label">叙事模式</span>
              <select v-model="narrativeMode" class="mode-select">
                <option value="protagonist_focus">主角视角</option>
                <option value="faithful">忠实原文</option>
              </select>
            </label>
          </div>
          <div class="field-row">
            <label class="supporting-field">
              <span class="label">本集配角</span>
              <input
                v-model="supportingNames"
                type="text"
                placeholder="希尔曼；哈德利（分号、逗号或空格分隔，每集可不同）"
                maxlength="500"
                @blur="supportingNames = normalizeNameListField(supportingNames)"
              />
            </label>
          </div>
          <label class="plot-field">
            <span class="label">剧情正文 <em>*</em></span>
            <textarea
              v-model="plot"
              rows="5"
              placeholder="粘贴本集小说片段或剧情描述…"
              @blur="onPlotBlur"
            />
          </label>
          <div class="composer-actions">
            <span class="hint">
              手绘动漫 · 竖屏 9:16
              <template v-if="protagonistLocked"> · 主角已锁定</template>
            </span>
            <div class="composer-buttons">
              <button
                class="btn-send btn-secondary"
                type="button"
                :disabled="generating"
                @click="handleGenerate('video')"
              >
                {{ generating && genMode === "video" ? "生成中…" : "生成视频" }}
              </button>
              <button
                class="btn-send"
                type="button"
                :disabled="generating"
                @click="handleGenerate('anime')"
              >
                {{ generating && genMode === "anime" ? "生成中…" : "生成动画" }}
              </button>
            </div>
            <p v-if="error && !generating" class="composer-error">{{ error }}</p>
          </div>
        </div>
      </div>
      </template>
    </main>

    <Transition name="alert-fade">
      <div
        v-if="alertDialog.visible"
        class="alert-dialog"
        @keydown.esc="closeAlertDialog"
      >
        <div class="alert-dialog-backdrop" @click="closeAlertDialog" />
        <div class="alert-dialog-panel" role="alertdialog" aria-modal="true">
          <div class="alert-dialog-icon">!</div>
          <h3 class="alert-dialog-title">{{ alertDialog.title }}</h3>
          <p v-if="alertDialog.message" class="alert-dialog-message">
            {{ alertDialog.message }}
          </p>
          <ul v-if="alertDialog.items.length" class="alert-dialog-list">
            <li v-for="item in alertDialog.items" :key="item">{{ item }}</li>
          </ul>
          <button type="button" class="alert-dialog-btn" @click="closeAlertDialog">
            知道了
          </button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  min-height: 100vh;
}

.sidebar {
  width: 260px;
  background: var(--sidebar);
  border-right: 1px solid var(--border);
  padding: 20px 16px;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  font-size: 18px;
  margin-bottom: 20px;
}

.logo {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: linear-gradient(135deg, #8b9bff, #6b7cff);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}

.btn-new {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--card);
  color: var(--text);
  font-weight: 500;
  margin-bottom: 24px;
}

.btn-new:hover {
  border-color: var(--primary);
}

.nav-tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
}

.nav-tab {
  flex: 1;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
}

.nav-tab.active {
  background: rgba(107, 124, 255, 0.12);
  border-color: var(--primary);
  color: var(--primary);
}

.history-title {
  font-size: 13px;
  color: var(--muted);
  margin-bottom: 10px;
}

.history-empty {
  font-size: 13px;
  color: var(--muted);
  line-height: 1.5;
}

.history-list {
  list-style: none;
  padding: 0;
  margin: 0;
  overflow-y: auto;
  flex: 1;
}

.history-item {
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  margin-bottom: 4px;
}

.history-item:hover {
  background: rgba(107, 124, 255, 0.1);
}

.history-name {
  font-weight: 500;
  font-size: 14px;
}

.history-meta {
  font-size: 12px;
  color: var(--muted);
}

.sidebar-foot {
  font-size: 12px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ccc;
}

.dot.ok {
  background: #22c55e;
}

.dot.err {
  background: #ef4444;
}

.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  max-width: 960px;
  margin: 0 auto;
  width: 100%;
  padding: 0 24px 24px;
}

.portfolio {
  padding-top: 24px;
  flex: 1;
}

.portfolio-header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px 16px;
  margin-bottom: 24px;
}

.portfolio-header h1 {
  margin: 0;
  font-size: 26px;
  width: 100%;
}

.portfolio-header p {
  margin: 0;
  color: var(--muted);
  flex: 1;
  min-width: 200px;
}

.btn-refresh {
  padding: 8px 16px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--card);
  font-size: 13px;
}

.portfolio-error {
  color: #ef4444;
}

.portfolio-empty {
  color: var(--muted);
  padding: 48px 0;
  text-align: center;
}

.portfolio-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}

.work-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  cursor: pointer;
  transition: box-shadow 0.2s, transform 0.15s;
}

.work-card:hover {
  box-shadow: var(--shadow);
  transform: translateY(-2px);
}

.work-cover {
  position: relative;
  aspect-ratio: 9 / 16;
  background: #1a1a1a;
  overflow: hidden;
}

.work-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.work-cover-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: 40px;
}

.work-badge {
  position: absolute;
  bottom: 8px;
  right: 8px;
  font-size: 11px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  padding: 3px 8px;
  border-radius: 6px;
}

.work-mode-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  background: linear-gradient(135deg, #7c5cff, #4f8cff);
  color: #fff;
  vertical-align: middle;
}

.work-cover .work-mode-badge {
  position: absolute;
  bottom: 8px;
  left: 8px;
}

.work-info {
  padding: 12px 14px;
}

.work-info h3 {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 600;
}

.work-meta {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}

.work-detail {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.work-detail-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
}

.work-detail-panel {
  position: relative;
  z-index: 1;
  background: var(--card);
  border-radius: 16px;
  padding: 20px;
  max-width: 420px;
  width: 100%;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
}

.work-detail-close {
  position: absolute;
  top: 12px;
  right: 12px;
  border: none;
  background: transparent;
  font-size: 18px;
  cursor: pointer;
  color: var(--muted);
}

.work-detail-panel h2 {
  margin: 0 0 16px;
  font-size: 18px;
  padding-right: 28px;
}

.work-detail-player {
  width: 100%;
  border-radius: 12px;
  background: #111;
  display: block;
}

.work-detail .btn-download {
  margin-top: 12px;
  border-radius: 12px;
}

.hero {
  text-align: center;
  padding: 48px 0 24px;
}

.hero-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

.hero h1 {
  margin: 0 0 8px;
  font-size: 28px;
  font-weight: 600;
}

.hero p {
  margin: 0;
  color: var(--muted);
}

.chat {
  flex: 1;
  overflow-y: auto;
  padding: 16px 0 120px;
  min-height: 200px;
}

.msg-row {
  margin-bottom: 24px;
}

.msg-row.user {
  display: flex;
  justify-content: flex-end;
}

.bubble.user {
  max-width: 85%;
  background: var(--user-bubble);
  border-radius: var(--radius);
  padding: 14px 18px;
}

.prompt-text {
  margin: 0;
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.6;
  font-family: inherit;
}

.bubble.assistant {
  max-width: 100%;
}

.assistant-text {
  margin: 0 0 12px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.progress-box {
  margin-bottom: 16px;
}

.progress-bar {
  height: 6px;
  background: var(--border);
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--primary), #9aa8ff);
  transition: width 0.4s ease;
}

.progress-label {
  font-size: 13px;
  color: var(--muted);
  margin-top: 8px;
  display: inline-block;
}

.video-card {
  position: relative;
  background: #111;
  border-radius: var(--radius);
  overflow: hidden;
  box-shadow: var(--shadow);
  max-width: 480px;
}

.ai-tag {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 2;
  font-size: 12px;
  background: rgba(0, 0, 0, 0.5);
  color: #fff;
  padding: 4px 10px;
  border-radius: 6px;
}

.player {
  width: 100%;
  display: block;
  max-height: 70vh;
}

.btn-download {
  display: block;
  text-align: center;
  padding: 14px;
  background: var(--primary);
  color: #fff;
  text-decoration: none;
  font-weight: 500;
}

.btn-download:hover {
  background: var(--primary-hover);
}

.composer {
  position: sticky;
  bottom: 0;
  padding-bottom: 16px;
  background: linear-gradient(180deg, transparent, var(--bg) 24%);
}

.composer-card {
  background: var(--card);
  border-radius: 20px;
  box-shadow: var(--shadow);
  border: 1px solid var(--border);
  padding: 16px 18px;
}

.field-row {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.field-row label {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.episode-field {
  flex: 0 0 120px !important;
}

.protagonist-field {
  flex: 1 1 180px !important;
  min-width: 140px;
}

.supporting-field {
  flex: 1 1 100%;
}

.label {
  font-size: 13px;
  color: var(--muted);
  font-weight: 500;
}

.label em {
  color: #ef4444;
  font-style: normal;
}

input,
textarea,
select {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 10px 12px;
  font-size: 14px;
  outline: none;
  resize: vertical;
  background: var(--surface, #fff);
}

.mode-select {
  cursor: pointer;
}

input:focus,
textarea:focus,
select:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(107, 124, 255, 0.15);
}

.plot-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}

.composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.hint {
  font-size: 12px;
  color: var(--muted);
}

.hint-warn {
  color: #e0843b;
  font-weight: 600;
}

.btn-send {
  padding: 10px 28px;
  border: none;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  font-weight: 600;
  font-size: 15px;
}

.btn-send:hover:not(:disabled) {
  background: var(--primary-hover);
}

.btn-send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.composer-buttons {
  display: flex;
  gap: 10px;
}

.composer-error {
  margin: 10px 0 0;
  font-size: 13px;
  color: #e0843b;
  text-align: right;
}

.btn-send.btn-secondary {
  background: transparent;
  color: var(--primary);
  border: 1px solid var(--primary);
}

.btn-send.btn-secondary:hover:not(:disabled) {
  background: rgba(124, 92, 255, 0.08);
}

.alert-dialog {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.alert-dialog-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  backdrop-filter: blur(2px);
}

.alert-dialog-panel {
  position: relative;
  z-index: 1;
  width: min(360px, 100%);
  padding: 28px 24px 22px;
  background: var(--card);
  border-radius: 20px;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.18);
  text-align: center;
}

.alert-dialog-icon {
  width: 48px;
  height: 48px;
  margin: 0 auto 14px;
  border-radius: 50%;
  background: linear-gradient(135deg, #fff4e6, #ffe8cc);
  color: #e0843b;
  font-size: 22px;
  font-weight: 700;
  line-height: 48px;
}

.alert-dialog-title {
  margin: 0 0 8px;
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
}

.alert-dialog-message {
  margin: 0 0 12px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--muted);
}

.alert-dialog-list {
  margin: 0 0 20px;
  padding: 12px 16px;
  list-style: none;
  text-align: left;
  background: #f8fafc;
  border-radius: 12px;
  border: 1px solid var(--border);
}

.alert-dialog-list li {
  position: relative;
  padding: 6px 0 6px 18px;
  font-size: 14px;
  color: #334155;
}

.alert-dialog-list li::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--primary);
  transform: translateY(-50%);
}

.alert-dialog-btn {
  min-width: 120px;
  padding: 10px 28px;
  border: none;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}

.alert-dialog-btn:hover {
  background: var(--primary-hover);
}

.alert-fade-enter-active,
.alert-fade-leave-active {
  transition: opacity 0.2s ease;
}

.alert-fade-enter-active .alert-dialog-panel,
.alert-fade-leave-active .alert-dialog-panel {
  transition: transform 0.2s ease, opacity 0.2s ease;
}

.alert-fade-enter-from,
.alert-fade-leave-to {
  opacity: 0;
}

.alert-fade-enter-from .alert-dialog-panel,
.alert-fade-leave-to .alert-dialog-panel {
  transform: scale(0.96) translateY(8px);
  opacity: 0;
}
</style>
