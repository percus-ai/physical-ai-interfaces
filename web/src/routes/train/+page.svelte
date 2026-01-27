<script lang="ts">
  import { Button } from 'bits-ui';

  const steps = [
    'ポリシー選択',
    '事前学習モデル',
    'データセット選択',
    '学習パラメータ',
    'Verda設定',
    'ジョブ名',
    '確認'
  ];
</script>

<section class="card-strong p-8">
  <p class="section-title">Train</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">モデル学習</h1>
      <p class="mt-2 text-sm text-slate-600">
        新規学習・継続学習ウィザードをWebUIへ移植。CLIと同等のステップ構成。
      </p>
    </div>
    <div class="flex gap-3">
      <Button.Root class="btn-primary">新規学習</Button.Root>
      <Button.Root class="btn-ghost">継続学習</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[280px_1fr]">
  <div class="card p-6">
    <h2 class="text-lg font-semibold text-slate-900">ウィザード</h2>
    <ol class="mt-4 space-y-3 text-sm text-slate-600">
      {#each steps as step, index}
        <li class="flex items-center gap-3">
          <span class="flex h-7 w-7 items-center justify-center rounded-full border border-slate-200 bg-white text-xs font-semibold">
            {index + 1}
          </span>
          <span>{step}</span>
        </li>
      {/each}
    </ol>
    <div class="mt-6 rounded-xl bg-slate-50 p-4 text-xs text-slate-500">
      CLIのデフォルト値 (steps / batch / save_freq) を同じ順序で提示。
    </div>
  </div>

  <div class="space-y-6">
    <div class="card p-6">
      <h3 class="text-lg font-semibold text-slate-900">ポリシー / 事前学習モデル</h3>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <p class="label">ポリシー種別</p>
          <select class="input mt-2">
            <option>π0.5 (Open-World VLA Model)</option>
            <option>π0 (Physical Intelligence)</option>
            <option>ACT</option>
            <option>Diffusion Policy</option>
            <option>GR00T N1.5</option>
            <option>SmolVLA</option>
            <option>VLA-0</option>
          </select>
        </div>
        <div>
          <p class="label">事前学習モデル</p>
          <select class="input mt-2">
            <option>lerobot/pi05_base</option>
            <option>lerobot/pi05_libero</option>
            <option>lerobot/pi0_base</option>
          </select>
        </div>
      </div>
    </div>

    <div class="card p-6">
      <h3 class="text-lg font-semibold text-slate-900">データセット</h3>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <p class="label">プロジェクト</p>
          <select class="input mt-2">
            <option>0001_black_cube_to_tray</option>
            <option>0002_stack_blocks</option>
          </select>
        </div>
        <div>
          <p class="label">セッション</p>
          <select class="input mt-2">
            <option>20260107_180132_watanabe</option>
            <option>20260105_102233_tanaka</option>
          </select>
        </div>
        <div>
          <p class="label">ビデオバックエンド</p>
          <select class="input mt-2">
            <option>torchcodec</option>
            <option>decord</option>
          </select>
        </div>
        <div>
          <p class="label">データセットID</p>
          <input class="input mt-2" placeholder="project/session" />
        </div>
      </div>
    </div>

    <div class="card p-6">
      <h3 class="text-lg font-semibold text-slate-900">学習パラメータ</h3>
      <div class="mt-4 grid gap-4 sm:grid-cols-3">
        <div>
          <p class="label">Steps</p>
          <input class="input mt-2" value="100000" />
        </div>
        <div>
          <p class="label">Batch Size</p>
          <input class="input mt-2" value="32" />
        </div>
        <div>
          <p class="label">Save Freq</p>
          <input class="input mt-2" value="5000" />
        </div>
        <div>
          <p class="label">Log Freq</p>
          <input class="input mt-2" value="200" />
        </div>
        <div>
          <p class="label">Workers</p>
          <input class="input mt-2" value="4" />
        </div>
        <div>
          <p class="label">Validation</p>
          <select class="input mt-2">
            <option>有効</option>
            <option>無効</option>
          </select>
        </div>
      </div>
    </div>

    <div class="card p-6">
      <h3 class="text-lg font-semibold text-slate-900">Verda / 実行環境</h3>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <p class="label">GPUモデル</p>
          <select class="input mt-2">
            <option>H100 (80GB)</option>
            <option>H200 (141GB)</option>
            <option>B200 (180GB)</option>
            <option>B300 (262GB)</option>
            <option>A100 (80GB)</option>
          </select>
        </div>
        <div>
          <p class="label">GPU数</p>
          <select class="input mt-2">
            <option>1</option>
            <option>2</option>
            <option>4</option>
            <option>8</option>
          </select>
        </div>
        <div>
          <p class="label">ストレージ</p>
          <input class="input mt-2" value="200" />
        </div>
        <div>
          <p class="label">Spot</p>
          <select class="input mt-2">
            <option>有効</option>
            <option>無効</option>
          </select>
        </div>
      </div>
    </div>

    <div class="card p-6">
      <h3 class="text-lg font-semibold text-slate-900">ジョブ名</h3>
      <div class="mt-4 flex flex-wrap items-end gap-4">
        <div class="flex-1">
          <p class="label">自動生成</p>
          <input class="input mt-2" value="pi05_a1b2c3_260127_142200" />
        </div>
        <Button.Root class="btn-ghost">再生成</Button.Root>
      </div>
      <div class="mt-6 flex gap-3">
        <Button.Root class="btn-primary">確認へ進む</Button.Root>
        <Button.Root class="btn-ghost">下書き保存</Button.Root>
      </div>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">学習ジョブ一覧</h2>
    <Button.Root class="btn-ghost">更新</Button.Root>
  </div>
  <div class="mt-4 space-y-3 text-sm text-slate-600">
    <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
      <span>pi05_a1b2c3_260109_143052</span>
      <span class="chip">待機</span>
    </div>
    <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
      <span>act_d4e5f6_260108_094512</span>
      <span class="chip">実行中</span>
    </div>
  </div>
</section>
