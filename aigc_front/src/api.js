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

export async function createProject({ novel_name, episode, text }) {
  const res = await fetch(`${API_BASE}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ novel_name, episode, text }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `创建失败 ${res.status}`);
  }
  return res.json();
}

export async function getProject(projectId) {
  const res = await fetch(
    `${API_BASE}/projects/${encodeProjectId(projectId)}`
  );
  if (!res.ok) throw new Error("查询任务失败");
  return res.json();
}

export function downloadUrl(projectId) {
  return `${API_BASE}/projects/${encodeProjectId(projectId)}/download`;
}

export function posterUrl(projectId) {
  return `${API_BASE}/portfolio/${encodeProjectId(projectId)}/poster`;
}

export async function fetchPortfolio() {
  const res = await fetch(`${API_BASE}/portfolio`);
  if (!res.ok) throw new Error("加载作品集失败");
  return res.json();
}
