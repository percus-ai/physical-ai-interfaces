import { api } from '$lib/api/client';
import { clearBlueprintDraft, type BlueprintSessionKind } from '$lib/blueprints/draftStorage';
import type { BlueprintNode } from '$lib/recording/blueprint';

export type WebuiBlueprintSummary = {
  id: string;
  name: string;
  created_at?: string;
  updated_at?: string;
};

export type WebuiBlueprintDetail = WebuiBlueprintSummary & {
  blueprint: BlueprintNode;
};

type WebuiBlueprintResolveResponse = {
  blueprint: WebuiBlueprintDetail;
  resolved_by: 'binding' | 'last_used' | 'latest' | 'default_created';
};

type WebuiBlueprintBindResponse = {
  blueprint: WebuiBlueprintDetail;
};

type WebuiBlueprintDeleteResponse = {
  success?: boolean;
  replacement_blueprint_id?: string | null;
  rebound_session_count?: number;
};

type WebuiBlueprintListResponse = {
  blueprints?: WebuiBlueprintSummary[];
  last_used_blueprint_id?: string | null;
};

type BlueprintManagerOptions = {
  getSessionId: () => string;
  getSessionKind: () => BlueprintSessionKind | '';
  getActiveBlueprintId: () => string;
  getActiveBlueprintName: () => string;
  getBlueprint: () => BlueprintNode;
  setSavedBlueprints: (items: WebuiBlueprintSummary[]) => void;
  setBusy: (value: boolean) => void;
  setActionPending: (value: boolean) => void;
  setError: (message: string) => void;
  setNotice: (message: string) => void;
  applyBlueprintDetail: (
    detail: WebuiBlueprintDetail,
    useDraft: boolean,
    kind: BlueprintSessionKind
  ) => void;
  confirmDelete?: (message: string) => boolean;
};

const toErrorMessage = (error: unknown, fallback: string) =>
  error instanceof Error ? error.message : fallback;

