<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';

  type ModelSummary = {
    id: string;
    name?: string;
    profile_name?: string;
    policy_type?: string;
    dataset_id?: string;
    size_bytes?: number;
    is_local?: boolean;
    status?: string;
    created_at?: string;
  };

  type ModelListResponse = {
    models?: ModelSummary[];
    total?: number;
  };

  type DatasetSummary = {
    id: string;
    name?: string;
  };

  type DatasetListResponse = {
    datasets?: DatasetSummary[];
    total?: number;
  };

  type ModelSyncStatus = {
    active?: boolean;
    model_id?: string;
    status?: string;
    message?: string;
    progress_percent?: number;
  };

  type InferenceRunnerStatusResponse = {
    model_sync?: ModelSyncStatus;
  };

  const modelsQuery = createQuery<ModelListResponse>({
    queryKey: ['storage', 'models', 'manage'],
    queryFn: () => api.storage.models()
  });

  const datasetsQuery = createQuery<DatasetListResponse>({
    queryKey: ['storage', 'datasets', 'lookup'],
    queryFn: () => api.storage.datasets()
  });

  const models = $derived($modelsQuery.data?.models ?? []);
  const datasetMap = $derived(
    new Map(
      ($datasetsQuery.data?.datasets ?? []).map((dataset) => [
        dataset.id,
        dataset.name ?? dataset.id
      ])
    )
  );

  const displayModelLabel = (model: ModelSummary) => model.name ?? model.id;

  let syncingModelIds = $state<string[]>([]);
  let syncAllPending = $state(false);
  let syncMessage = $state('');
  let syncError = $state('');
  let modelSyncStatus = $state<ModelSyncStatus | null>(null);

  const syncPending = $derived(syncAllPending || syncingModelIds.length > 0);
  const activeSyncModelId = $derived(
    modelSyncStatus?.active ? String(modelSyncStatus.model_id ?? '') : ''
  );
  const activeSyncProgress = $derived(
    Math.min(100, Math.max(0, Number(modelSyncStatus?.progress_percent ?? 0)))
  );

  const isModelSyncing = (modelId: string) => syncingModelIds.includes(modelId);

  const refetchModels = async () => {
    await $modelsQuery?.refetch?.();
  };

  const handleSyncModel = async (modelId: string) => {
    if (!modelId || syncAllPending || isModelSyncing(modelId)) return;
    syncMessage = '';
    syncError = '';
    syncingModelIds = [...syncingModelIds, modelId];
    try {
      const response = await api.storage.syncModel(modelId);
      if (response.result.success) {
        syncMessage = response.result.skipped
          ? `${modelId} はローカルキャッシュを利用しました。`
          : `${modelId} を同期しました。`;
      } else {
        syncError = `${modelId} の同期に失敗しました: ${response.result.message}`;
      }
      await refetchModels();
    } catch (err) {
      syncError = err instanceof Error ? err.message : 'モデル同期に失敗しました。';
    } finally {
      syncingModelIds = syncingModelIds.filter((id) => id !== modelId);
    }
  };

  const handleSyncAll = async () => {
    if (syncPending || !models.length) return;
    syncMessage = '';
    syncError = '';
    syncAllPending = true;
    let succeeded = 0;
    let failed = 0;
    const failedIds: string[] = [];
    try {
      for (const model of models) {
        syncingModelIds = [model.id];
        try {
          const response = await api.storage.syncModel(model.id);
          if (response.result.success) {
            succeeded += 1;
          } else {
            failed += 1;
            failedIds.push(model.id);
          }
        } catch {
          failed += 1;
          failedIds.push(model.id);
        } finally {
          syncingModelIds = [];
        }
      }
      syncMessage = `同期完了: 成功 ${succeeded} / 全体 ${models.length}`;
      if (failed > 0) {
        const preview = failedIds.slice(0, 5).join(', ');
        const suffix = failedIds.length > 5 ? ' ...' : '';
        syncError = `失敗 ${failed} 件: ${preview}${suffix}`;
      }
      await refetchModels();
    } catch (err) {
      syncError = err instanceof Error ? err.message : '全モデル同期に失敗しました。';
    } finally {
      syncingModelIds = [];
      syncAllPending = false;
    }
  };

  $effect(() => {
    if (!syncPending) {
      modelSyncStatus = null;
      return;
    }

    let cancelled = false;
    const pollStatus = async () => {
      try {
        const payload = (await api.inference.runnerStatus()) as InferenceRunnerStatusResponse;
        if (cancelled) return;
        modelSyncStatus = payload.model_sync ?? null;
      } catch {
        if (cancelled) return;
      }
    };

    void pollStatus();
    const timer = setInterval(() => {
      void pollStatus();
    }, 500);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">モデル管理</h1>
      <p class="mt-2 text-sm text-slate-600">アクティブなモデルを一覧で確認できます。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage">ビューに戻る</Button.Root>
      <button class="btn-ghost" type="button" onclick={handleSyncAll} disabled={syncPending || !models.length}>
        {syncAllPending ? '全て同期中...' : '全て同期'}
      </button>
      <button class="btn-ghost" type="button" onclick={refetchModels} disabled={syncPending}>
        更新
      </button>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">モデル一覧</h2>
  </div>
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="pb-3">ID</th>
          <th class="pb-3">プロファイル</th>
          <th class="pb-3">ポリシー</th>
          <th class="pb-3">データセット</th>
          <th class="pb-3">サイズ</th>
          <th class="pb-3">状態</th>
          <th class="pb-3">作成日時</th>
          <th class="pb-3">同期</th>
          <th class="pb-3">詳細</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $modelsQuery.isLoading}
          <tr><td class="py-3" colspan="9">読み込み中...</td></tr>
        {:else if models.length}
          {#each models as model}
            <tr class="border-t border-slate-200/60">
              <td class="py-3 font-semibold text-slate-800">
                <span class="block max-w-[25ch] truncate" title={model.id}>
                  {displayModelLabel(model)}
                </span>
              </td>
              <td class="py-3">{model.profile_name ?? '-'}</td>
              <td class="py-3">{model.policy_type ?? '-'}</td>
              <td class="py-3">
                {#if model.dataset_id}
                  <a
                    class="text-brand hover:underline"
                    href={`/storage/datasets/${model.dataset_id}`}
                    title={datasetMap.get(model.dataset_id) ?? model.dataset_id}
                  >
                    詳細
                  </a>
                {:else}
                  -
                {/if}
              </td>
              <td class="py-3">{formatBytes(model.size_bytes ?? 0)}</td>
              <td class="py-3"><span class="chip">{model.status}</span></td>
              <td class="py-3">{formatDate(model.created_at)}</td>
              <td class="py-3">
                <button
                  class="btn-ghost"
                  type="button"
                  onclick={() => handleSyncModel(model.id)}
                  disabled={syncPending || isModelSyncing(model.id)}
                >
                  {isModelSyncing(model.id) ? '同期中...' : model.is_local ? '同期済' : '同期'}
                </button>
                {#if activeSyncModelId === model.id}
                  <div class="mt-2 max-w-[220px]">
                    <div class="h-1.5 overflow-hidden rounded-full bg-slate-200">
                      <div
                        class="h-full rounded-full bg-brand transition-all duration-200"
                        style={`width: ${activeSyncProgress}%;`}
                      ></div>
                    </div>
                    <p class="mt-1 text-xs text-slate-500">
                      {Math.round(activeSyncProgress)}% {modelSyncStatus?.message ?? '同期中...'}
                    </p>
                  </div>
                {/if}
              </td>
              <td class="py-3 text-right">
                <Button.Root class="btn-ghost" href={`/storage/models/${model.id}`}>詳細</Button.Root>
              </td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="9">モデルがありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
  {#if syncMessage}
    <p class="mt-4 text-sm text-emerald-600">{syncMessage}</p>
  {/if}
  {#if syncError}
    <p class="mt-2 text-sm text-rose-600">{syncError}</p>
  {/if}
</section>
