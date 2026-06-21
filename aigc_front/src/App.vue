<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import {
  addProjectCharacter,
  addCharacterVariant,
  characterRefUrl,
  confirmProtagonist,
  costumeRefUrl,
  coverUrl,
  createProject,
  deleteCostumeRef,
  deleteProjectCharacter,
  downloadUrl,
  fetchNovelMeta,
  fetchPortfolio,
  fetchProjectScenes,
  fetchProtagonistDesign,
  fetchStyles,
  generateProjectImages,
  generateProjectVideo,
  getProject,
  posterUrl,
  previewProtagonist,
  protagonistImageUrl,
  regenerateCharacterRef,
  regenerateCharacterVariantRef,
  regenerateSceneImage,
  resetProtagonist,
  saveNovelStyle,
  saveProjectScenes,
  sceneImageUrl,
  syncProjectCharacters,
  updateCharacterVariant,
  updateProjectCharacter,
  uploadCharacterRef,
  uploadCharacterVariantRef,
  uploadCostumeRefs,
} from "./api";

const STYLE_THEMES = {
  default: { gradient: "linear-gradient(135deg,#8b9bff,#6b7cff)", tag: "经典" },
  jp_cel: { gradient: "linear-gradient(135deg,#ff8fab,#ff6b9d)", tag: "日系" },
  cn_semi_realistic: { gradient: "linear-gradient(135deg,#f4a261,#e76f51)", tag: "国漫" },
  kr_manhwa: { gradient: "linear-gradient(135deg,#ffc8dd,#ffafcc)", tag: "韩漫" },
  ink_gongbi: { gradient: "linear-gradient(135deg,#6b705c,#a5a58d)", tag: "国风" },
  manga_bw: { gradient: "linear-gradient(135deg,#495057,#212529)", tag: "黑白" },
  us_comic: { gradient: "linear-gradient(135deg,#ffd60a,#fca311)", tag: "美漫" },
  realistic_anime: { gradient: "linear-gradient(135deg,#90e0ef,#0077b6)", tag: "写实" },
  chibi: { gradient: "linear-gradient(135deg,#bde0fe,#cdb4db)", tag: "Q版" },
  watercolor: { gradient: "linear-gradient(135deg,#d8f3dc,#95d5b2)", tag: "水彩" },
  cyberpunk: { gradient: "linear-gradient(135deg,#7209b7,#4cc9f0)", tag: "赛博" },
  retro_90s: { gradient: "linear-gradient(135deg,#ff9f1c,#ffbf69)", tag: "复古" },
  dark_fantasy: { gradient: "linear-gradient(135deg,#2b2d42,#8d99ae)", tag: "暗黑" },
};

const STAGE_LABELS = {
  pending: "排队中",
  parsing: "AI 分镜",
  storyboard_ready: "分镜待编辑",
  imaging: "生成画面",
  images_ready: "图片待确认",
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
const plot = ref("");
const styles = ref([]);
const selectedStyle = ref("");
const protagonistAppearance = ref("");
const protagonistPersonality = ref("");
const protagonistDesignConfirmed = ref(false);
const protagonistPreviewUrl = ref("");
const protagonistPreviewOpen = ref(false);
const protagonistPreviewVisible = ref(false);
const sceneLightboxOpen = ref(false);
const sceneLightboxSrc = ref("");
const sceneLightboxTitle = ref("");
const styleSectionOpen = ref(true);
const protagonistSectionOpen = ref(true);
const plotSectionOpen = ref(true);
const protagonistDesignLoading = ref(false);
const refFileInput = ref(null);
const refFiles = ref([]);
const costumeRefs = ref([]);
const costumeRefVersion = ref(0);
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
const workflowStep = ref("input");
const sceneScript = ref(null);
const chatRef = ref(null);
const storyboardRef = ref(null);
const scenesSaving = ref(false);
const sceneRegenerating = ref({});
const characterRefLoading = ref({});
const characterUploadLoading = ref({});
const characterRefVersion = ref(0);
const castSectionOpen = ref(true);
const showAddCharacterForm = ref(false);
const newCharacterName = ref("");
const newCharacterAppearance = ref("");
const newCharacterRefFile = ref(null);
const addingVariantFor = ref("");
const newVariantLabel = ref("");
const newVariantAppearance = ref("");
const editingVariant = ref(null);
const variantActionLoading = ref({});
const scenePreviewVisible = ref({});
const storyboardConfirmed = ref(false);
const imageVersion = ref(0);

const needsProtagonistDesign = computed(() => Boolean(protagonistName.value.trim()));

const canGenerate = computed(
  () => !needsProtagonistDesign.value || protagonistDesignConfirmed.value
);

const showStoryboardPanel = computed(
  () => Boolean(sceneScript.value?.scenes?.length)
);

const workflowStepLabel = computed(() => {
  if (workflowStep.value === "images") return "图片阶段，可重绘单镜或补生成缺失图片";
  if (workflowStep.value === "storyboard") {
    return storyboardConfirmed.value ? "分镜已确认，可生成图片" : "请编辑并确认分镜";
  }
  return "";
});

const sceneImageStats = computed(() => {
  const scenes = sceneScript.value?.scenes || [];
  const withImages = scenes.filter((s) => s.image_path).length;
  return { total: scenes.length, withImages, withoutImages: scenes.length - withImages };
});

const generateImagesButtonLabel = computed(() => {
  const { withoutImages, withImages } = sceneImageStats.value;
  if (withoutImages > 0 && withImages > 0) {
    return `生成图片（跳过已有 ${withImages} 镜）`;
  }
  if (withImages > 0 && withoutImages === 0) {
    return "补全/刷新图片";
  }
  return "生成图片";
});

const scriptCharacters = computed(() => sceneScript.value?.characters || []);

function characterRoleLabel(role) {
  if (role === "protagonist") return "主角";
  if (role === "supporting") return "配角";
  return "角色";
}

function characterRefImageUrl(charId, variantId = "default") {
  if (!projectId.value || !charId) return "";
  return characterRefUrl(
    projectId.value,
    charId,
    genMode.value,
    characterRefVersion.value,
    variantId
  );
}

function charById(charId) {
  return sceneScript.value?.characters?.find((c) => c.id === charId) || null;
}

function characterNameById(charId) {
  return charById(charId)?.name || charId;
}

function characterVariantList(char) {
  if (!char) return [];
  if (char.variants && Object.keys(char.variants).length) {
    return Object.values(char.variants);
  }
  return [
    {
      variant_id: char.default_variant_id || "default",
      label: "默认",
      appearance: char.appearance,
      ref_image: char.ref_image,
    },
  ];
}

function variantLabel(variant) {
  return variant?.label || variant?.variant_id || "默认";
}

function variantLoadingKey(charId, variantId, action = "all") {
  return `${charId}:${variantId}:${action}`;
}

function isVariantLoading(charId, variantId, action = "all") {
  return Boolean(variantActionLoading.value[variantLoadingKey(charId, variantId, action)]);
}

function sceneCharacters(scene) {
  if (scene.scene_type === "environment") return [];
  return [
    ...new Set([
      ...(scene.character_ids || []),
      ...(scene.focus_character_ids || []),
    ]),
  ].filter(Boolean);
}

function isDefaultVariant(char, variantId) {
  if (!char) return variantId === "default";
  return (char.default_variant_id || "default") === variantId;
}

function getSceneVariant(scene, charId) {
  const explicit = scene.character_variants?.[charId];
  if (explicit) return explicit;
  const ch = charById(charId);
  return ch?.default_variant_id || "default";
}

function sceneHasVariantOverride(scene, charId) {
  return Boolean(scene.character_variants?.[charId]);
}

function setSceneVariant(scene, charId, variantId) {
  if (!scene.character_variants) scene.character_variants = {};
  const ch = charById(charId);
  const defaultId = ch?.default_variant_id || "default";
  if (variantId === defaultId) {
    const next = { ...scene.character_variants };
    delete next[charId];
    scene.character_variants = Object.keys(next).length ? next : {};
  } else {
    scene.character_variants[charId] = variantId;
  }
  markStoryboardDirty();
}

function availableCharactersForScene(scene) {
  const inScene = new Set(sceneCharacters(scene));
  return scriptCharacters.value.filter((c) => !inScene.has(c.id));
}

function addCharacterToScene(scene, charId) {
  if (!charId || scene.scene_type === "environment") return;
  if (!scene.character_ids) scene.character_ids = [];
  if (!scene.focus_character_ids) scene.focus_character_ids = [];
  if (!scene.character_ids.includes(charId)) {
    scene.character_ids.push(charId);
  }
  if (!scene.focus_character_ids.includes(charId)) {
    scene.focus_character_ids.push(charId);
  }
  if (scene.scene_type !== "character" && scene.scene_type !== "crowd") {
    scene.scene_type = "character";
  }
  markStoryboardDirty();
}

function removeCharacterFromScene(scene, charId) {
  scene.character_ids = (scene.character_ids || []).filter((id) => id !== charId);
  scene.focus_character_ids = (scene.focus_character_ids || []).filter((id) => id !== charId);
  if (scene.character_variants) {
    const next = { ...scene.character_variants };
    delete next[charId];
    scene.character_variants = next;
  }
  if (scene.narration_speaker_id === charId) {
    scene.narration_speaker_id = null;
  }
  if (!scene.character_ids.length && scene.scene_type === "character") {
    scene.scene_type = "crowd";
  }
  markStoryboardDirty();
}

function onAddCharacterToScene(scene, event) {
  const charId = event.target.value;
  event.target.value = "";
  if (charId) addCharacterToScene(scene, charId);
}

function startAddVariant(charId) {
  addingVariantFor.value = charId;
  editingVariant.value = null;
  newVariantLabel.value = "";
  newVariantAppearance.value = "";
}

function selectVariantEdit(char, variant) {
  addingVariantFor.value = "";
  editingVariant.value = {
    charId: char.id,
    variantId: variant.variant_id,
    label: variant.label || "",
    appearance: variant.appearance || "",
  };
}

function cancelVariantEdit() {
  addingVariantFor.value = "";
  editingVariant.value = null;
  newVariantLabel.value = "";
  newVariantAppearance.value = "";
}

function markStoryboardDirty() {
  storyboardConfirmed.value = false;
}

function collapseComposerSections() {
  styleSectionOpen.value = false;
  protagonistSectionOpen.value = false;
  plotSectionOpen.value = false;
}

watch(showStoryboardPanel, (visible) => {
  if (visible) collapseComposerSections();
});

watch(protagonistDesignConfirmed, (confirmed) => {
  if (confirmed) protagonistSectionOpen.value = false;
});

const currentStyleLabel = computed(() => {
  if (!selectedStyle.value) return "默认手绘动漫";
  const s = styles.value.find((x) => x.id === selectedStyle.value);
  return s ? s.label : "默认手绘动漫";
});

const styleOptions = computed(() => {
  const defaultOpt = {
    id: "",
    label: "默认手绘动漫",
    description: "宫崎骏式手绘水彩感，温暖柔和",
    suited_for: "通用叙事、日常、奇幻",
  };
  return [defaultOpt, ...styles.value];
});

function styleTheme(styleId) {
  return STYLE_THEMES[styleId || "default"] || STYLE_THEMES.default;
}

function selectStyle(styleId) {
  selectedStyle.value = styleId;
  const name = novelName.value.trim();
  if (name) {
    saveNovelStyle(name, styleId).catch(() => {});
  }
}

const dramaGroups = computed(() => {
  const groups = new Map();
  for (const item of portfolioItems.value) {
    const key = `${item.mode}::${item.novel_name}`;
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        novel_name: item.novel_name,
        mode: item.mode,
        items: [],
      });
    }
    groups.get(key).items.push(item);
  }
  for (const g of groups.values()) {
    g.items.sort((a, b) => a.episode - b.episode);
  }
  return Array.from(groups.values());
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
  plot.value = normalizePlot(plot.value);
}

