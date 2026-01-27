<script lang="ts">
  import { Button } from 'bits-ui';

  const teleopModes = [
    { id: 'simple', name: 'Simple (leader-follower)' },
    { id: 'visual', name: 'Visual (with camera)' },
    { id: 'bimanual', name: 'Bimanual (two arms)' }
  ];
</script>

<section class="card-strong p-8">
  <p class="section-title">Operate</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">テレオペ / 推論</h1>
      <p class="mt-2 text-sm text-slate-600">ローカル・リモートテレオペと推論実行の統合画面。</p>
    </div>
    <div class="flex gap-3">
      <Button.Root class="btn-primary">セッションを開始</Button.Root>
      <Button.Root class="btn-ghost">推論を実行</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.1fr_1fr]">
  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">テレオペレーション</h2>
    <div class="mt-4 grid gap-4 sm:grid-cols-2">
      <div>
        <p class="label">モード</p>
        <div class="mt-2 space-y-2">
          {#each teleopModes as mode}
            <label class="flex items-center gap-2 text-sm text-slate-600">
              <input type="radio" name="teleop-mode" class="accent-brand" />
              {mode.name}
            </label>
          {/each}
        </div>
      </div>
      <div class="space-y-3">
        <div>
          <p class="label">ロボット種別</p>
          <select class="input mt-2">
            <option>SO-101</option>
            <option>SO-100</option>
          </select>
        </div>
        <div>
          <p class="label">FPS</p>
          <input class="input mt-2" value="60" />
        </div>
      </div>
      <div>
        <p class="label">リーダーポート</p>
        <input class="input mt-2" placeholder="/dev/ttyUSB0" />
      </div>
      <div>
        <p class="label">フォロワーポート</p>
        <input class="input mt-2" placeholder="/dev/ttyUSB1" />
      </div>
    </div>
    <div class="mt-6 flex flex-wrap gap-3">
      <Button.Root class="btn-primary">テレオペ開始</Button.Root>
      <Button.Root class="btn-ghost">停止</Button.Root>
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">推論実行</h2>
    <div class="mt-4 space-y-4">
      <div>
        <p class="label">モデル</p>
        <select class="input mt-2">
          <option>lerobot/pi05_base</option>
          <option>lerobot/pi0_base</option>
          <option>custom/your-model</option>
        </select>
      </div>
      <div>
        <p class="label">入力ソース</p>
        <select class="input mt-2">
          <option>カメラ (live)</option>
          <option>録画済みデータ</option>
        </select>
      </div>
      <div>
        <p class="label">セッション名</p>
        <input class="input mt-2" placeholder="inference_session_001" />
      </div>
    </div>
    <div class="mt-6 flex gap-3">
      <Button.Root class="btn-primary">推論開始</Button.Root>
      <Button.Root class="btn-ghost">履歴を見る</Button.Root>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">セッション一覧</h2>
    <Button.Root class="btn-ghost">更新</Button.Root>
  </div>
  <div class="mt-4 space-y-3 text-sm text-slate-600">
    <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
      <span>teleop_20260127_1030</span>
      <span class="chip">実行中</span>
    </div>
    <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
      <span>inference_20260126_2105</span>
      <span class="chip">完了</span>
    </div>
  </div>
</section>
