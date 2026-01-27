<script lang="ts">
  import { Button } from 'bits-ui';
</script>

<section class="card-strong p-8">
  <p class="section-title">Record</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データ録画</h1>
      <p class="mt-2 text-sm text-slate-600">プロジェクト別の録画セッション作成と進行状況を確認。</p>
    </div>
    <Button.Root class="btn-primary">新規録画を開始</Button.Root>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">録画設定</h2>
    <div class="mt-4 grid gap-4 sm:grid-cols-2">
      <div>
        <p class="label">プロジェクト</p>
        <select class="input mt-2">
          <option>0001_black_cube_to_tray</option>
          <option>0002_stack_blocks</option>
          <option>import from YAML</option>
        </select>
      </div>
      <div>
        <p class="label">エピソード数</p>
        <input class="input mt-2" value="1" />
      </div>
      <div>
        <p class="label">エピソード時間 (秒)</p>
        <input class="input mt-2" value="60" />
      </div>
      <div>
        <p class="label">リセット時間 (秒)</p>
        <input class="input mt-2" value="10" />
      </div>
    </div>
    <div class="mt-6 flex flex-wrap gap-3">
      <Button.Root class="btn-primary">録画開始</Button.Root>
      <Button.Root class="btn-ghost">シミュレーション</Button.Root>
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">アップロード状況</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <div>
        <p class="label">現在のファイル</p>
        <p class="text-base font-semibold text-slate-800">episode_0004.mp4</p>
      </div>
      <div>
        <p class="label">転送進行</p>
        <div class="mt-2 h-2 w-full rounded-full bg-slate-200">
          <div class="h-2 w-2/3 rounded-full bg-brand"></div>
        </div>
        <p class="mt-2 text-xs text-slate-500">640MB / 1.0GB</p>
      </div>
      <div>
        <p class="label">ファイル数</p>
        <p class="text-base font-semibold text-slate-800">3 / 12</p>
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
          <th class="pb-3">状態</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        <tr class="border-t border-slate-200/60">
          <td class="py-3">20260126_2032_user1</td>
          <td class="py-3">black_cube_to_tray</td>
          <td class="py-3">12.4 GB</td>
          <td class="py-3"><span class="chip">完了</span></td>
        </tr>
        <tr class="border-t border-slate-200/60">
          <td class="py-3">20260126_1510_user2</td>
          <td class="py-3">stack_blocks</td>
          <td class="py-3">8.9 GB</td>
          <td class="py-3"><span class="chip">アップロード中</span></td>
        </tr>
      </tbody>
    </table>
  </div>
</section>