function onNovelNameBlur() {
  novelName.value = normalizeLineField(novelName.value);
  loadNovelProtagonist();
  tryLoadExistingStoryboard();
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

async function pollUntilStatus(id, mode = "video", targetStatuses = ["done"]) {
  const maxMs = 30 * 60 * 1000;
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    const data = await getProject(id, mode);
    status.value = data.status;
    progress.value = data.progress;
    currentStage.value = data.current_stage || data.status;
    error.value = data.error || "";

    if (targetStatuses.includes(data.status)) {
      return data;
    }
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

async function pollUntilDone(id, mode = "video") {
  return pollUntilStatus(id, mode, ["done"]);
}

async function loadSceneScript() {
  if (!projectId.value) return;
  const data = await fetchProjectScenes(projectId.value, genMode.value);
  sceneScript.value = {
    ...data,
    scenes: (data.scenes || []).map((s) => ({ ...s })),
  };
  const hasImages = sceneScript.value.scenes.some((s) => s.image_path);
  workflowStep.value = hasImages ? "images" : "storyboard";
  storyboardConfirmed.value = hasImages;
  imageVersion.value += 1;
  characterRefVersion.value += 1;
  await afterSceneScriptLoaded();
}

function scrollToStoryboard() {
  const panel = storyboardRef.value;
  if (!panel) return;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function afterSceneScriptLoaded() {
  collapseComposerSections();
  await nextTick();
  scrollToStoryboard();
}

function buildProjectIdFromForm() {
  const name = novelName.value.trim();
  const ep = Number(episode.value);
  if (!name || !(ep >= 1)) return "";
  return `${name}/第${String(ep).padStart(2, "0")}集`;
}

async function tryLoadExistingStoryboard() {
  const id = buildProjectIdFromForm();
  if (!id) return;
  projectId.value = id;
  const modes = [genMode.value, genMode.value === "video" ? "anime" : "video"];
  for (const mode of modes) {
    try {
      const data = await fetchProjectScenes(id, mode);
      sceneScript.value = {
        ...data,
        scenes: (data.scenes || []).map((s) => ({ ...s })),
      };
      const hasImages = sceneScript.value.scenes.some((s) => s.image_path);
      workflowStep.value = hasImages ? "images" : "storyboard";
      storyboardConfirmed.value = hasImages;
      imageVersion.value += 1;
      genMode.value = mode;
      await afterSceneScriptLoaded();
      return;
    } catch {
      /* try next mode */
    }
  }
  sceneScript.value = null;
  workflowStep.value = "input";
}

function nextSceneId() {
  const scenes = sceneScript.value?.scenes || [];
  let max = 0;
  for (const s of scenes) {
    const m = /^scene_(\d+)$/.exec(s.id);
    if (m) max = Math.max(max, Number(m[1]));
  }
  return `scene_${max + 1 || scenes.length + 1}`;
}

function addScene() {
  if (!sceneScript.value) return;
  const len = sceneScript.value.scenes.length;
  insertSceneAfter(len > 0 ? len - 1 : -1);
}

function insertSceneAfter(index) {
  if (!sceneScript.value) return;
  const id = nextSceneId();
  const at = Math.max(0, index + 1);
  sceneScript.value.scenes.splice(at, 0, {
    id,
    narration: "",
    visual_prompt: "",
    character_ids: [],
    shot_type: "medium",
    scene_type: "character",
    focus_character_ids: [],
  });
  markStoryboardDirty();
}

function isScenePreviewVisible(sceneId) {
  return Boolean(scenePreviewVisible.value[sceneId]);
}

function toggleScenePreview(sceneId) {
  scenePreviewVisible.value = {
    ...scenePreviewVisible.value,
    [sceneId]: !scenePreviewVisible.value[sceneId],
  };
}

function toggleProtagonistPreviewVisible() {
  protagonistPreviewVisible.value = !protagonistPreviewVisible.value;
}

function removeScene(index) {
  if (!sceneScript.value || sceneScript.value.scenes.length <= 1) return;
  sceneScript.value.scenes.splice(index, 1);
  markStoryboardDirty();
}

function moveScene(index, delta) {
  if (!sceneScript.value) return;
  const scenes = sceneScript.value.scenes;
  const next = index + delta;
  if (next < 0 || next >= scenes.length) return;
  const item = scenes.splice(index, 1)[0];
  scenes.splice(next, 0, item);
  markStoryboardDirty();
}

function sceneImageSrc(sceneId) {
  if (!projectId.value) return "";
  return sceneImageUrl(projectId.value, sceneId, genMode.value) + "&v=" + imageVersion.value;
}

async function handleSaveScenes(silent = false) {
  if (!projectId.value || !sceneScript.value?.scenes?.length) return false;
  scenesSaving.value = true;
  error.value = "";
  try {
    const data = await saveProjectScenes(
      projectId.value,
      sceneScript.value.scenes,
      genMode.value
    );
    sceneScript.value = data;
    workflowStep.value = "storyboard";
    storyboardConfirmed.value = true;
    if (!silent) {
      showAlertDialog({
        title: "分镜已确认",
        message: "现在可以点击「生成图片」为各镜绘制画面（已有图片的镜会自动跳过）。",
      });
    }
    return true;
  } catch (e) {
    error.value = e.message || String(e);
    if (!silent) {
      showAlertDialog({ title: "保存失败", message: error.value });
    }
    return false;
  } finally {
    scenesSaving.value = false;
  }
}

async function handleRegenerateScene(scene) {
  if (!projectId.value || sceneRegenerating.value[scene.id]) return;
  sceneRegenerating.value = { ...sceneRegenerating.value, [scene.id]: true };
  error.value = "";
  try {
    const data = await regenerateSceneImage(
      projectId.value,
      scene.id,
      {
        visual_prompt: scene.visual_prompt,
        narration: scene.narration,
        style: selectedStyle.value || null,
      },
      genMode.value
    );
    sceneScript.value = data;
    imageVersion.value += 1;
  } catch (e) {
    error.value = e.message || String(e);
    showAlertDialog({ title: "重新生成失败", message: error.value });
  } finally {
    const next = { ...sceneRegenerating.value };
    delete next[scene.id];
    sceneRegenerating.value = next;
  }
}

async function handleSyncCharacters() {
  if (!projectId.value || generating.value) return;
  generating.value = true;
  error.value = "";
  try {
    const data = await syncProjectCharacters(projectId.value, genMode.value);
    sceneScript.value = {
      ...data,
      scenes: (data.scenes || []).map((s) => ({ ...s })),
    };
    characterRefVersion.value += 1;
    addMessage(
      "assistant",
      `已同步角色库，共 ${scriptCharacters.value.length} 人。请在各分镜中选择出镜角色与造型。`
    );
  } catch (e) {
    error.value = e.message || String(e);
    showAlertDialog({ title: "同步角色失败", message: error.value });
  } finally {
    generating.value = false;
  }
}

async function handleRegenerateCharacterRef(char) {
  if (!projectId.value || characterRefLoading.value[char.id]) return;
  if (!char.appearance?.trim()) {
    showAlertDialog({ title: "请填写外貌描述", message: "请先填写角色外貌提示词，再重绘角色图。" });
    return;
  }
  characterRefLoading.value = { ...characterRefLoading.value, [char.id]: true };
  error.value = "";
  try {
    await updateProjectCharacter(
      projectId.value,
      char.id,
      { name: char.name, appearance: char.appearance },
      genMode.value
    );
    const data = await regenerateCharacterRef(
      projectId.value,
      char.id,
      {
        appearance: char.appearance,
        style: selectedStyle.value || null,
      },
      genMode.value
    );
    sceneScript.value = {
      ...data,
      scenes: (data.scenes || []).map((s) => ({ ...s })),
    };
    characterRefVersion.value += 1;
  } catch (e) {
    error.value = e.message || String(e);
    showAlertDialog({ title: "重绘角色图失败", message: error.value });
  } finally {
    const next = { ...characterRefLoading.value };
    delete next[char.id];
    characterRefLoading.value = next;
  }
}

async function handleSaveCharacter(char) {
  if (!projectId.value) return;
  if (!char.name?.trim() || !char.appearance?.trim()) {
    showAlertDialog({ title: "请填写完整", message: "角色名与外貌描述均不能为空。" });
    return;
  }
  error.value = "";
  try {
    const data = await updateProjectCharacter(
      projectId.value,
      char.id,
      { name: char.name, appearance: char.appearance },
      genMode.value
    );
    sceneScript.value = {
      ...data,
      scenes: (data.scenes || []).map((s) => ({ ...s })),
    };
  } catch (e) {
    error.value = e.message || String(e);
    showAlertDialog({ title: "保存角色失败", message: error.value });
  }
}

async function handleSetDefaultVariant(char, variantId) {
  if (!projectId.value || !char?.id || !variantId) return;
  if (isDefaultVariant(char, variantId)) return;
  generating.value = true;
  error.value = "";
  try {
    const data = await updateProjectCharacter(
      projectId.value,
      char.id,
      { default_variant_id: variantId },
      genMode.value
    );
    sceneScript.value = {
      ...data,
      scenes: (data.scenes || []).map((s) => ({ ...s })),
    };
    characterRefVersion.value += 1;
  } catch (e) {
    error.value = e.message || String(e);
    showAlertDialog({ title: "设置默认造型失败", message: error.value });
  } finally {
    generating.value = false;
  }
}

async function handleUploadCharacterRef(char, event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file || !projectId.value || characterUploadLoading.value[char.id]) return;
  characterUploadLoading.value = { ...characterUploadLoading.value, [char.id]: true };
  error.value = "";
  try {
    if (char.appearance?.trim()) {
      await updateProjectCharacter(
        projectId.value,
        char.id,
        { name: char.name, appearance: char.appearance },
        genMode.value
      );
    }
    const data = await uploadCharacterRef(projectId.value, char.id, file, genMode.value);
    sceneScript.value = {
      ...data,
      scenes: (data.scenes || []).map((s) => ({ ...s })),
    };
    characterRefVersion.value += 1;
  } catch (e) {
    error.value = e.message || String(e);
    showAlertDialog({ title: "上传参考图失败", message: error.value });
  } finally {
    const next = { ...characterUploadLoading.value };
    delete next[char.id];
    characterUploadLoading.value = next;
  }
}

async function refreshEpisodeCastFromRegistry() {
  if (!projectId.value || !sceneScript.value) return;
  try {
    const data = await syncProjectCharacters(projectId.value, genMode.value);
    sceneScript.value = {
      ...data,
      scenes: (data.scenes || []).map((s) => ({ ...s })),
    };
    characterRefVersion.value += 1;
    castSectionOpen.value = true;
  } catch {
    /* storyboard may not exist yet */
  }
}

function openCharacterVariantEditor(char) {
  if (!char) return;
  const variant = characterVariantList(char)[0];
  if (variant) selectVariantEdit(char, variant);
  castSectionOpen.value = true;
}

async function handleAddCharacter(drawAfterAdd = false) {
  if (!projectId.value || generating.value) return;
  const name = newCharacterName.value.trim();
  const appearance = newCharacterAppearance.value.trim();
  if (!name || !appearance) {
    showAlertDialog({ title: "请填写完整", message: "请填写角色名与外貌描述。" });
    return;
  }
  generating.value = true;
  error.value = "";
  try {
    let data = await addProjectCharacter(
      projectId.value,
      { name, appearance },
      genMode.value
    );
    let added = (data.characters || []).find((c) => c.name === name);
    if (added && newCharacterRefFile.value) {
      data = await uploadCharacterRef(
        projectId.value,
        added.id,
        newCharacterRefFile.value,
        genMode.value
      );
      added = (data.characters || []).find((c) => c.id === added.id) || added;
    }
    if (added && drawAfterAdd) {
      data = await regenerateCharacterVariantRef(
        projectId.value,
        added.id,
        added.default_variant_id || "default",
        { appearance, style: selectedStyle.value || null },
        genMode.value
      );
      added = (data.characters || []).find((c) => c.id === added.id) || added;
    }
    sceneScript.value = {
      ...data,
      scenes: (data.scenes || []).map((s) => ({ ...s })),
    };
    characterRefVersion.value += 1;
    newCharacterName.value = "";
    newCharacterAppearance.value = "";
    newCharacterRefFile.value = null;
    showAddCharacterForm.value = false;
    if (added) openCharacterVariantEditor(added);
  } catch (e) {
    error.value = e.message || String(e);
    showAlertDialog({ title: "添加角色失败", message: error.value });
  } finally {
    generating.value = false;
  }
}

async function handleDeleteCharacter(char) {
  if (!projectId.value || !char?.id) return;
  const label = char.role === "protagonist" ? "主角" : "角色";
  if (!window.confirm(`确定删除${label}「${char.name}」？将从角色库及分镜绑定中移除。`)) return;
  generating.value = true;
  error.value = "";
  try {
    if (editingVariant.value?.charId === char.id) cancelVariantEdit();
    const data = await deleteProjectCharacter(projectId.value, char.id, genMode.value);
    sceneScript.value = {
      ...data,
      scenes: (data.scenes || []).map((s) => ({ ...s })),
    };
    characterRefVersion.value += 1;
  } catch (e) {
    error.value = e.message || String(e);
    showAlertDialog({ title: "删除失败", message: error.value });
  } finally {
    generating.value = false;
  }
}

function onNewCharacterRefChange(event) {
  newCharacterRefFile.value = event.target.files?.[0] || null;
}

async function handleAddVariant(charId) {
  if (!projectId.value || !charId) return;
  const label = newVariantLabel.value.trim();
  const appearance = newVariantAppearance.value.trim();
  if (!label || !appearance) {
    showAlertDialog({ title: "请填写完整", message: "请填写时期名称与外貌描述。" });
    return;
  }
  const key = variantLoadingKey(charId, "new", "add");
  variantActionLoading.value = { ...variantActionLoading.value, [key]: true };
  try {
    const data = await addCharacterVariant(
      projectId.value,
      charId,
      { label, appearance },
      genMode.value
    );
    sceneScript.value = {
      ...data,
      scenes: (data.scenes || []).map((s) => ({ ...s })),
    };
    const ch = charById(charId);
    const added = characterVariantList(ch).find((v) => v.label === label);
    if (added) selectVariantEdit(ch, added);
    addingVariantFor.value = "";
    newVariantLabel.value = "";
    newVariantAppearance.value = "";
  } catch (e) {
    showAlertDialog({ title: "添加造型失败", message: e.message || String(e) });
  } finally {
    const next = { ...variantActionLoading.value };
    delete next[key];
    variantActionLoading.value = next;
  }
}

async function handleSaveVariant() {
  if (!projectId.value || !editingVariant.value) return;
  const { charId, variantId, label, appearance } = editingVariant.value;
  if (!label?.trim() || !appearance?.trim()) {
    showAlertDialog({ title: "请填写完整", message: "时期名称与外貌描述均不能为空。" });
    return;
  }
  const key = variantLoadingKey(charId, variantId, "save");
  variantActionLoading.value = { ...variantActionLoading.value, [key]: true };
  try {
    const data = await updateCharacterVariant(
      projectId.value,
      charId,
      variantId,
      { label: label.trim(), appearance: appearance.trim() },
      genMode.value
    );
    sceneScript.value = {
      ...data,
      scenes: (data.scenes || []).map((s) => ({ ...s })),
    };
  } catch (e) {
    showAlertDialog({ title: "保存造型失败", message: e.message || String(e) });
  } finally {
    const next = { ...variantActionLoading.value };
    delete next[key];
    variantActionLoading.value = next;
  }
}

async function handleUploadVariantRef(charId, variantId, event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file || !projectId.value) return;
  const key = variantLoadingKey(charId, variantId, "upload");
  variantActionLoading.value = { ...variantActionLoading.value, [key]: true };
  try {
    if (editingVariant.value?.charId === charId && editingVariant.value?.variantId === variantId) {
      await updateCharacterVariant(
        projectId.value,
        charId,
        variantId,
        {
          label: editingVariant.value.label,
          appearance: editingVariant.value.appearance,
        },
        genMode.value
      );
    }
    const data = await uploadCharacterVariantRef(
      projectId.value,
      charId,
      variantId,
      file,
      genMode.value
    );
    sceneScript.value = {
      ...data,
      scenes: (data.scenes || []).map((s) => ({ ...s })),
    };
    characterRefVersion.value += 1;
  } catch (e) {
    showAlertDialog({ title: "上传参考图失败", message: e.message || String(e) });
  } finally {
    const next = { ...variantActionLoading.value };
    delete next[key];
    variantActionLoading.value = next;
  }
}

async function handleAiGenerateVariant(charId, variantId, appearance) {
  if (!projectId.value || !appearance?.trim()) {
    showAlertDialog({ title: "请填写外貌描述", message: "请先填写该时期的外貌提示词。" });
    return;
  }
  const key = variantLoadingKey(charId, variantId, "ai");
  variantActionLoading.value = { ...variantActionLoading.value, [key]: true };
  try {
    const data = await regenerateCharacterVariantRef(
      projectId.value,
      charId,
      variantId,
      {
        appearance: appearance.trim(),
        style: selectedStyle.value || null,
      },
      genMode.value
    );
    sceneScript.value = {
      ...data,
      scenes: (data.scenes || []).map((s) => ({ ...s })),
    };
    characterRefVersion.value += 1;
  } catch (e) {
    showAlertDialog({ title: "AI 生成失败", message: e.message || String(e) });
  } finally {
    const next = { ...variantActionLoading.value };
    delete next[key];
    variantActionLoading.value = next;
  }
}

function validateBeforeGenerate() {
  normalizeAllInputs();
  const missing = collectMissingRequired();
  if (missing.length) {
    promptMissingRequired(missing);
    return false;
  }
  if (needsProtagonistDesign.value && !protagonistDesignConfirmed.value) {
    showAlertDialog({
      title: "请先确认主角",
      message: "填写了主角姓名时，需先生成主角预览并确认外貌与性格，再生成视频/动画。",
    });
    return false;
  }
  return true;
}

async function handleGenerateStoryboard(mode = "video", { withImages = false } = {}) {
  if (generating.value) {
    showAlertDialog({
      title: "请稍候",
      message: "当前任务正在生成中，完成后再试。",
    });
    return;
  }
  if (!validateBeforeGenerate()) return;

  const regen = showStoryboardPanel.value;
  genMode.value = mode;
  generating.value = true;
  videoUrl.value = "";
  error.value = "";
  status.value = "pending";
  progress.value = 0;
  sceneScript.value = null;
  workflowStep.value = "input";
  storyboardConfirmed.value = false;
  scenePreviewVisible.value = {};

  const prompt = formatUserPrompt();
  addMessage("user", prompt);

  if (regen) {
    addMessage(
      "assistant",
      withImages
        ? `正在重新生成《${novelName.value.trim()}》第 ${episode.value} 集分镜并绘制画面…`
        : `正在重新生成《${novelName.value.trim()}》第 ${episode.value} 集分镜剧本…`,
      { loading: true }
    );
  }

  try {
    const created = await createProject({
      novel_name: novelName.value.trim(),
      episode: Number(episode.value),
      text: plot.value.trim(),
      mode,
      narrative_mode: narrativeMode.value,
      protagonist_name: protagonistName.value.trim() || undefined,
      style: selectedStyle.value || undefined,
      stop_after: withImages ? "generate_images" : "parse_scenes",
      regenerate_storyboard: true,
    });

    projectId.value = created.project_id;
    if (!regen) {
      addMessage(
        "assistant",
        withImages
          ? `正在为《${created.novel_name}》第 ${created.episode} 集生成分镜并绘制画面，请稍候…`
          : `正在为《${created.novel_name}》第 ${created.episode} 集生成 AI 分镜，请稍候…`,
        { loading: true }
      );
    }

    saveHistory({
      id: created.project_id,
      novel_name: created.novel_name,
      episode: created.episode,
      mode,
      time: new Date().toISOString(),
    });

    const targetStatuses = withImages
      ? ["images_ready", "done"]
      : ["storyboard_ready", "done"];
    if (
      !targetStatuses.includes(created.status)
    ) {
      await pollUntilStatus(created.project_id, mode, targetStatuses);
    }

    await loadSceneScript();
    if (withImages) {
      storyboardConfirmed.value = true;
    }

    const last = messages.value[messages.value.length - 1];
    if (last?.loading) last.loading = false;

    addMessage(
      "assistant",
      withImages
        ? `分镜与图片已生成，共 ${sceneScript.value.scenes.length} 镜。可在下方查看并修改，不满意可重绘单镜。`
        : regen
          ? `分镜剧本已重新生成，共 ${sceneScript.value.scenes.length} 镜。请编辑后确认，再生成图片。`
          : `分镜已生成，共 ${sceneScript.value.scenes.length} 镜。可直接「生成图片」，或先编辑确认后再生成。`
    );
  } catch (e) {
    error.value = e.message || String(e);
    const last = messages.value[messages.value.length - 1];
    if (last?.loading) last.loading = false;
    addMessage("assistant", `分镜生成失败：${error.value}`, { error: true });
  } finally {
    generating.value = false;
  }
}

async function handleGenerateImages() {
  if (generating.value || !projectId.value) return;
  if (!sceneScript.value?.scenes?.length) return;

  generating.value = true;
  error.value = "";
  try {
    const saved = await handleSaveScenes(true);
    if (!saved) return;

    const { withImages, withoutImages } = sceneImageStats.value;
    await generateProjectImages(projectId.value, genMode.value);
    addMessage(
      "assistant",
      withoutImages > 0 && withImages > 0
        ? `正在生成 ${withoutImages} 镜缺失图片（${withImages} 镜已有图片将跳过）…`
        : withImages > 0
          ? "正在检查并补全分镜图片（已有图片将跳过）…"
          : "正在根据分镜生成画面，请稍候…",
      { loading: true }
    );

    await pollUntilStatus(projectId.value, genMode.value, [
      "images_ready",
      "done",
    ]);
    await loadSceneScript();

    const last = messages.value[messages.value.length - 1];
    if (last?.loading) last.loading = false;

    addMessage(
      "assistant",
      "分镜图片已就绪。若不满意可修改画面描述并「重绘此镜」，确认无误后点击「生成视频」。"
    );
  } catch (e) {
    error.value = e.message || String(e);
    const last = messages.value[messages.value.length - 1];
    if (last?.loading) last.loading = false;
    showAlertDialog({ title: "生成图片失败", message: error.value });
  } finally {
    generating.value = false;
  }
}

async function handleGenerateVideo() {
  if (generating.value || !projectId.value) return;

  generating.value = true;
  videoUrl.value = "";
  error.value = "";
  const kindLabel = genMode.value === "anime" ? "动画" : "短视频";

  try {
    await generateProjectVideo(projectId.value, genMode.value);
    addMessage("assistant", `正在合成${kindLabel}，请稍候…`, { loading: true });

    await pollUntilDone(projectId.value, genMode.value);
    workflowStep.value = "done";

    const last = messages.value[messages.value.length - 1];
    if (last?.loading) last.loading = false;

    addMessage("assistant", `你的${kindLabel}生成好啦。`, {
      video: true,
      downloadName: `${novelName.value.trim()}_第${String(episode.value).padStart(2, "0")}集.mp4`,
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

async function handleGenerate(mode = "video") {
  await handleGenerateStoryboard(mode);
}

async function loadProtagonistDesign() {
  const name = novelName.value.trim();
  if (!name) {
    protagonistDesignConfirmed.value = false;
    protagonistPreviewUrl.value = "";
    return;
  }
  try {
    const data = await fetchProtagonistDesign(name);
    if (!data) return;
    if (data.protagonist_appearance) {
      protagonistAppearance.value = data.protagonist_appearance;
    }
    if (data.protagonist_personality) {
      protagonistPersonality.value = data.protagonist_personality;
    }
    if (data.protagonist_style && !selectedStyle.value) {
      selectedStyle.value = data.protagonist_style;
    }
    protagonistDesignConfirmed.value = Boolean(data.protagonist_design_confirmed);
    protagonistPreviewUrl.value = data.protagonist_preview_url
      ? protagonistImageUrl(name)
      : "";
    applyCostumeRefsFromMeta(data);
  } catch {
    /* ignore */
  }
}

async function loadNovelProtagonist() {
  const name = novelName.value.trim();
  if (!name) {
    protagonistLocked.value = false;
    protagonistDesignConfirmed.value = false;
    protagonistPreviewUrl.value = "";
    selectedStyle.value = "";
    costumeRefs.value = [];
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
    if (meta.protagonist_appearance) {
      protagonistAppearance.value = meta.protagonist_appearance;
    }
    if (meta.protagonist_personality) {
      protagonistPersonality.value = meta.protagonist_personality;
    }
    protagonistDesignConfirmed.value = Boolean(meta.protagonist_design_confirmed);
    protagonistPreviewUrl.value = meta.protagonist_preview_url
      ? protagonistImageUrl(name)
      : "";
    if (meta.protagonist_style !== undefined && meta.protagonist_style !== null) {
      selectedStyle.value = meta.protagonist_style || "";
    }
    applyCostumeRefsFromMeta(meta);
  } catch {
    /* ignore */
  }
}

function onRefFileChange(event) {
  const files = Array.from(event.target.files || []);
  refFiles.value = files;
}

function clearRefFiles() {
  refFiles.value = [];
  if (refFileInput.value) refFileInput.value.value = "";
}

function applyCostumeRefsFromMeta(meta) {
  const list = meta?.protagonist_costume_refs || [];
  costumeRefs.value = list.map((item) => ({
    id: item.id,
    url: costumeRefUrl(novelName.value.trim(), item.id) + "&v=" + costumeRefVersion.value,
  }));
}

function costumeRefSrc(refId) {
  return costumeRefUrl(novelName.value.trim(), refId) + "&v=" + costumeRefVersion.value;
}

async function handleUploadCostumeRefs() {
  normalizeAllInputs();
  if (!novelName.value.trim() || !protagonistName.value.trim()) {
    showAlertDialog({ title: "请先填写", message: "需要短剧名称与主角姓名后再上传服饰参考图。" });
    return;
  }
  if (!refFiles.value.length) {
    showAlertDialog({ title: "请选择图片", message: "请至少选择一张服饰参考图。" });
    return;
  }
  protagonistDesignLoading.value = true;
  try {
    const data = await uploadCostumeRefs({
      novel_name: novelName.value.trim(),
      protagonist_name: protagonistName.value.trim(),
      reference_files: refFiles.value,
    });
    applyCostumeRefsFromMeta(data);
    costumeRefVersion.value += 1;
    clearRefFiles();
  } catch (e) {
    showAlertDialog({ title: "上传失败", message: e.message || String(e) });
  } finally {
    protagonistDesignLoading.value = false;
  }
}

async function handleDeleteCostumeRef(refId) {
  if (!novelName.value.trim() || protagonistDesignLoading.value) return;
  protagonistDesignLoading.value = true;
  try {
    const data = await deleteCostumeRef(novelName.value.trim(), refId);
    applyCostumeRefsFromMeta(data);
    costumeRefVersion.value += 1;
  } catch (e) {
    showAlertDialog({ title: "删除失败", message: e.message || String(e) });
  } finally {
    protagonistDesignLoading.value = false;
  }
}

function openProtagonistPreview() {
  if (protagonistPreviewUrl.value) protagonistPreviewOpen.value = true;
}

function closeProtagonistPreview() {
  protagonistPreviewOpen.value = false;
}

function openSceneLightbox(sceneId, index) {
  if (!projectId.value) return;
  sceneLightboxSrc.value = sceneImageSrc(sceneId);
  sceneLightboxTitle.value = `第 ${index + 1} 镜`;
  sceneLightboxOpen.value = true;
}

function closeSceneLightbox() {
  sceneLightboxOpen.value = false;
}

async function handlePreviewProtagonist() {
  normalizeAllInputs();
  const missing = [];
  if (!novelName.value.trim()) missing.push("短剧名称");
  if (!protagonistName.value.trim()) missing.push("全书主角");
  if (!protagonistAppearance.value.trim()) missing.push("主角外貌提示词");
  if (missing.length) {
    promptMissingRequired(missing);
    return;
  }
  protagonistDesignLoading.value = true;
  error.value = "";
  try {
    const data = await previewProtagonist({
      novel_name: novelName.value.trim(),
      protagonist_name: protagonistName.value.trim(),
      appearance_prompt: protagonistAppearance.value.trim(),
      personality: protagonistPersonality.value.trim(),
      style: selectedStyle.value,
      reference_files: refFiles.value.length ? refFiles.value : undefined,
    });
    protagonistDesignConfirmed.value = Boolean(data.protagonist_design_confirmed);
    protagonistPreviewUrl.value = data.protagonist_preview_url
      ? protagonistImageUrl(novelName.value.trim())
      : "";
    applyCostumeRefsFromMeta(data);
    clearRefFiles();
    protagonistLocked.value = true;
    showAlertDialog({
      title: "主角预览已生成",
      message: "请查看预览图，满意后点击「确认主角」；不满意可修改提示词后重新生成。",
    });
  } catch (e) {
    error.value = e.message || String(e);
    showAlertDialog({ title: "生成失败", message: error.value });
  } finally {
    protagonistDesignLoading.value = false;
  }
}

async function handleConfirmProtagonist() {
  normalizeAllInputs();
  if (!novelName.value.trim() || !protagonistName.value.trim()) {
    promptMissingRequired(["短剧名称", "全书主角"]);
    return;
  }
  if (!protagonistPreviewUrl.value && !protagonistAppearance.value.trim()) {
    showAlertDialog({
      title: "请先预览",
      message: "请先生成主角预览图，确认外貌后再锁定主角设定。",
    });
    return;
  }
  protagonistDesignLoading.value = true;
  error.value = "";
  try {
    const data = await confirmProtagonist({
      novel_name: novelName.value.trim(),
      appearance: protagonistAppearance.value.trim(),
      personality: protagonistPersonality.value.trim(),
    });
    protagonistDesignConfirmed.value = Boolean(data.protagonist_design_confirmed);
    protagonistLocked.value = Boolean(data.protagonist_locked ?? true);
    protagonistPreviewUrl.value = data.protagonist_preview_url
      ? protagonistImageUrl(novelName.value.trim())
      : protagonistPreviewUrl.value;
    await refreshEpisodeCastFromRegistry();
    showAlertDialog({
      title: "主角已确认",
      message: projectId.value
        ? "主角外貌已锁定，下方「本集出镜角色」已同步最新造型。"
        : "主角外貌与性格已锁定，现在可以生成视频或动画。",
    });
  } catch (e) {
    error.value = e.message || String(e);
    showAlertDialog({ title: "确认失败", message: error.value });
  } finally {
    protagonistDesignLoading.value = false;
  }
}

async function handleResetProtagonist() {
  if (!novelName.value.trim()) {
    promptMissingRequired(["短剧名称"]);
    return;
  }
  if (generating.value || protagonistDesignLoading.value) return;
  protagonistDesignLoading.value = true;
  error.value = "";
  try {
    const data = await resetProtagonist(novelName.value.trim());
    protagonistLocked.value = false;
    protagonistDesignConfirmed.value = false;
    protagonistPreviewUrl.value = "";
    protagonistAppearance.value = "";
    protagonistPersonality.value = "";
    clearRefFiles();
    costumeRefs.value = [];
    if (data.protagonist_names?.length) {
      protagonistName.value = data.protagonist_names.join("；");
    }
    showAlertDialog({
      title: "主角已重置",
      message: "可修改主角姓名、外貌与性格，重新生成预览并确认后再制作视频。",
    });
  } catch (e) {
    error.value = e.message || String(e);
    showAlertDialog({ title: "重置失败", message: error.value });
  } finally {
    protagonistDesignLoading.value = false;
  }
}

function stepEpisode(delta) {
  const next = Math.min(9999, Math.max(1, Number(episode.value || 1) + delta));
  episode.value = next;
  tryLoadExistingStoryboard();
}

function resetEpisodeNumber() {
  episode.value = 1;
  tryLoadExistingStoryboard();
}

function resetEpisodeContent() {
  plot.value = "";
  messages.value = [];
  videoUrl.value = "";
  error.value = "";
  status.value = null;
  progress.value = 0;
  projectId.value = null;
  sceneScript.value = null;
  workflowStep.value = "input";
  storyboardConfirmed.value = false;
  sceneRegenerating.value = {};
}

function loadFromHistory(item) {
  activeView.value = "chat";
  novelName.value = item.novel_name;
  episode.value = item.episode;
  projectId.value = item.id;
  genMode.value = item.mode || "video";
  loadNovelProtagonist();
  tryLoadExistingStoryboard();
}

function newChat() {
  activeView.value = "chat";
  messages.value = [];
  videoUrl.value = "";
  error.value = "";
  status.value = null;
  progress.value = 0;
  protagonistDesignConfirmed.value = false;
  protagonistPreviewUrl.value = "";
  protagonistAppearance.value = "";
  protagonistPersonality.value = "";
  sceneScript.value = null;
  workflowStep.value = "input";
  projectId.value = null;
  clearRefFiles();
  costumeRefs.value = [];
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

async function loadStyles() {
  try {
    styles.value = await fetchStyles();
  } catch {
    styles.value = [];
  }
}

function onCoverError(event) {
  event.target.style.display = "none";
}

onMounted(() => {
  loadHistory();
  loadPortfolio();
  loadStyles();
  if (novelName.value.trim() && Number(episode.value) >= 1) {
    tryLoadExistingStoryboard();
  }
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

        <div v-else class="drama-groups">
          <section
            v-for="group in dramaGroups"
            :key="group.key"
            class="drama-group"
          >
            <header class="drama-head">
              <div class="drama-cover">
                <span class="drama-cover-fallback">🎬</span>
                <img
                  :src="coverUrl(group.novel_name, group.mode)"
                  :alt="group.novel_name"
                  loading="lazy"
                  @error="onCoverError"
                />
              </div>
              <div class="drama-head-info">
                <h2>{{ group.novel_name }}</h2>
                <p>
                  {{ group.mode === "anime" ? "动画" : "视频" }} · 共
                  {{ group.items.length }} 集
                </p>
              </div>
            </header>
            <div class="portfolio-grid">
              <article
                v-for="item in group.items"
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
                  <span class="work-mode-badge">{{
                    item.mode === "anime" ? "动画" : "视频"
                  }}</span>
                </div>
                <div class="work-info">
                  <h3>第 {{ item.episode }} 集</h3>
                  <p class="work-meta">
                    {{ formatTime(item.finished_at) }}
                    <span v-if="item.video_size_bytes">
                      · {{ formatSize(item.video_size_bytes) }}
                    </span>
                  </p>
                </div>
              </article>
            </div>
          </section>
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
        <p>填写短剧名称、集数与剧情，一键生成动漫/视频风格短片</p>
      </div>

      <div ref="chatRef" class="chat">
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
                :disabled="protagonistLocked && protagonistDesignConfirmed"
                :title="
                  protagonistLocked && protagonistDesignConfirmed
                    ? '主角已确认，点「重置主角」后可修改'
                    : '多个主角用分号、逗号或空格分隔'
                "
                @blur="protagonistName = normalizeNameListField(protagonistName)"
              />
            </label>
            <label class="episode-field episode-stepper-field">
              <span class="label">集数 <em>*</em></span>
              <div class="episode-stepper">
                <button
                  type="button"
                  class="stepper-btn"
                  :disabled="Number(episode) <= 1 || generating"
                  @click="stepEpisode(-1)"
                >
                  −
                </button>
                <input
                  v-model.number="episode"
                  type="number"
                  min="1"
                  max="9999"
                  placeholder="1"
                  @change="tryLoadExistingStoryboard"
                />
                <button
                  type="button"
                  class="stepper-btn"
                  :disabled="Number(episode) >= 9999 || generating"
                  @click="stepEpisode(1)"
                >
                  +
                </button>
              </div>
              <div class="episode-reset-row">
                <button
                  type="button"
                  class="btn-mini"
                  :disabled="generating"
                  @click="resetEpisodeNumber"
                >
                  重置为第1集
                </button>
                <button
                  type="button"
                  class="btn-mini"
                  :disabled="generating"
                  @click="resetEpisodeContent"
                >
                  清空本集内容
                </button>
              </div>
            </label>
            <label class="episode-field">
              <span class="label">叙事模式</span>
              <select v-model="narrativeMode" class="mode-select">
                <option value="protagonist_focus">主角视角</option>
                <option value="faithful">忠实原文</option>
              </select>
            </label>
          </div>
          <div class="style-section collapsible-section">
            <div class="collapsible-head">
              <div class="collapsible-head-text">
                <span class="label">画风风格</span>
                <span class="style-current">{{ currentStyleLabel }}</span>
              </div>
              <button
                type="button"
                class="btn-mini collapsible-toggle"
                @click="styleSectionOpen = !styleSectionOpen"
              >
                {{ styleSectionOpen ? "收起" : "展开" }}
              </button>
            </div>
            <div v-show="styleSectionOpen" class="style-grid">
              <button
                v-for="s in styleOptions"
                :key="s.id || 'default'"
                type="button"
                :class="['style-card', selectedStyle === s.id && 'active']"
                @click="selectStyle(s.id)"
              >
                <span
                  class="style-card-accent"
                  :style="{ background: styleTheme(s.id).gradient }"
                />
                <span class="style-card-tag">{{ styleTheme(s.id).tag }}</span>
                <span class="style-card-title">{{ s.label }}</span>
                <span class="style-card-desc">{{
                  s.description || s.suited_for
                }}</span>
                <span v-if="s.suited_for" class="style-card-for">{{
                  s.suited_for
                }}</span>
              </button>
            </div>
          </div>

          <section v-if="needsProtagonistDesign" class="protagonist-design collapsible-section">
            <div class="protagonist-design-head collapsible-head">
              <div class="collapsible-head-text">
                <span class="label">主角设定 <em>*</em></span>
                <span
                  :class="[
                    'design-badge',
                    protagonistDesignConfirmed ? 'confirmed' : 'pending',
                  ]"
                >
                  {{ protagonistDesignConfirmed ? "已确认" : "待确认" }}
                </span>
              </div>
              <button
                type="button"
                class="btn-mini collapsible-toggle"
                @click="protagonistSectionOpen = !protagonistSectionOpen"
              >
                {{ protagonistSectionOpen ? "收起" : "展开" }}
              </button>
            </div>
            <div v-show="protagonistSectionOpen">
            <p class="design-hint">
              先根据提示词或服饰参考图生成主角形象，确认性格后再制作；可上传多张服饰参考图（最多 4 张）。
            </p>
            <div class="field-row">
              <label class="supporting-field">
                <span class="label">主角外貌提示词</span>
                <textarea
                  v-model="protagonistAppearance"
                  rows="2"
                  placeholder="例如：银发红瞳的吸血鬼少年，黑色长风衣，冷峻气质…"
                  :disabled="protagonistDesignLoading"
                />
              </label>
            </div>
            <div class="field-row">
              <label class="supporting-field">
                <span class="label">主角性格</span>
                <textarea
                  v-model="protagonistPersonality"
                  rows="2"
                  placeholder="例如：外冷内热，寡言但重情义，对敌人冷酷…"
                  :disabled="protagonistDesignLoading"
                />
              </label>
            </div>
            <div class="costume-refs-block">
              <div class="field-row ref-upload-row">
                <label class="ref-upload">
                  <span class="label">服饰参考图（可选，可多选，最多 4 张）</span>
                  <input
                    ref="refFileInput"
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    multiple
                    :disabled="protagonistDesignLoading"
                    @change="onRefFileChange"
                  />
                </label>
                <span v-if="refFiles.length" class="ref-file-name">
                  已选 {{ refFiles.length }} 张
                </span>
                <button
                  v-if="refFiles.length"
                  type="button"
                  class="btn-mini"
                  :disabled="protagonistDesignLoading"
                  @click="handleUploadCostumeRefs"
                >
                  上传服饰参考
                </button>
                <button
                  v-if="refFiles.length"
                  type="button"
                  class="btn-link"
                  :disabled="protagonistDesignLoading"
                  @click="clearRefFiles"
                >
                  清除选择
                </button>
              </div>
              <p class="costume-refs-hint">
                可上传脸部、全身、礼服等多张参考；生成分镜图时会一并传入模型以保持服饰一致。
              </p>
              <div v-if="costumeRefs.length" class="costume-refs-grid">
                <div
                  v-for="ref in costumeRefs"
                  :key="ref.id"
                  class="costume-ref-item"
                >
                  <img :src="costumeRefSrc(ref.id)" :alt="ref.id" loading="lazy" />
                  <button
                    type="button"
                    class="costume-ref-delete"
                    :disabled="protagonistDesignLoading"
                    @click="handleDeleteCostumeRef(ref.id)"
                  >
                    删除
                  </button>
                </div>
              </div>
            </div>
            <div v-if="protagonistPreviewUrl" class="protagonist-preview-block">
              <button
                type="button"
                class="btn-mini protagonist-preview-toggle"
                @click="toggleProtagonistPreviewVisible"
              >
                {{ protagonistPreviewVisible ? "隐藏主角图" : "显示主角图" }}
              </button>
              <div v-show="protagonistPreviewVisible" class="protagonist-preview">
                <button
                  type="button"
                  class="protagonist-preview-btn"
                  title="点击查看大图"
                  @click="openProtagonistPreview"
                >
                  <img :src="protagonistPreviewUrl" alt="主角预览" />
                  <span class="protagonist-preview-zoom">🔍 点击放大</span>
                </button>
              </div>
            </div>
            <div class="protagonist-actions">
              <button
                type="button"
                class="btn-send btn-secondary"
                :disabled="protagonistDesignLoading || generating"
                @click="handlePreviewProtagonist"
              >
                {{ protagonistDesignLoading ? "生成中…" : "生成主角预览" }}
              </button>
              <button
                type="button"
                class="btn-send btn-confirm"
                :disabled="
                  protagonistDesignLoading ||
                  generating ||
                  !protagonistPreviewUrl
                "
                @click="handleConfirmProtagonist"
              >
                确认主角
              </button>
              <button
                v-if="protagonistDesignConfirmed || protagonistPreviewUrl"
                type="button"
                class="btn-send btn-reset"
                :disabled="protagonistDesignLoading || generating"
                @click="handleResetProtagonist"
              >
                重置主角
              </button>
            </div>
            </div>
          </section>

          <section v-if="showStoryboardPanel" class="episode-cast-panel collapsible-section">
            <div class="episode-cast-head collapsible-head">
              <div>
                <h4>角色库</h4>
                <p class="episode-cast-hint">
                  管理本集角色与造型时期（上传或 AI 生成参考图）；在各分镜卡片中选择出镜角色与造型，无需在分镜里改提示词或重绘。
                </p>
              </div>
              <div class="episode-cast-head-actions">
                <button
                  type="button"
                  class="btn-mini"
                  :disabled="generating"
                  @click="showAddCharacterForm = !showAddCharacterForm"
                >
                  {{ showAddCharacterForm ? "取消添加" : "添加角色" }}
                </button>
                <button
                  type="button"
                  class="btn-mini"
                  :disabled="generating"
                  @click="handleSyncCharacters"
                >
                  从分镜识别角色
                </button>
                <button
                  type="button"
                  class="btn-mini"
                  @click="castSectionOpen = !castSectionOpen"
                >
                  {{ castSectionOpen ? "收起" : "展开" }}
                </button>
              </div>
            </div>

            <div v-show="showAddCharacterForm" class="add-character-form">
              <label>
                <span class="label">角色名</span>
                <input v-model="newCharacterName" type="text" placeholder="如：保尔侯爵" />
              </label>
              <label>
                <span class="label">外貌提示词</span>
                <textarea
                  v-model="newCharacterAppearance"
                  rows="3"
                  placeholder="服饰、年龄、气质、五官特征…"
                />
              </label>
              <label class="upload-ref-label">
                <span class="label">参考图（可选，本地上传）</span>
                <input type="file" accept="image/png,image/jpeg,image/webp" @change="onNewCharacterRefChange" />
              </label>
              <div class="add-character-actions">
                <button
                  type="button"
                  class="btn-mini"
                  :disabled="generating"
                  @click="handleAddCharacter(false)"
                >
                  确认添加
                </button>
                <button
                  type="button"
                  class="btn-send btn-secondary"
                  :disabled="generating || !newCharacterName.trim() || !newCharacterAppearance.trim()"
                  @click="handleAddCharacter(true)"
                >
                  {{ generating ? "处理中…" : "添加并绘制角色" }}
                </button>
              </div>
            </div>

            <div v-show="castSectionOpen" class="episode-cast-list">
              <p v-if="!scriptCharacters.length" class="episode-cast-empty">
                暂无角色。点击「从分镜识别角色」自动提取，或「添加角色」手动创建。
              </p>
              <article
                v-for="char in scriptCharacters"
                :key="char.id"
                class="episode-cast-card"
              >
                <div class="episode-cast-card-head">
                  <input
                    v-model="char.name"
                    class="episode-cast-name-input"
                    type="text"
                  />
                  <span :class="['episode-cast-role', char.role]">{{ characterRoleLabel(char.role) }}</span>
                  <button
                    type="button"
                    class="btn-mini btn-danger episode-cast-delete"
                    :disabled="generating"
                    @click="handleDeleteCharacter(char)"
                  >
                    删除
                  </button>
                </div>

                <div class="variant-periods">
                  <div class="variant-periods-head">
                    <span class="label">造型时期</span>
                    <span class="variant-default-hint">默认造型用于未单独指定的分镜；分镜内选择优先</span>
                    <button type="button" class="btn-mini" @click="startAddVariant(char.id)">+ 添加时期</button>
                  </div>
                  <div class="variant-strip">
                    <div
                      v-for="variant in characterVariantList(char)"
                      :key="`${char.id}-${variant.variant_id}`"
                      :class="[
                        'variant-slot-wrap',
                        editingVariant?.charId === char.id &&
                          editingVariant?.variantId === variant.variant_id &&
                          'active',
                      ]"
                    >
                      <button
                        type="button"
                        :class="[
                          'variant-slot',
                          isDefaultVariant(char, variant.variant_id) && 'is-default',
                        ]"
                        @click="selectVariantEdit(char, variant)"
                      >
                        <span v-if="isDefaultVariant(char, variant.variant_id)" class="variant-default-badge">
                          默认
                        </span>
                        <img
                          v-if="variant.ref_image"
                          :src="characterRefImageUrl(char.id, variant.variant_id)"
                          :alt="variantLabel(variant)"
                        />
                        <span v-else class="variant-slot-empty">无图</span>
                        <span class="variant-slot-label">{{ variantLabel(variant) }}</span>
                      </button>
                      <button
                        v-if="!isDefaultVariant(char, variant.variant_id)"
                        type="button"
                        class="btn-mini variant-set-default"
                        :disabled="generating"
                        @click="handleSetDefaultVariant(char, variant.variant_id)"
                      >
                        设为默认
                      </button>
                    </div>
                    <button type="button" class="variant-add" title="添加造型时期" @click="startAddVariant(char.id)">
                      +
                    </button>
                  </div>
                </div>

                <div v-if="addingVariantFor === char.id" class="variant-editor">
                  <label>
                    <span class="label">时期名称</span>
                    <input v-model="newVariantLabel" type="text" placeholder="如：成年、初见阳光、变身" />
                  </label>
                  <label>
                    <span class="label">外貌提示词</span>
                    <textarea v-model="newVariantAppearance" rows="3" placeholder="该时期的服饰、状态、气质…" />
                  </label>
                  <div class="episode-cast-actions">
                    <button
                      type="button"
                      class="btn-mini"
                      :disabled="isVariantLoading(char.id, 'new', 'add')"
                      @click="handleAddVariant(char.id)"
                    >
                      {{ isVariantLoading(char.id, "new", "add") ? "添加中…" : "确认添加" }}
                    </button>
                    <button type="button" class="btn-mini" @click="cancelVariantEdit">取消</button>
                  </div>
                </div>

                <div
                  v-if="editingVariant?.charId === char.id"
                  class="variant-editor"
                >
                  <label>
                    <span class="label">时期名称</span>
                    <input v-model="editingVariant.label" type="text" />
                  </label>
                  <label>
                    <span class="label">外貌提示词</span>
                    <textarea v-model="editingVariant.appearance" rows="4" />
                  </label>
                  <div class="variant-editor-preview">
                    <img
                      v-if="charById(char.id)?.variants?.[editingVariant.variantId]?.ref_image"
                      :src="characterRefImageUrl(char.id, editingVariant.variantId)"
                      :alt="editingVariant.label"
                    />
                    <span v-else class="episode-cast-no-ref">该时期暂无参考图</span>
                  </div>
                  <div class="episode-cast-actions">
                    <label class="btn-mini upload-ref-btn">
                      {{
                        isVariantLoading(char.id, editingVariant.variantId, "upload")
                          ? "上传中…"
                          : "上传参考图"
                      }}
                      <input
                        type="file"
                        accept="image/png,image/jpeg,image/webp"
                        :disabled="isVariantLoading(char.id, editingVariant.variantId, 'upload')"
                        @change="
                          (e) =>
                            handleUploadVariantRef(char.id, editingVariant.variantId, e)
                        "
                      />
                    </label>
                    <button
                      type="button"
                      class="btn-mini"
                      :disabled="isVariantLoading(char.id, editingVariant.variantId, 'ai')"
                      @click="
                        handleAiGenerateVariant(
                          char.id,
                          editingVariant.variantId,
                          editingVariant.appearance
                        )
                      "
                    >
                      {{
                        isVariantLoading(char.id, editingVariant.variantId, "ai")
                          ? "绘制中…"
                          : charById(char.id)?.variants?.[editingVariant.variantId]?.ref_image
                            ? "重绘角色"
                            : "绘制角色"
                      }}
                    </button>
                    <button
                      type="button"
                      class="btn-mini"
                      :disabled="isVariantLoading(char.id, editingVariant.variantId, 'save')"
                      @click="handleSaveVariant"
                    >
                      {{
                        isVariantLoading(char.id, editingVariant.variantId, "save")
                          ? "保存中…"
                          : "保存"
                      }}
                    </button>
                    <button type="button" class="btn-mini" @click="cancelVariantEdit">关闭</button>
                  </div>
                </div>

                <div class="episode-cast-actions episode-cast-actions-foot">
                  <button type="button" class="btn-mini" :disabled="generating" @click="handleSaveCharacter(char)">
                    保存角色名
                  </button>
                </div>
              </article>
            </div>
          </section>

          <div class="plot-field collapsible-section">
            <div class="collapsible-head">
              <span class="label">剧情正文 <em>*</em></span>
              <button
                type="button"
                class="btn-mini collapsible-toggle"
                @click="plotSectionOpen = !plotSectionOpen"
              >
                {{ plotSectionOpen ? "收起" : "展开" }}
              </button>
            </div>
            <textarea
              v-show="plotSectionOpen"
              v-model="plot"
              rows="5"
              placeholder="粘贴本集小说片段或剧情描述…"
              @blur="onPlotBlur"
            />
          </div>

          <div v-if="showStoryboardPanel" class="storyboard-notice">
            分镜已就绪（共 {{ sceneScript.scenes.length }} 镜，已有图 {{ sceneImageStats.withImages }} 镜）。
            可只生成分镜，或点「生成分镜并出图」一步完成；生成图片时已有图片的镜会自动跳过。
          </div>

          <div class="composer-actions">
            <span class="hint">
              {{ currentStyleLabel }} · 横屏 16:9
              <template v-if="protagonistLocked"> · 主角已锁定</template>
              <template v-if="needsProtagonistDesign && !protagonistDesignConfirmed">
                · <span class="hint-warn">请先确认主角</span>
              </template>
              <template v-if="!showStoryboardPanel">
                · 步骤：① 生成分镜 → ② 生成图片 → ③ 生成视频
              </template>
            </span>
            <div class="composer-buttons composer-buttons-wrap">
              <button
                class="btn-send btn-secondary"
                type="button"
                :disabled="generating || !canGenerate"
                @click="handleGenerateStoryboard('video')"
              >
                {{
                  generating && genMode === "video"
                    ? "生成中…"
                    : showStoryboardPanel
                      ? "重新生成分镜（视频）"
                      : "生成分镜（视频）"
                }}
              </button>
              <button
                class="btn-send btn-secondary"
                type="button"
                :disabled="generating || !canGenerate"
                @click="handleGenerateStoryboard('video', { withImages: true })"
              >
                {{
                  generating && genMode === "video"
                    ? "生成中…"
                    : showStoryboardPanel
                      ? "重新生成分镜并出图（视频）"
                      : "生成分镜并出图（视频）"
                }}
              </button>
              <button
                class="btn-send"
                type="button"
                :disabled="generating || !canGenerate"
                @click="handleGenerateStoryboard('anime')"
              >
                {{
                  generating && genMode === "anime"
                    ? "生成中…"
                    : showStoryboardPanel
                      ? "重新生成分镜（动画）"
                      : "生成分镜（动画）"
                }}
              </button>
              <button
                class="btn-send"
                type="button"
                :disabled="generating || !canGenerate"
                @click="handleGenerateStoryboard('anime', { withImages: true })"
              >
                {{
                  generating && genMode === "anime"
                    ? "生成中…"
                    : showStoryboardPanel
                      ? "重新生成分镜并出图（动画）"
                      : "生成分镜并出图（动画）"
                }}
              </button>
            </div>
            <p v-if="error && !generating" class="composer-error">{{ error }}</p>
          </div>
        </div>
      </div>

      <section
        v-if="showStoryboardPanel"
        ref="storyboardRef"
        class="storyboard-panel storyboard-panel-main"
      >
        <div class="storyboard-head">
          <div>
            <h3>分镜编排</h3>
            <p v-if="workflowStepLabel" class="storyboard-step-hint">{{ workflowStepLabel }}</p>
          </div>
          <span class="storyboard-meta">
            共 {{ sceneScript.scenes.length }} 镜
            <span class="storyboard-style-tag">画风：{{ currentStyleLabel }}</span>
            <template v-if="workflowStep === 'images'"> · 图片已生成</template>
            <template v-else-if="storyboardConfirmed"> · 已确认</template>
            <template v-else> · 待确认</template>
          </span>
        </div>
        <div class="workflow-steps">
          <span :class="['workflow-step', workflowStep === 'storyboard' && 'active']">① 编辑分镜</span>
          <span :class="['workflow-step', workflowStep === 'storyboard' && storyboardConfirmed && 'active']">② 确认分镜</span>
          <span :class="['workflow-step', workflowStep === 'images' && 'active']">③ 生成图片</span>
          <span :class="['workflow-step', workflowStep === 'done' && 'active']">④ 生成视频</span>
        </div>
        <p class="storyboard-style-bar">
          当前分镜画风：<strong>{{ currentStyleLabel }}</strong>
          <span v-if="selectedStyle" class="storyboard-style-id">({{ selectedStyle }})</span>
          <span class="storyboard-style-hint"> · 重绘/生成图片均使用此画风</span>
        </p>

        <div class="storyboard-list">
          <article
            v-for="(scene, index) in sceneScript.scenes"
            :key="scene.id"
            class="storyboard-card"
          >
            <div class="storyboard-card-head">
              <div class="scene-head-text">
                <span class="scene-badge">第 {{ index + 1 }} 镜</span>
                <p v-if="scene.narration" class="scene-narration-preview">
                  {{ scene.narration }}
                </p>
              </div>
              <div class="scene-actions">
                <button
                  type="button"
                  class="btn-mini"
                  title="在此镜后插入新分镜"
                  @click="insertSceneAfter(index)"
                >
                  插入
                </button>
                <button
                  type="button"
                  class="btn-mini"
                  :disabled="index === 0"
                  @click="moveScene(index, -1)"
                >
                  ↑
                </button>
                <button
                  type="button"
                  class="btn-mini"
                  :disabled="index === sceneScript.scenes.length - 1"
                  @click="moveScene(index, 1)"
                >
                  ↓
                </button>
                <button
                  type="button"
                  class="btn-mini btn-danger"
                  :disabled="sceneScript.scenes.length <= 1"
                  @click="removeScene(index)"
                >
                  删除
                </button>
                <button
                  v-if="workflowStep === 'images' && scene.image_path"
                  type="button"
                  class="btn-mini"
                  @click="toggleScenePreview(scene.id)"
                >
                  {{ isScenePreviewVisible(scene.id) ? "隐藏分镜图" : "显示分镜图" }}
                </button>
              </div>
            </div>
            <div
              class="storyboard-card-body"
              :class="{ 'no-preview': !isScenePreviewVisible(scene.id) }"
            >
              <div
                v-if="workflowStep === 'images' && isScenePreviewVisible(scene.id) && scene.image_path"
                class="scene-preview"
              >
                <button
                  type="button"
                  class="scene-preview-btn"
                  title="双击放大"
                  @dblclick="openSceneLightbox(scene.id, index)"
                >
                  <img
                    :src="sceneImageSrc(scene.id)"
                    :alt="`分镜 ${index + 1}`"
                    loading="lazy"
                  />
                  <span class="scene-preview-zoom">🔍 双击放大</span>
                </button>
              </div>
              <div class="scene-fields">
                <label>
                  <span class="mini-label">旁白 / 台词</span>
                  <textarea
                    v-model="scene.narration"
                    rows="2"
                    placeholder="本镜旁白或对白（中文）"
                    @input="markStoryboardDirty"
                  />
                </label>
                <label>
                  <span class="mini-label">画面描述</span>
                  <textarea
                    v-model="scene.visual_prompt"
                    rows="3"
                    placeholder="镜头、人物动作、环境、光影…（中文）"
                    @input="markStoryboardDirty"
                  />
                </label>
                <div
                  v-if="scene.scene_type !== 'environment'"
                  class="scene-cast-picks"
                >
                  <div class="scene-cast-head">
                    <span class="mini-label">出镜角色</span>
                    <select
                      v-if="availableCharactersForScene(scene).length"
                      class="scene-cast-add"
                      @change="onAddCharacterToScene(scene, $event)"
                    >
                      <option value="">+ 添加角色</option>
                      <option
                        v-for="c in availableCharactersForScene(scene)"
                        :key="c.id"
                        :value="c.id"
                      >
                        {{ c.name }}
                      </option>
                    </select>
                  </div>
                  <p v-if="!sceneCharacters(scene).length" class="scene-cast-empty">
                    本镜暂无出镜角色，可从角色库添加。
                  </p>
                  <div
                    v-for="cid in sceneCharacters(scene)"
                    :key="`${scene.id}-${cid}`"
                    class="scene-variant-row"
                  >
                    <span class="scene-variant-name">{{ characterNameById(cid) }}</span>
                    <select
                      :value="getSceneVariant(scene, cid)"
                      @change="setSceneVariant(scene, cid, $event.target.value)"
                    >
                      <option
                        v-for="v in characterVariantList(charById(cid))"
                        :key="v.variant_id"
                        :value="v.variant_id"
                      >
                        {{ variantLabel(v) }}{{ isDefaultVariant(charById(cid), v.variant_id) ? "（角色默认）" : "" }}
                      </option>
                    </select>
                    <span
                      v-if="sceneHasVariantOverride(scene, cid)"
                      class="scene-variant-override-tag"
                      title="本分镜单独指定，优先于角色默认"
                    >
                      分镜指定
                    </span>
                    <button
                      type="button"
                      class="btn-mini btn-danger scene-cast-remove"
                      @click="removeCharacterFromScene(scene, cid)"
                    >
                      移除
                    </button>
                  </div>
                </div>
                <label class="shot-field">
                  <span class="mini-label">景别</span>
                  <select v-model="scene.shot_type" @change="markStoryboardDirty">
                    <option value="wide">远景</option>
                    <option value="medium">中景</option>
                    <option value="close">近景</option>
                    <option value="close_up">特写</option>
                    <option value="extreme_close">大特写</option>
                    <option value="low_angle">仰角</option>
                    <option value="high_angle">俯角</option>
                  </select>
                </label>
                <button
                  v-if="workflowStep === 'images'"
                  type="button"
                  class="btn-mini btn-regen"
                  :disabled="generating || sceneRegenerating[scene.id]"
                  @click="handleRegenerateScene(scene)"
                >
                  {{
                    sceneRegenerating[scene.id]
                      ? "生成中…"
                      : scene.image_path
                        ? "重绘此镜"
                        : "生成此镜"
                  }}
                </button>
              </div>
            </div>
          </article>
        </div>
        <div class="storyboard-toolbar">
          <button type="button" class="btn-mini" @click="addScene">+ 末尾添加</button>
          <button
            type="button"
            class="btn-send btn-secondary"
            :disabled="generating || scenesSaving"
            @click="handleSaveScenes"
          >
            {{ scenesSaving ? "确认中…" : storyboardConfirmed ? "再次确认分镜" : "确认分镜" }}
          </button>
          <button
            v-if="workflowStep === 'storyboard' || sceneImageStats.withoutImages > 0"
            type="button"
            class="btn-send"
            :disabled="generating"
            @click="handleGenerateImages"
          >
            {{ generating ? "生成中…" : generateImagesButtonLabel }}
          </button>
          <button
            v-if="workflowStep === 'images'"
            type="button"
            class="btn-send"
            :disabled="generating"
            @click="handleGenerateVideo"
          >
            {{ generating ? "合成中…" : genMode === "anime" ? "生成动画" : "生成视频" }}
          </button>
        </div>
      </section>
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

    <Transition name="alert-fade">
      <div
        v-if="sceneLightboxOpen && sceneLightboxSrc"
        class="protagonist-lightbox scene-lightbox"
        @keydown.esc="closeSceneLightbox"
      >
        <div class="protagonist-lightbox-backdrop" @click="closeSceneLightbox" />
        <div class="protagonist-lightbox-panel" role="dialog" aria-modal="true">
          <button
            type="button"
            class="protagonist-lightbox-close"
            aria-label="关闭"
            @click="closeSceneLightbox"
          >
            ✕
          </button>
          <p v-if="sceneLightboxTitle" class="scene-lightbox-title">{{ sceneLightboxTitle }}</p>
          <img :src="sceneLightboxSrc" :alt="sceneLightboxTitle" />
        </div>
      </div>
    </Transition>

    <Transition name="alert-fade">
      <div
        v-if="protagonistPreviewOpen && protagonistPreviewUrl"
        class="protagonist-lightbox"
        @keydown.esc="closeProtagonistPreview"
      >
        <div class="protagonist-lightbox-backdrop" @click="closeProtagonistPreview" />
        <div class="protagonist-lightbox-panel" role="dialog" aria-modal="true">
          <button
            type="button"
            class="protagonist-lightbox-close"
            aria-label="关闭"
            @click="closeProtagonistPreview"
          >
            ✕
          </button>
          <img :src="protagonistPreviewUrl" alt="主角预览大图" />
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
  min-height: 0;
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

.drama-groups {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.drama-group {
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 16px;
  background: var(--card);
}

.drama-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 16px;
}

.drama-cover {
  position: relative;
  width: 96px;
  height: 54px;
  border-radius: 10px;
  overflow: hidden;
  background: #1a1a1a;
  flex-shrink: 0;
}

.drama-cover img {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.drama-cover-fallback {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
}

.drama-head-info h2 {
  margin: 0 0 4px;
  font-size: 18px;
}

.drama-head-info p {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
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
  aspect-ratio: 16 / 9;
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

.workflow-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.chat {
  flex: 0 1 auto;
  overflow-y: auto;
  padding: 16px 0 16px;
  min-height: 120px;
  max-height: 32vh;
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

.episode-stepper-field {
  flex: 0 0 168px !important;
}

.episode-stepper {
  display: flex;
  align-items: center;
  gap: 4px;
}

.episode-stepper input {
  flex: 1;
  min-width: 0;
  text-align: center;
  padding-left: 6px;
  padding-right: 6px;
}

.stepper-btn {
  width: 32px;
  height: 38px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--card);
  color: var(--text);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}

.stepper-btn:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.stepper-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.episode-reset-row {
  display: flex;
  gap: 6px;
  margin-top: 6px;
  flex-wrap: wrap;
}

.btn-mini {
  border: none;
  background: rgba(107, 124, 255, 0.08);
  color: var(--primary);
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 999px;
  cursor: pointer;
}

.btn-mini:hover:not(:disabled) {
  background: rgba(107, 124, 255, 0.16);
}

.btn-mini:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.style-section {
  margin-bottom: 14px;
}

.style-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.style-current {
  font-size: 12px;
  color: var(--primary);
  font-weight: 600;
}

.style-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
  gap: 10px;
  max-height: 220px;
  overflow-y: auto;
  padding-right: 4px;
}

.style-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 10px 10px 10px 12px;
  border: 2px solid var(--border);
  border-radius: 14px;
  background: var(--card);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.12s;
  overflow: hidden;
}

.style-card:hover {
  border-color: rgba(107, 124, 255, 0.45);
  transform: translateY(-1px);
}

.style-card.active {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(107, 124, 255, 0.15);
}

.style-card-accent {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 5px;
}

.style-card-tag {
  font-size: 10px;
  font-weight: 700;
  color: var(--muted);
  letter-spacing: 0.04em;
}

.style-card-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.3;
}

.style-card-desc {
  font-size: 11px;
  color: var(--muted);
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.style-card-for {
  font-size: 10px;
  color: #8b9bff;
  line-height: 1.3;
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

.collapsible-section {
  margin-bottom: 14px;
}

.collapsible-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.collapsible-head-text {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.collapsible-toggle {
  flex-shrink: 0;
}

.storyboard-notice {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid rgba(107, 124, 255, 0.25);
  background: rgba(107, 124, 255, 0.08);
  font-size: 13px;
  line-height: 1.5;
  color: var(--text);
}

.storyboard-panel {
  margin-bottom: 14px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: rgba(107, 124, 255, 0.03);
}

.storyboard-panel-main {
  flex: 1 1 auto;
  min-height: 320px;
  max-height: 52vh;
  overflow-y: auto;
  margin-top: 16px;
  background: var(--card);
  box-shadow: var(--shadow);
}

.storyboard-step-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--muted);
}

.workflow-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.workflow-step {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  border: 1px solid var(--border);
  color: var(--muted);
  background: rgba(0, 0, 0, 0.02);
}

.workflow-step.active {
  border-color: var(--primary);
  color: var(--primary);
  background: rgba(107, 124, 255, 0.1);
}

.storyboard-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.storyboard-head h3 {
  margin: 0;
  font-size: 15px;
}

.storyboard-meta {
  font-size: 12px;
  color: var(--muted);
  text-align: right;
}

.storyboard-style-tag {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(107, 124, 255, 0.12);
  color: var(--primary);
  font-weight: 500;
}

.storyboard-style-bar {
  margin: 0 0 12px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(107, 124, 255, 0.06);
  border: 1px solid rgba(107, 124, 255, 0.15);
  font-size: 13px;
  color: var(--text);
}

.storyboard-style-bar strong {
  color: var(--primary);
}

.storyboard-style-id {
  font-size: 12px;
  color: var(--muted);
}

.storyboard-style-hint {
  font-size: 12px;
  color: var(--muted);
}

.episode-cast-panel {
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: rgba(107, 124, 255, 0.04);
}

.episode-cast-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.episode-cast-head h4 {
  margin: 0;
  font-size: 14px;
}

.episode-cast-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.episode-cast-head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.episode-cast-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.episode-cast-card {
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--card);
}

.episode-cast-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.episode-cast-name {
  font-weight: 600;
  font-size: 14px;
}

.episode-cast-role {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.06);
  color: var(--muted);
}

.episode-cast-role.protagonist {
  background: rgba(107, 124, 255, 0.15);
  color: var(--primary);
}

.episode-cast-role.supporting {
  background: rgba(244, 162, 97, 0.15);
  color: #c45c26;
}

.episode-cast-body {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 12px;
}

.episode-cast-preview {
  width: 96px;
  height: 128px;
  border-radius: 8px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.04);
  display: flex;
  align-items: center;
  justify-content: center;
}

.episode-cast-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.episode-cast-no-ref {
  font-size: 11px;
  color: var(--muted);
  padding: 8px;
  text-align: center;
}

.episode-cast-fields textarea {
  width: 100%;
  margin-top: 4px;
  margin-bottom: 8px;
}

.episode-cast-note {
  margin: 0 0 8px;
  font-size: 11px;
  color: var(--muted);
  line-height: 1.4;
}

.episode-cast-empty {
  margin: 0;
  padding: 12px;
  font-size: 13px;
  color: var(--muted);
  text-align: center;
  border: 1px dashed var(--border);
  border-radius: 8px;
}

.add-character-form {
  display: grid;
  gap: 10px;
  margin-bottom: 12px;
  padding: 12px;
  border: 1px dashed var(--primary);
  border-radius: 10px;
  background: rgba(107, 124, 255, 0.06);
}

.add-character-form input[type="text"],
.add-character-form textarea {
  width: 100%;
  margin-top: 4px;
}

.upload-ref-label input[type="file"] {
  margin-top: 6px;
  font-size: 12px;
}

.add-character-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.episode-cast-delete {
  margin-left: auto;
}

.episode-cast-name-input {
  flex: 1;
  min-width: 0;
  font-weight: 600;
  font-size: 14px;
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 2px 6px;
  background: transparent;
}

.episode-cast-name-input:focus {
  border-color: var(--primary);
  background: var(--card);
  outline: none;
}

.episode-cast-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.upload-ref-btn {
  position: relative;
  cursor: pointer;
  overflow: hidden;
}

.upload-ref-btn input[type="file"] {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.episode-cast-actions-foot {
  margin-top: 8px;
}

.variant-periods {
  margin-top: 8px;
}

.variant-periods-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.variant-default-hint {
  flex: 1;
  min-width: 160px;
  font-size: 11px;
  color: var(--muted, #888);
}

.variant-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: stretch;
}

.variant-slot-wrap {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
}

.variant-slot-wrap.active .variant-slot {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(107, 124, 255, 0.2);
}

.variant-slot.is-default {
  border-color: #4a90d9;
}

.variant-default-badge {
  position: absolute;
  top: 4px;
  left: 4px;
  z-index: 1;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  line-height: 1.4;
  color: #fff;
  background: #4a90d9;
}

.variant-set-default {
  align-self: center;
  font-size: 11px;
}

.variant-slot {
  position: relative;
  width: 88px;
  padding: 0;
  border: 2px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  background: var(--card);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: stretch;
}

.variant-slot img {
  width: 100%;
  height: 96px;
  object-fit: cover;
  display: block;
}

.variant-slot-empty {
  height: 96px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--muted);
  background: rgba(0, 0, 0, 0.04);
}

.variant-slot-label {
  padding: 4px 6px;
  font-size: 11px;
  text-align: center;
  line-height: 1.3;
  color: var(--text);
}

.variant-add {
  width: 88px;
  min-height: 120px;
  border: 2px dashed var(--border);
  border-radius: 10px;
  background: rgba(107, 124, 255, 0.04);
  color: var(--primary);
  font-size: 28px;
  cursor: pointer;
}

.variant-add:hover {
  border-color: var(--primary);
  background: rgba(107, 124, 255, 0.1);
}

.variant-editor {
  margin-top: 10px;
  padding: 10px;
  border: 1px solid rgba(107, 124, 255, 0.25);
  border-radius: 10px;
  background: rgba(107, 124, 255, 0.04);
  display: grid;
  gap: 8px;
}

.variant-editor input,
.variant-editor textarea {
  width: 100%;
  margin-top: 4px;
}

.variant-editor-preview {
  width: 120px;
  height: 160px;
  border-radius: 8px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.04);
}

.variant-editor-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.scene-cast-picks {
  display: grid;
  gap: 8px;
  padding: 8px 0;
}

.scene-cast-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.scene-cast-add {
  flex: 1;
  min-width: 0;
  max-width: 200px;
}

.scene-cast-empty {
  margin: 0;
  font-size: 12px;
  color: var(--muted, #888);
}

.scene-cast-remove {
  flex-shrink: 0;
}

.scene-variant-picks {
  display: grid;
  gap: 8px;
  padding: 8px 0;
}

.scene-variant-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.scene-variant-name {
  min-width: 72px;
  font-size: 13px;
  color: var(--text);
}

.scene-variant-row select {
  flex: 1;
  min-width: 0;
}

.scene-variant-override-tag {
  flex-shrink: 0;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  color: #8a6d3b;
  background: #fff3cd;
  white-space: nowrap;
}

.storyboard-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.storyboard-card {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--card, #fff);
  overflow: hidden;
}

.storyboard-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  background: rgba(107, 124, 255, 0.06);
  border-bottom: 1px solid var(--border);
}

.scene-head-text {
  flex: 1;
  min-width: 0;
}

.scene-badge {
  font-size: 13px;
  font-weight: 600;
}

.scene-narration-preview {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--muted);
  word-break: break-word;
}

