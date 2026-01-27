<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';

  const projectsQuery = createQuery({
    queryKey: ['projects'],
    queryFn: api.projects.list
  });

  const recordingsQuery = createQuery({
    queryKey: ['recordings'],
    queryFn: api.recording.list
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Record</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データ録画</h1>
      <p class="mt-2 text-sm text-slate-600">プロジェクト一覧と録画セッションの状況を表示します。</p>
    </div>
    <Button.Root class="btn-primary">新規録画を開始</Button.Root>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">プロジェクト一覧</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $projectsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $projectsQuery.data?.projects?.length}
        {#each $projectsQuery.data.projects as project}
          <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <span class="font-semibold text-slate-800">{project}</span>
            <span class="chip">プロジェクト</span>
          </div>
        {/each}
      {:else}
        <p>プロジェクトがありません。</p>
      {/if}
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">録画サマリ</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <div>
        <p class="label">総録画数</p>
        <p class="text-base font-semibold text-slate-800">{$recordingsQuery.data?.total ?? 0}</p>
      </div>
      <div>
        <p class="label">最新録画</p>
        <p class="text-base font-semibold text-slate-800">
          {formatDate($recordingsQuery.data?.recordings?.[0]?.created_at)}
        </p>
      </div>
      <div>
        <p class="label">最新プロジェクト</p>
        <p class="text-base font-semibold text-slate-800">
          {$recordingsQuery.data?.recordings?.[0]?.project_id ?? '-'}
        </p>
      </div>
    </div>
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
          <th class="pb-3">セッション</th>
          <th class="pb-3">プロジェクト</th>
          <th class="pb-3">サイズ</th>
          <th class="pb-3">作成日時</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $recordingsQuery.isLoading}
          <tr><td class="py-3" colspan="4">読み込み中...</td></tr>
        {:else if $recordingsQuery.data?.recordings?.length}
          {#each $recordingsQuery.data.recordings as recording}
            <tr class="border-t border-slate-200/60">
              <td class="py-3">{recording.recording_id}</td>
              <td class="py-3">{recording.project_id}</td>
              <td class="py-3">{formatBytes((recording.size_mb ?? 0) * 1024 * 1024)}</td>
              <td class="py-3">{formatDate(recording.created_at)}</td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="4">録画がありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
</section>
