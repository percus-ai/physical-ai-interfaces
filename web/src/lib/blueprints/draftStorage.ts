import type { BlueprintNode } from '$lib/recording/blueprint';

export type BlueprintSessionKind = 'recording' | 'teleop' | 'inference';

type BlueprintDraft = {
  blueprintId: string;
  blueprint: BlueprintNode;
  updatedAt: string;
};

const DRAFT_PREFIX = 'webui-blueprint-draft:v1';

const buildDraftKey = (sessionKind: BlueprintSessionKind, sessionId: string) =>
  `${DRAFT_PREFIX}:${sessionKind}:${sessionId}`;

export const loadBlueprintDraft = (
  sessionKind: BlueprintSessionKind,
  sessionId: string,
  blueprintId: string
): BlueprintNode | null => {
  if (typeof localStorage === 'undefined' || !sessionId || !blueprintId) return null;
  const raw = localStorage.getItem(buildDraftKey(sessionKind, sessionId));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as BlueprintDraft;
    if (parsed.blueprintId !== blueprintId) return null;
    if (!parsed.blueprint || typeof parsed.blueprint !== 'object') return null;
    return parsed.blueprint;
  } catch {
    return null;
  }
};

export const saveBlueprintDraft = (
  sessionKind: BlueprintSessionKind,
  sessionId: string,
  blueprintId: string,
  blueprint: BlueprintNode
): void => {
  if (typeof localStorage === 'undefined' || !sessionId || !blueprintId) return;
  const draft: BlueprintDraft = {
    blueprintId,
    blueprint,
    updatedAt: new Date().toISOString()
  };
  localStorage.setItem(buildDraftKey(sessionKind, sessionId), JSON.stringify(draft));
};

export const clearBlueprintDraft = (
  sessionKind: BlueprintSessionKind,
  sessionId: string,
  blueprintId?: string
): void => {
  if (typeof localStorage === 'undefined' || !sessionId) return;
  const key = buildDraftKey(sessionKind, sessionId);
  if (!blueprintId) {
    localStorage.removeItem(key);
    return;
  }
  const raw = localStorage.getItem(key);
  if (!raw) return;
  try {
    const parsed = JSON.parse(raw) as BlueprintDraft;
    if (parsed.blueprintId !== blueprintId) return;
    localStorage.removeItem(key);
  } catch {
    localStorage.removeItem(key);
  }
};
