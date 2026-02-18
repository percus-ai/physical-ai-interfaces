<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';

  type DatasetSummary = {
    id: string;
    name?: string;
    profile_name?: string;
    size_bytes?: number;
    episode_count?: number;
    status?: string;
    created_at?: string;
  };

  type DatasetListResponse = {
    datasets?: DatasetSummary[];
    total?: number;
  };

  type DatasetMergeResponse = {
    dataset_id?: string;
  };

  const datasetsQuery = createQuery<DatasetListResponse>({
    queryKey: ['storage', 'datasets', 'manage'],
    queryFn: () => api.storage.datasets()
  });

  const queryClient = useQueryClient();

  let selectedIds = $state<string[]>([]);
  let mergeName = $state('');
  let actionMessage = $state('');
  let actionError = $state('');
  let actionLoading = $state(false);

  const datasets = $derived($datasetsQuery.data?.datasets ?? []);
  const selectedDatasets = $derived(datasets.filter((dataset) => selectedIds.includes(dataset.id)));
  const profileNames = $derived(
    Array.from(
      new Set(selectedDatasets.map((dataset) => dataset.profile_name).filter(Boolean))
    )
  );
  const profileMismatch = $derived(profileNames.length > 1);
  const profileName = $derived(profileNames.length === 1 ? profileNames[0] : '');
  const mergeDefaultName = $derived(
    selectedDatasets.length
      ? `${selectedDatasets[0].name ?? selectedDatasets[0].id}_merged`
      : ''
  );
  const canMerge = $derived(selectedIds.length >= 2 && !profileMismatch && !actionLoading);
  const canArchive = $derived(selectedIds.length > 0 && !actionLoading);
  const canReupload = $derived(selectedIds.length > 0 && !actionLoading);

  const refetchDatasets = async () => {
    await queryClient.invalidateQueries({ queryKey: ['storage', 'datasets', 'manage'] });
  };

  const displayDatasetLabel = (dataset: DatasetSummary) => dataset.name ?? dataset.id;

  async function handleMerge() {
    actionMessage = '';
    actionError = '';

    if (selectedIds.length < 2) {
      actionError = '2件以上のデータセットを選択してください。';
      return;
    }
    if (profileMismatch || !profileName) {
      actionError = '同一プロファイルのデータセットのみマージできます。';
      return;
    }

    const datasetName = mergeName.trim() || mergeDefaultName;
    if (!datasetName) {
      actionError = '新しいデータセット名を入力してください。';
      return;
    }

    const confirmed = confirm(`${selectedIds.length}件のデータセットを ${datasetName} にマージしますか？`);
    if (!confirmed) return;

    actionLoading = true;
    const sourceIds = [...selectedIds];

    try {
      const result = await api.storage.mergeDatasets({
        dataset_name: datasetName,
        source_dataset_ids: sourceIds
      }) as DatasetMergeResponse;
      actionMessage = `マージ完了: ${result.dataset_id}`;
      mergeName = '';
      selectedIds = [];
      await refetchDatasets();
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'マージに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleArchiveSelected() {
    actionMessage = '';
    actionError = '';

    if (!selectedIds.length) {
      actionError = 'アーカイブ対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${selectedIds.length}件をアーカイブしますか？`);
    if (!confirmed) return;

    actionLoading = true;
    const ids = [...selectedIds];

    try {
      const results = await Promise.allSettled(ids.map((id) => api.storage.archiveDataset(id)));
      const failed = results.filter((result) => result.status === 'rejected');
      if (failed.length) {
        actionError = `アーカイブに失敗しました: ${failed.length}件`;
      } else {
        actionMessage = `アーカイブ完了: ${ids.length}件`;
      }
      selectedIds = [];
      await refetchDatasets();
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleReuploadSelected() {
    actionMessage = '';
    actionError = '';

    if (!selectedIds.length) {
      actionError = '再アップロード対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${selectedIds.length}件をR2へ再アップロードしますか？`);
    if (!confirmed) return;

    actionLoading = true;
    const ids = [...selectedIds];

    try {
      const results = await Promise.allSettled(ids.map((id) => api.storage.reuploadDataset(id)));
      const failed = results.filter((result) => result.status === 'rejected');
      if (failed.length) {
        actionError = `再アップロードに失敗しました: ${failed.length}件`;
      } else {
        actionMessage = `再アップロード完了: ${ids.length}件`;
      }
      await refetchDatasets();
    } catch (err) {
      actionError = err instanceof Error ? err.message : '再アップロードに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データセット管理</h1>
      <p class="mt-2 text-sm text-slate-600">アクティブなデータセットを一覧で確認できます。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage">戻る</Button.Root>
      <button class="btn-ghost" type="button" onclick={refetchDatasets}>更新</button>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <h2 class="text-xl font-semibold text-slate-900">データセット一覧</h2>
    <p class="text-xs text-slate-500">選択して一括操作が可能です。</p>
  </div>
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="pb-3"></th>
          <th class="pb-3">ID</th>
          <th class="pb-3">プロファイル</th>
          <th class="pb-3">サイズ</th>
          <th class="pb-3">エピソード</th>
          <th class="pb-3">状態</th>
          <th class="pb-3">作成日時</th>
          <th class="pb-3"></th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $datasetsQuery.isLoading}
          <tr><td class="py-3" colspan="8">読み込み中...</td></tr>
        {:else if datasets.length}
          {#each datasets as dataset}
            <tr class="border-t border-slate-200/60">
              <td class="py-3">
                <input
                  type="checkbox"
                  class="h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
                  bind:group={selectedIds}
                  value={dataset.id}
                />
              </td>
              <td class="py-3 font-semibold text-slate-800">
                <span class="block max-w-[25ch] truncate" title={dataset.id}>
                  {displayDatasetLabel(dataset)}
                </span>
              </td>
              <td class="py-3">{dataset.profile_name ?? '-'}</td>
              <td class="py-3">{formatBytes(dataset.size_bytes ?? 0)}</td>
              <td class="py-3">{dataset.episode_count ?? 0}</td>
              <td class="py-3"><span class="chip">{dataset.status}</span></td>
              <td class="py-3">{formatDate(dataset.created_at)}</td>
              <td class="py-3 text-right">
                <Button.Root class="btn-ghost" href={`/storage/datasets/${dataset.id}`}>詳細</Button.Root>
              </td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="8">データセットがありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div>
      <h2 class="text-xl font-semibold text-slate-900">一括操作</h2>
      <p class="text-xs text-slate-500">選択済み: {selectedIds.length} 件</p>
    </div>
  </div>
  <div class="mt-4 grid gap-4 lg:grid-cols-[1.2fr_1fr]">
    <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
      <p class="text-sm font-semibold text-slate-800">マージ</p>
      <p class="mt-1 text-xs text-slate-500">
        同一プロジェクトのデータセットをまとめて新規作成します。
      </p>
      <div class="mt-3">
        <label class="label" for="merge-name">新しいデータセット名</label>
        <input
          class="input mt-2"
          id="merge-name"
          placeholder={mergeDefaultName || 'dataset_name'}
          bind:value={mergeName}
        />
        {#if profileMismatch}
          <p class="mt-2 text-xs text-rose-500">プロファイルが一致しません。</p>
        {:else if profileName}
          <p class="mt-2 text-xs text-slate-500">profile: {profileName}</p>
        {/if}
      </div>
      <div class="mt-4">
      <button
        class={`btn-primary ${canMerge ? '' : 'opacity-50 cursor-not-allowed'}`}
        type="button"
        disabled={!canMerge}
        onclick={handleMerge}
      >
        マージ実行
      </button>
    </div>
  </div>
  <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
    <p class="text-sm font-semibold text-slate-800">再アップロード</p>
    <p class="mt-1 text-xs text-slate-500">選択済みデータセットをR2へ再アップロードします。</p>
    <div class="mt-4">
      <button
        class={`btn-primary ${canReupload ? '' : 'opacity-50 cursor-not-allowed'}`}
        type="button"
        disabled={!canReupload}
        onclick={handleReuploadSelected}
      >
        再アップロード
      </button>
    </div>
  </div>
  <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
    <p class="text-sm font-semibold text-slate-800">アーカイブ</p>
    <p class="mt-1 text-xs text-slate-500">選択済みデータセットをアーカイブに移動します。</p>
    <div class="mt-4">
      <button
        class={`btn-ghost ${canArchive ? '' : 'opacity-50 cursor-not-allowed'}`}
        type="button"
        disabled={!canArchive}
        onclick={handleArchiveSelected}
      >
        アーカイブ
      </button>
    </div>
  </div>
  </div>
  {#if actionMessage}
    <p class="mt-4 text-sm text-emerald-600">{actionMessage}</p>
  {/if}
  {#if actionError}
    <p class="mt-2 text-sm text-rose-600">{actionError}</p>
  {/if}
</section>