.scene-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  flex-shrink: 0;
}

.storyboard-card-body {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 12px;
  padding: 12px;
}

.storyboard-card-body.no-preview {
  grid-template-columns: 1fr;
}

.scene-preview {
  width: 140px;
  height: 88px;
  border-radius: 8px;
  overflow: hidden;
  background: #111;
}

.scene-preview-btn {
  position: relative;
  display: block;
  width: 100%;
  height: 100%;
  padding: 0;
  border: none;
  background: transparent;
  cursor: zoom-in;
}

.scene-preview-btn img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.scene-preview-zoom {
  position: absolute;
  right: 4px;
  bottom: 4px;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  color: #fff;
  background: rgba(0, 0, 0, 0.55);
  opacity: 0;
  transition: opacity 0.15s;
}

.scene-preview-btn:hover .scene-preview-zoom {
  opacity: 1;
}

.scene-lightbox-title {
  margin: 0 0 10px;
  font-size: 14px;
  color: var(--muted);
  text-align: center;
}

.scene-preview-empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #888;
  background: rgba(0, 0, 0, 0.06);
}

.scene-fields {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mini-label {
  display: block;
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 4px;
}

.scene-fields textarea,
.shot-field select {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 13px;
  resize: vertical;
  font-family: inherit;
}

.shot-field select {
  max-width: 160px;
}

.btn-mini {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  font-size: 12px;
  cursor: pointer;
}

.btn-mini:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.btn-mini:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-mini.btn-danger:hover:not(:disabled) {
  border-color: #e0843b;
  color: #e0843b;
}

.btn-mini.btn-regen {
  align-self: flex-start;
  margin-top: 4px;
}

.storyboard-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
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

.composer-buttons-wrap {
  flex-wrap: wrap;
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

.protagonist-design {
  margin-bottom: 14px;
  padding: 14px;
  border: 1px dashed var(--border);
  border-radius: 14px;
  background: rgba(107, 124, 255, 0.04);
}

.costume-refs-block {
  margin-bottom: 12px;
}

.costume-refs-hint {
  margin: 6px 0 10px;
  font-size: 12px;
  color: var(--muted);
}

.costume-refs-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.costume-ref-item {
  position: relative;
  width: 88px;
}

.costume-ref-item img {
  width: 88px;
  height: 88px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid var(--border);
}

.costume-ref-delete {
  margin-top: 4px;
  width: 100%;
  padding: 2px 0;
  border: none;
  background: transparent;
  color: #e0843b;
  font-size: 11px;
  cursor: pointer;
}

.costume-ref-delete:hover:not(:disabled) {
  text-decoration: underline;
}

.protagonist-design-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.design-badge {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
}

.design-badge.pending {
  background: #fff4e6;
  color: #e0843b;
}

.design-badge.confirmed {
  background: #ecfdf5;
  color: #059669;
}

.design-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.ref-upload-row {
  align-items: center;
}

.ref-upload input[type="file"] {
  font-size: 13px;
}

.ref-file-name {
  font-size: 12px;
  color: var(--muted);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.btn-link {
  border: none;
  background: none;
  color: var(--primary);
  font-size: 13px;
  cursor: pointer;
  padding: 0 4px;
}

.protagonist-preview-block {
  margin-top: 12px;
}

.protagonist-preview-toggle {
  margin-bottom: 8px;
}

.protagonist-preview {
  margin: 12px 0;
  max-width: 220px;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--border);
  background: #111;
}

.protagonist-preview-btn {
  display: block;
  width: 100%;
  padding: 0;
  border: none;
  background: transparent;
  cursor: zoom-in;
  position: relative;
}

.protagonist-preview-btn img {
  display: block;
  width: 100%;
  height: auto;
}

.protagonist-preview-zoom {
  position: absolute;
  right: 8px;
  bottom: 8px;
  font-size: 11px;
  color: #fff;
  background: rgba(0, 0, 0, 0.55);
  padding: 3px 8px;
  border-radius: 6px;
  pointer-events: none;
}

.protagonist-preview-btn:hover .protagonist-preview-zoom {
  background: rgba(0, 0, 0, 0.72);
}

.protagonist-lightbox {
  position: fixed;
  inset: 0;
  z-index: 210;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.protagonist-lightbox-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.72);
  backdrop-filter: blur(2px);
}

.protagonist-lightbox-panel {
  position: relative;
  z-index: 1;
  max-width: min(920px, 96vw);
  max-height: 92vh;
}

.protagonist-lightbox-panel img {
  display: block;
  max-width: 100%;
  max-height: 92vh;
  width: auto;
  height: auto;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.45);
}

.protagonist-lightbox-close {
  position: absolute;
  top: -12px;
  right: -12px;
  z-index: 2;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.95);
  color: #334155;
  font-size: 16px;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
}

.protagonist-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.btn-send.btn-confirm {
  background: #059669;
}

.btn-send.btn-confirm:hover:not(:disabled) {
  background: #047857;
}

.btn-send.btn-reset {
  background: transparent;
  color: #e0843b;
  border: 1px solid #e0843b;
}

.btn-send.btn-reset:hover:not(:disabled) {
  background: rgba(224, 132, 59, 0.08);
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
