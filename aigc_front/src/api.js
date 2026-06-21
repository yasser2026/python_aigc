const API_BASE = import.meta.env.VITE_API_BASE || "/api";

/** 后端 styles 接口不可用时的兜底列表 */
export const FALLBACK_STYLES = [
  { id: "jp_cel", label: "日系赛璐璐", suited_for: "热血战斗、校园青春" },
  { id: "cn_semi_realistic", label: "国漫半写实厚涂", suited_for: "玄幻修仙、都市爽文" },
  { id: "kr_manhwa", label: "韩漫精致美型", suited_for: "都市霸总、甜宠言情" },
  { id: "ink_gongbi", label: "水墨国风 / 工笔", suited_for: "仙侠修仙、古言历史" },
  { id: "manga_bw", label: "黑白漫画 / 网点纸", suited_for: "悬疑推理、少年战斗" },
  { id: "us_comic", label: "美式硬派漫画", suited_for: "超级英雄、热血硬派" },
  { id: "realistic_anime", label: "写实厚涂动漫", suited_for: "都市情感、悬疑" },
  { id: "chibi", label: "Q版萌系", suited_for: "搞笑日常、轻松治愈" },
  { id: "watercolor", label: "水彩绘本", suited_for: "童话、治愈、文艺" },
  { id: "cyberpunk", label: "赛博朋克", suited_for: "科幻、末世、机甲" },
  { id: "retro_90s", label: "90年代复古动漫", suited_for: "怀旧题材、经典冒险" },
  { id: "dark_fantasy", label: "暗黑奇幻", suited_for: "西幻、吸血鬼、黑暗冒险" },
];

export function encodeProjectId(projectId) {
  return projectId
    .split("/")
    .map((seg) => encodeURIComponent(seg))
    .join("/");
}

export async function fetchHealth() {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error("后端不可用");
  return res.json();
}

export async function fetchAnimeHealth() {
  try {
    const res = await fetch(`${API_BASE}/anime/health`);
    if (!res.ok) return { available: false };
    return res.json();
  } catch {
    return { available: false };
  }
}

export async function fetchNovelMeta(novelName) {
  const name = encodeURIComponent(novelName.trim());
  if (!name) return null;
  const res = await fetch(`${API_BASE}/novels/${name}/meta`);
  if (!res.ok) return null;
  return res.json();
}

export async function fetchProtagonistDesign(novelName) {
  const name = encodeURIComponent(novelName.trim());
  if (!name) return null;
  const res = await fetch(`${API_BASE}/novels/${name}/protagonist/design`);
  if (!res.ok) return null;
  return res.json();
}

export function protagonistImageUrl(novelName) {
  const name = encodeURIComponent(novelName.trim());
  if (!name) return "";
  return `${API_BASE}/novels/${name}/protagonist/image?t=${Date.now()}`;
}

export function costumeRefUrl(novelName, refId) {
  const name = encodeURIComponent(novelName.trim());
  if (!name || !refId) return "";
  return `${API_BASE}/novels/${name}/protagonist/costume-refs/${encodeURIComponent(refId)}?t=${Date.now()}`;
}

export async function previewProtagonist({
  novel_name,
  protagonist_name,
  appearance_prompt,
  personality,
  style,
  reference_file,
  reference_files,
}) {
  const name = encodeURIComponent(novel_name.trim());
  const form = new FormData();
  form.append("protagonist_name", protagonist_name.trim());
  form.append("appearance_prompt", appearance_prompt.trim());
  form.append("personality", (personality || "").trim());
  form.append("style", (style || "").trim());
  const files = reference_files?.length
    ? reference_files
    : reference_file
      ? [reference_file]
      : [];
  for (const file of files) {
    form.append("reference_images", file);
  }
  const res = await fetch(`${API_BASE}/novels/${name}/protagonist/preview`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `生成主角预览失败 ${res.status}`);
  }
  return res.json();
}

export async function uploadCostumeRefs({
  novel_name,
  protagonist_name,
  reference_files,
}) {
  const name = encodeURIComponent(novel_name.trim());
  const form = new FormData();
  form.append("protagonist_name", protagonist_name.trim());
  for (const file of reference_files || []) {
    form.append("reference_images", file);
  }
  const res = await fetch(`${API_BASE}/novels/${name}/protagonist/costume-refs`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `上传服饰参考图失败 ${res.status}`);
  }
  return res.json();
}

