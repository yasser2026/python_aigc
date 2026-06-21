const API_BASE = import.meta.env.VITE_API_BASE || "/api";

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

export async function fetchStyles() {
  try {
    const res = await fetch(`${API_BASE}/styles`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.styles || [];
  } catch {
    return [];
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
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `创建失败 ${res.status}`);
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