export const createBlueprintManager = (options: BlueprintManagerOptions) => {
  const resetMessages = () => {
    options.setError('');
    options.setNotice('');
  };

  const refreshBlueprintList = async () => {
    const response = (await api.webuiBlueprints.list()) as WebuiBlueprintListResponse;
    options.setSavedBlueprints(response.blueprints ?? []);
  };

  const resolveSessionBlueprint = async () => {
    const sessionId = options.getSessionId();
    const sessionKind = options.getSessionKind();
    if (!sessionId || !sessionKind) return;

    options.setBusy(true);
    resetMessages();
    try {
      const resolved = (await api.webuiBlueprints.resolveSession({
        session_kind: sessionKind,
        session_id: sessionId
      })) as WebuiBlueprintResolveResponse;
      options.applyBlueprintDetail(resolved.blueprint, true, sessionKind);
      await refreshBlueprintList();
      if (resolved.resolved_by === 'default_created') {
        options.setNotice('デフォルトのブループリントを作成して適用しました。');
      }
    } catch (error) {
      options.setError(toErrorMessage(error, 'ブループリントの読み込みに失敗しました。'));
    } finally {
      options.setBusy(false);
    }
  };

  const openBlueprint = async (blueprintId: string) => {
    const sessionId = options.getSessionId();
    const sessionKind = options.getSessionKind();
    const activeBlueprintId = options.getActiveBlueprintId();
    if (!sessionId || !sessionKind || !blueprintId || blueprintId === activeBlueprintId) return;

    options.setActionPending(true);
    resetMessages();
    try {
      const response = (await api.webuiBlueprints.bindSession({
        session_kind: sessionKind,
        session_id: sessionId,
        blueprint_id: blueprintId
      })) as WebuiBlueprintBindResponse;
      options.applyBlueprintDetail(response.blueprint, true, sessionKind);
      await refreshBlueprintList();
    } catch (error) {
      options.setError(toErrorMessage(error, 'ブループリントの切り替えに失敗しました。'));
    } finally {
      options.setActionPending(false);
    }
  };

  const saveBlueprint = async () => {
    const sessionId = options.getSessionId();
    const sessionKind = options.getSessionKind();
    const activeBlueprintId = options.getActiveBlueprintId();
    if (!sessionId || !sessionKind || !activeBlueprintId) return;

    const nextName = options.getActiveBlueprintName().trim();
    if (!nextName) {
      options.setError('ブループリント名を入力してください。');
      return;
    }

    options.setActionPending(true);
    resetMessages();
    try {
      const response = (await api.webuiBlueprints.update(activeBlueprintId, {
        name: nextName,
        blueprint: options.getBlueprint() as unknown as Record<string, unknown>
      })) as WebuiBlueprintDetail;
      options.applyBlueprintDetail(response, false, sessionKind);
      clearBlueprintDraft(sessionKind, sessionId, activeBlueprintId);
      await refreshBlueprintList();
      options.setNotice('ブループリントを保存しました。');
    } catch (error) {
      options.setError(toErrorMessage(error, 'ブループリントの保存に失敗しました。'));
    } finally {
      options.setActionPending(false);
    }
  };

  const duplicateBlueprint = async () => {
    const sessionId = options.getSessionId();
    const sessionKind = options.getSessionKind();
    if (!sessionId || !sessionKind) return;

    const baseName = options.getActiveBlueprintName().trim() || 'Blueprint';
    options.setActionPending(true);
    resetMessages();
    try {
      const created = (await api.webuiBlueprints.create({
        name: `${baseName} (copy)`,
        blueprint: options.getBlueprint() as unknown as Record<string, unknown>
      })) as WebuiBlueprintDetail;

      const bound = (await api.webuiBlueprints.bindSession({
        session_kind: sessionKind,
        session_id: sessionId,
        blueprint_id: created.id
      })) as WebuiBlueprintBindResponse;

      options.applyBlueprintDetail(bound.blueprint, false, sessionKind);
      clearBlueprintDraft(sessionKind, sessionId, created.id);
      await refreshBlueprintList();
      options.setNotice('複製したブループリントを開きました。');
    } catch (error) {
      options.setError(toErrorMessage(error, 'ブループリントの複製に失敗しました。'));
    } finally {
      options.setActionPending(false);
    }
  };

  const deleteBlueprint = async () => {
    const sessionId = options.getSessionId();
    const sessionKind = options.getSessionKind();
    const activeBlueprintId = options.getActiveBlueprintId();
    if (!sessionId || !sessionKind || !activeBlueprintId) return;

    const confirmFn =
      options.confirmDelete ??
      ((message: string) => {
        return confirm(message);
      });
    if (!confirmFn('現在のブループリントを削除しますか？')) return;

    options.setActionPending(true);
    resetMessages();
    try {
      const response = (await api.webuiBlueprints.delete(activeBlueprintId)) as WebuiBlueprintDeleteResponse;
      clearBlueprintDraft(sessionKind, sessionId, activeBlueprintId);
      await resolveSessionBlueprint();
      if (response.rebound_session_count && response.rebound_session_count > 0) {
        options.setNotice('参照中セッションを代替ブループリントに切り替えました。');
      } else {
        options.setNotice('ブループリントを削除しました。');
      }
    } catch (error) {
      options.setError(toErrorMessage(error, 'ブループリントの削除に失敗しました。'));
    } finally {
      options.setActionPending(false);
    }
  };

  const resetBlueprint = async () => {
    const sessionId = options.getSessionId();
    const sessionKind = options.getSessionKind();
    const activeBlueprintId = options.getActiveBlueprintId();
    if (!sessionId || !sessionKind || !activeBlueprintId) return;

    options.setActionPending(true);
    resetMessages();
    try {
      const response = (await api.webuiBlueprints.get(activeBlueprintId)) as WebuiBlueprintDetail;
      options.applyBlueprintDetail(response, false, sessionKind);
      clearBlueprintDraft(sessionKind, sessionId, activeBlueprintId);
      options.setNotice('サーバ保存版にリセットしました。');
    } catch (error) {
      options.setError(toErrorMessage(error, 'ブループリントのリセットに失敗しました。'));
    } finally {
      options.setActionPending(false);
    }
  };

  return {
    refreshBlueprintList,
    resolveSessionBlueprint,
    openBlueprint,
    saveBlueprint,
    duplicateBlueprint,
    deleteBlueprint,
    resetBlueprint
  };
};