export async function deleteCostumeRef(novel_name, refId) {
  const name = encodeURIComponent(novel_name.trim());
  const res = await fetch(
    `${API_BASE}/novels/${name}/protagonist/costume-refs/${encodeURIComponent(refId)}`,
    { method: "DELETE" }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `删除参考图失败 ${res.status}`);
  }
  return res.json();
}

export async function confirmProtagonist({
  novel_name,
  appearance,
  personality,
}) {
  const name = encodeURIComponent(novel_name.trim());
  const res = await fetch(`${API_BASE}/novels/${name}/protagonist/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      appearance: appearance?.trim() || null,
      personality: personality?.trim() || null,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `确认主角失败 ${res.status}`);
  }
  return res.json();
}

export async function resetProtagonist(novel_name) {
  const name = encodeURIComponent(novel_name.trim());
  const res = await fetch(`${API_BASE}/novels/${name}/protagonist/reset`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `重置主角失败 ${res.status}`);
  }
  return res.json();
}

export async function saveNovelStyle(novel_name, style) {
  const name = encodeURIComponent(novel_name.trim());
  const res = await fetch(`${API_BASE}/novels/${name}/style`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ style: style || "" }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `保存画风失败 ${res.status}`);
  }
  return res.json();
}

export async function fetchStyles() {
  try {
    const res = await fetch(`${API_BASE}/styles`);
    if (!res.ok) return FALLBACK_STYLES;
    const data = await res.json();
    const list = data.styles || [];
    return list.length ? list : FALLBACK_STYLES;
  } catch {
    return FALLBACK_STYLES;
  }
}

export async function createProject({
  novel_name,
  episode,
  text,
  mode,
  narrative_mode,
  protagonist_name,
  supporting_names,
  style,
  stop_after = "parse_scenes",
  regenerate_storyboard = false,
}) {
  const res = await fetch(`${API_BASE}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      novel_name,
      episode,
      text,
      mode: mode || "video",
      narrative_mode: narrative_mode || "protagonist_focus",
      protagonist_name: protagonist_name?.trim() || null,
      supporting_names: supporting_names?.trim() || null,
      style: style?.trim() || null,
      stop_after: stop_after ?? "parse_scenes",
      regenerate_storyboard: Boolean(regenerate_storyboard),
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `创建失败 ${res.status}`);
  }
  return res.json();
}

export async function fetchProjectScenes(projectId, mode = "video") {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/scenes?mode=${mode}`
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `加载分镜失败 ${res.status}`);
  }
  return res.json();
}

export async function saveProjectScenes(projectId, scenes, mode = "video") {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/scenes?mode=${mode}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenes }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `保存分镜失败 ${res.status}`);
  }
  return res.json();
}

export async function generateProjectImages(projectId, mode = "video") {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/generate-images?mode=${mode}`,
    { method: "POST" }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `生成图片失败 ${res.status}`);
  }
  return res.json();
}

export async function generateProjectVideo(projectId, mode = "video") {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/generate-video?mode=${mode}`,
    { method: "POST" }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `生成视频失败 ${res.status}`);
  }
  return res.json();
}

export async function regenerateSceneImage(
  projectId,
  sceneId,
  { visual_prompt, narration, style },
  mode = "video"
) {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/scenes/${encodeURIComponent(sceneId)}/regenerate-image?mode=${mode}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        visual_prompt: visual_prompt?.trim() || null,
        narration: narration?.trim() || null,
        style: style?.trim() || null,
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `重新生成图片失败 ${res.status}`);
  }
  return res.json();
}

export function sceneImageUrl(projectId, sceneId, mode = "video") {
  return `${API_BASE}/projects/${encodeProjectId(projectId)}/scenes/${encodeURIComponent(sceneId)}/image?mode=${mode}&t=${Date.now()}`;
}

export function characterRefUrl(
  projectId,
  charId,
  mode = "video",
  cacheBust = Date.now(),
  variantId = "default"
) {
  const variant = encodeURIComponent(variantId || "default");
  return `${API_BASE}/projects/${encodeProjectId(projectId)}/characters/${encodeURIComponent(charId)}/image?mode=${mode}&variant=${variant}&t=${cacheBust}`;
}

export async function syncProjectCharacters(projectId, mode = "video") {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/sync-characters?mode=${mode}`,
    { method: "POST" }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `同步角色失败 ${res.status}`);
  }
  return res.json();
}

