<script lang="ts">
  import { Button } from 'bits-ui';
  import { derived } from 'svelte/store';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';

  type DatasetInfo = {
    id: string;
    name?: string;
    project_id?: string;
    dataset_type?: string;
    status?: string;
    size_bytes?: number;
    episode_count?: number;
    created_at?: string;
    updated_at?: string;
  };

  type DatasetListResponse = {
    datasets?: DatasetInfo[];
    total?: number;
  };

  type DatasetMergeResponse = {
    dataset_id?: string;
  };

  $: datasetId = $page.params.datasetId;

  const queryClient = useQueryClient();

  const datasetQuery = createQuery<DatasetInfo>(
    derived(page, ($page) => {
      const currentId = $page.params.datasetId;
      return {
        queryKey: ['storage', 'dataset', currentId],
        queryFn: () => api.storage.dataset(currentId) as Promise<DatasetInfo>,
        enabled: Boolean(currentId)
      };
    })
  );

  const candidatesQuery = createQuery<DatasetListResponse>(
    derived(datasetQuery, ($datasetQuery) => {
      const currentProjectId = $datasetQuery.data?.project_id;
      return {
        queryKey: ['storage', 'datasets', 'project', currentProjectId],
        queryFn: () => api.storage.datasets(currentProjectId) as Promise<DatasetListResponse>,
        enabled: Boolean(currentProjectId)
      };
    })
  );

  $: dataset = $datasetQuery.data;
  $: projectId = dataset?.project_id ?? '';
  $: isArchived = dataset?.status === 'archived';

  $: candidates = ($candidatesQuery.data?.datasets ?? [])
    .filter((item) => item.project_id === projectId)
    .filter((item) => item.status === 'active' && item.id !== datasetId);

  let mergeSelection: string[] = [];
  let mergeName = '';
  let actionMessage = '';
  let actionError = '';
  let actionLoading = false;

  $: mergeDefaultName = datasetId
    ? `${datasetId.split('/').pop() ?? 'dataset'}_merged`
    : '';
  $: canMerge = !isArchived && mergeSelection.length > 0 && !actionLoading;

  const refetchDataset = async () => {
    if (!datasetId) return;
    await queryClient.invalidateQueries({ queryKey: ['storage', 'dataset', datasetId] });
  };

  const refetchCandidates = async () => {
    if (!projectId) return;
    await queryClient.invalidateQueries({
      queryKey: ['storage', 'datasets', 'project', projectId]
    });
  };

  async function handleArchive() {
    actionMessage = '';
    actionError = '';

    if (!datasetId) return;
    const confirmed = confirm(`${datasetId} をアーカイブしますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      await api.storage.archiveDataset(datasetId);
      await refetchDataset();
      actionMessage = 'アーカイブしました。';
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleRestore() {
    actionMessage = '';
    actionError = '';

    if (!datasetId) return;
    const confirmed = confirm(`${datasetId} を復元しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      await api.storage.restoreDataset(datasetId);
      await refetchDataset();
      actionMessage = '復元しました。';
    } catch (err) {
      actionError = err instanceof Error ? err.message : '復元に失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleMerge() {
    actionMessage = '';
    actionError = '';

    if (!datasetId || !projectId) return;
    if (!mergeSelection.length) {
      actionError = 'マージ対象を選択してください。';
      return;
    }

    const datasetName = mergeName.trim() || mergeDefaultName;
    if (!datasetName) {
      actionError = '新しいデータセット名を入力してください。';
      return;
    }

    const confirmed = confirm(
      `${mergeSelection.length + 1}件を ${projectId}/${datasetName} にマージしますか？`
    );
    if (!confirmed) return;

    actionLoading = true;
    try {
      const result = await api.storage.mergeDatasets({
        project_id: projectId,
        dataset_name: datasetName,
        source_dataset_ids: [datasetId, ...mergeSelection]
      }) as DatasetMergeResponse;
      actionMessage = `マージ完了: ${result.dataset_id}`;
      mergeSelection = [];
      mergeName = '';
      await refetchDataset();
      await refetchCandidates();
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'マージに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データセット詳細</h1>
      <p class="mt-2 text-sm text-slate-600">データセットの状態と操作を確認します。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage/datasets">一覧へ戻る</Button.Root>
      <button class="btn-ghost" type="button" on:click={refetchDataset}>更新</button>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">基本情報</h2>
  </div>
  {#if $datasetQuery.isLoading}
    <p class="mt-4 text-sm text-slate-600">読み込み中...</p>
  {:else if dataset}
    <div class="mt-4 grid gap-4 text-sm text-slate-600 lg:grid-cols-2">
      <div>
        <p class="label">ID</p>
        <p class="text-base font-semibold text-slate-800">{dataset.id}</p>
      </div>
      <div>
        <p class="label">プロジェクト</p>
        <p class="text-base font-semibold text-slate-800">{dataset.project_id}</p>
      </div>
      <div>
        <p class="label">タイプ</p>
        <p class="text-base font-semibold text-slate-800">{dataset.dataset_type}</p>
      </div>
      <div>
        <p class="label">状態</p>
        <p class="text-base font-semibold text-slate-800">{dataset.status}</p>
      </div>
      <div>
        <p class="label">サイズ</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes(dataset.size_bytes)}</p>
      </div>
      <div>
        <p class="label">エピソード数</p>
        <p class="text-base font-semibold text-slate-800">{dataset.episode_count ?? 0}</p>
      </div>
      <div>
        <p class="label">作成日時</p>
        <p class="text-base font-semibold text-slate-800">{formatDate(dataset.created_at)}</p>
      </div>
      <div>
        <p class="label">更新日時</p>
        <p class="text-base font-semibold text-slate-800">{formatDate(dataset.updated_at)}</p>
      </div>
    </div>
    <div class="mt-6 flex flex-wrap gap-2">
      {#if isArchived}
        <button
          class={`btn-primary ${actionLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
          type="button"
          disabled={actionLoading}
          on:click={handleRestore}
        >
          復元
        </button>
      {:else}
        <button
          class={`btn-ghost ${actionLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
          type="button"
          disabled={actionLoading}
          on:click={handleArchive}
        >
          アーカイブ
        </button>
      {/if}
      <button class="btn-ghost" type="button" on:click={() => goto('/storage/archive')}>アーカイブ一覧</button>
    </div>
  {:else}
    <p class="mt-4 text-sm text-slate-600">データセットが見つかりません。</p>
  {/if}
  {#if actionMessage}
    <p class="mt-4 text-sm text-emerald-600">{actionMessage}</p>
  {/if}
  {#if actionError}
    <p class="mt-2 text-sm text-rose-600">{actionError}</p>
  {/if}
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">マージ</h2>
    <button class="btn-ghost" type="button" on:click={refetchCandidates}>候補を更新</button>
  </div>
  <p class="mt-2 text-sm text-slate-600">同一プロジェクトの他データセットと統合できます。</p>
  {#if isArchived}
    <p class="mt-4 text-sm text-rose-600">アーカイブ中のデータセットはマージできません。</p>
  {:else if $candidatesQuery.isLoading}
    <p class="mt-4 text-sm text-slate-600">候補を読み込み中...</p>
  {:else if candidates.length}
    <div class="mt-4 grid gap-2">
      {#each candidates as candidate}
        <label class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-2 text-sm text-slate-600">
          <div class="flex items-center gap-3">
            <input
              type="checkbox"
              class="h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
              bind:group={mergeSelection}
              value={candidate.id}
            />
            <span class="font-semibold text-slate-800">{candidate.id}</span>
          </div>
          <span class="text-xs text-slate-500">{formatBytes(candidate.size_bytes ?? 0)}</span>
        </label>
      {/each}
    </div>
    <div class="mt-4">
      <label class="label" for="merge-name-detail">新しいデータセット名</label>
      <input
        class="input mt-2"
        id="merge-name-detail"
        placeholder={mergeDefaultName || 'dataset_name'}
        bind:value={mergeName}
      />
    </div>
    <div class="mt-4">
      <button
        class={`btn-primary ${canMerge ? '' : 'opacity-50 cursor-not-allowed'}`}
        type="button"
        disabled={!canMerge}
        on:click={handleMerge}
      >
        マージ実行
      </button>
    </div>
  {:else}
    <p class="mt-4 text-sm text-slate-600">マージ可能なデータセットがありません。</p>
  {/if}
</section>
