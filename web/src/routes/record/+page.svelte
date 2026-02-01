<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';

  type DatasetSummary = {
    id: string;
    name?: string;
    profile_instance_id?: string;
    dataset_type?: string;
    created_at?: string;
    size_bytes?: number;
  };

  type DatasetListResponse = {
    datasets?: DatasetSummary[];
    total?: number;
  };

  const datasetsQuery = createQuery<DatasetListResponse>({
    queryKey: ['datasets', 'recorded'],
    queryFn: () => api.storage.datasets()
  });

  $: recordedDatasets =
    $datasetsQuery.data?.datasets?.filter(
      (dataset) => !dataset.dataset_type || dataset.dataset_type === 'recorded'
    ) ?? [];

</script>

<section class="card-strong p-8">
  <p class="section-title">Record</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データ録画</h1>
      <p class="mt-2 text-sm text-slate-600">録画セッションの状況を表示します。</p>
    </div>
    <Button.Root class="btn-primary" href="/record/new">新規録画を開始</Button.Root>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">録画一覧</h2>
    <Button.Root class="btn-ghost">更新</Button.Root>
  </div>
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="pb-3">データセットID</th>
          <th class="pb-3">プロフィール</th>
          <th class="pb-3">サイズ</th>
          <th class="pb-3">作成日時</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $datasetsQuery.isLoading}
          <tr><td class="py-3" colspan="4">読み込み中...</td></tr>
        {:else if recordedDatasets.length}
          {#each recordedDatasets as dataset}
            <tr class="border-t border-slate-200/60">
              <td class="py-3">{dataset.name ?? dataset.id}</td>
              <td class="py-3">{dataset.profile_instance_id ?? '-'}</td>
              <td class="py-3">{formatBytes(dataset.size_bytes ?? 0)}</td>
              <td class="py-3">{formatDate(dataset.created_at)}</td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="4">録画がありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
</section>