export async function addProjectCharacter(projectId, { name, appearance }, mode = "video") {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/characters?mode=${mode}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim(), appearance: appearance.trim() }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `添加角色失败 ${res.status}`);
  }
  return res.json();
}

export async function updateProjectCharacter(
  projectId,
  charId,
  { name, appearance, default_variant_id },
  mode = "video"
) {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/characters/${encodeURIComponent(charId)}?mode=${mode}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name?.trim() || null,
        appearance: appearance?.trim() || null,
        default_variant_id: default_variant_id?.trim() || null,
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `保存角色失败 ${res.status}`);
  }
  return res.json();
}

export async function uploadCharacterRef(projectId, charId, file, mode = "video") {
  const form = new FormData();
  form.append("reference_image", file);
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/characters/${encodeURIComponent(charId)}/upload-ref?mode=${mode}`,
    { method: "POST", body: form }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `上传参考图失败 ${res.status}`);
  }
  return res.json();
}

export async function deleteProjectCharacter(projectId, charId, mode = "video") {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/characters/${encodeURIComponent(charId)}?mode=${mode}`,
    { method: "DELETE" }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `删除角色失败 ${res.status}`);
  }
  return res.json();
}

export async function regenerateCharacterRef(
  projectId,
  charId,
  { appearance, style, variant_id },
  mode = "video"
) {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/characters/${encodeURIComponent(charId)}/regenerate-ref?mode=${mode}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        appearance: appearance?.trim() || null,
        style: style?.trim() || null,
        variant_id: variant_id || null,
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `生成角色参考图失败 ${res.status}`);
  }
  return res.json();
}

export async function addCharacterVariant(
  projectId,
  charId,
  { label, appearance, variant_id },
  mode = "video"
) {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/characters/${encodeURIComponent(charId)}/variants?mode=${mode}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        label: label.trim(),
        appearance: appearance.trim(),
        variant_id: variant_id?.trim() || null,
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `添加造型失败 ${res.status}`);
  }
  return res.json();
}

export async function updateCharacterVariant(
  projectId,
  charId,
  variantId,
  { label, appearance },
  mode = "video"
) {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/characters/${encodeURIComponent(charId)}/variants/${encodeURIComponent(variantId)}?mode=${mode}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        label: label?.trim() || null,
        appearance: appearance?.trim() || null,
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `保存造型失败 ${res.status}`);
  }
  return res.json();
}

export async function uploadCharacterVariantRef(
  projectId,
  charId,
  variantId,
  file,
  mode = "video"
) {
  const form = new FormData();
  form.append("reference_image", file);
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/characters/${encodeURIComponent(charId)}/variants/${encodeURIComponent(variantId)}/upload-ref?mode=${mode}`,
    { method: "POST", body: form }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `上传参考图失败 ${res.status}`);
  }
  return res.json();
}

export async function regenerateCharacterVariantRef(
  projectId,
  charId,
  variantId,
  { appearance, style },
  mode = "video"
) {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}/characters/${encodeURIComponent(charId)}/variants/${encodeURIComponent(variantId)}/regenerate-ref?mode=${mode}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        appearance: appearance?.trim() || null,
        style: style?.trim() || null,
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `生成造型参考图失败 ${res.status}`);
  }
  return res.json();
}

export async function getProject(projectId, mode = "video") {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}?mode=${mode}`
  );
  if (!res.ok) throw new Error("查询任务失败");
  return res.json();
}

export function downloadUrl(projectId, mode = "video") {
  return `${API_BASE}/projects/${encodeProjectId(projectId)}/download?mode=${mode}`;
}

export function posterUrl(projectId, mode = "video") {
  return `${API_BASE}/portfolio/${encodeProjectId(projectId)}/poster?mode=${mode}`;
}

export function coverUrl(novelName, mode = "video") {
  return `${API_BASE}/portfolio/cover?novel=${encodeURIComponent(
    novelName
  )}&mode=${mode}`;
}

export async function fetchPortfolio() {
  const res = await fetch(`${API_BASE}/portfolio`);
  if (!res.ok) throw new Error("加载作品集失败");
  return res.json();
}
