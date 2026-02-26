<script lang="ts">
  import { Button } from 'bits-ui';
</script>

<section class="card-strong p-8">
  <p class="section-title">HuggingFace</p>
  <h1 class="mt-2 text-3xl font-semibold text-slate-900">データセットをインポート</h1>
  <p class="mt-2 text-sm text-slate-600">HuggingFace からデータセットを取り込みます。</p>
</section>

<section class="card p-6">
  <div class="grid gap-4 sm:grid-cols-2">
    <div>
      <p class="label">repo_id</p>
      <input class="input mt-2" placeholder="username/dataset" />
    </div>
    <div>
      <p class="label">profile name (optional)</p>
      <input class="input mt-2" placeholder="so101_dual_teleop" />
    </div>
    <div>
      <p class="label">dataset name</p>
      <input class="input mt-2" placeholder="dataset_name" />
    </div>
    <div>
      <p class="label">force overwrite</p>
      <select class="input mt-2">
        <option>false</option>
        <option>true</option>
      </select>
    </div>
  </div>
  <div class="mt-6 flex gap-3">
    <Button.Root class="btn-primary">インポート</Button.Root>
    <Button.Root class="btn-ghost" href="/storage">戻る</Button.Root>
  </div>
</section>
