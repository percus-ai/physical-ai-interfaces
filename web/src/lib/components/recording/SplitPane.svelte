<script lang="ts">
  import { createEventDispatcher, type Snippet } from 'svelte';

  let {
    direction = 'row',
    sizes = [0.5, 0.5],
    min = 0.15,
    editable = true,
    handleSize = 10,
    handleInset = 6,
    handleGutter = 2,
    gapSize = 16,
    first,
    second
  }: {
    direction?: 'row' | 'column';
    sizes?: [number, number];
    min?: number;
    editable?: boolean;
    handleSize?: number;
    handleInset?: number;
    handleGutter?: number;
    gapSize?: number;
    first?: Snippet;
    second?: Snippet;
  } = $props();

  const dispatch = createEventDispatcher<{ resize: { sizes: [number, number] } }>();
  let container: HTMLDivElement | null = null;
  let dragging = false;

  const clamp = (value: number, minValue: number, maxValue: number) =>
    Math.min(Math.max(value, minValue), maxValue);

  const handlePointerDown = (event: PointerEvent) => {
    if (!editable) return;
    if (!container) return;
    dragging = true;
    container.setPointerCapture(event.pointerId);
    document.body.style.userSelect = 'none';
    handlePointerMove(event);
  };

  const handlePointerMove = (event: PointerEvent) => {
    if (!editable) return;
    if (!dragging || !container) return;
    const rect = container.getBoundingClientRect();
    const total = direction === 'row' ? rect.width : rect.height;
    if (total <= 0) return;
    const offset = direction === 'row' ? event.clientX - rect.left : event.clientY - rect.top;
    let ratio = offset / total;
    ratio = clamp(ratio, min, 1 - min);
    dispatch('resize', { sizes: [ratio, 1 - ratio] });
  };

  const handlePointerUp = () => {
    if (!dragging) return;
    dragging = false;
    document.body.style.userSelect = '';
  };
</script>

  <div
    class={`split-pane ${direction}`}
    bind:this={container}
    role="presentation"
    style={`--first-size:${sizes[0]}; --second-size:${sizes[1]}; --handle-size:${editable ? handleSize : gapSize}px; --handle-inset:${handleInset}px; --handle-gutter:${handleGutter}px;`}
    onpointermove={handlePointerMove}
    onpointerup={handlePointerUp}
    onpointerleave={handlePointerUp}
  >
    <div class="pane">
      {@render first?.()}
    </div>
    <div
      class={`handle ${editable ? 'active' : 'hidden'}`}
      role="separator"
      onpointerdown={handlePointerDown}
    >
      <div class="handle-bar"></div>
    </div>
    <div class="pane">
      {@render second?.()}
    </div>
  </div>

<style>
  .split-pane {
    display: grid;
    height: 100%;
    width: 100%;
    gap: 0;
    position: relative;
  }
  .split-pane.row {
    grid-template-columns:
      calc((100% - var(--handle-size, 0px)) * var(--first-size, 0.5))
      var(--handle-size, 0px)
      calc((100% - var(--handle-size, 0px)) * var(--second-size, 0.5));
  }
  .split-pane.column {
    grid-template-rows:
      calc((100% - var(--handle-size, 0px)) * var(--first-size, 0.5))
      var(--handle-size, 0px)
      calc((100% - var(--handle-size, 0px)) * var(--second-size, 0.5));
  }
  .pane {
    min-height: 0;
    min-width: 0;
    overflow: hidden;
  }
  .handle {
    display: flex;
    align-items: stretch;
    justify-content: stretch;
    align-self: stretch;
    justify-self: stretch;
    cursor: col-resize;
    touch-action: none;
    padding: var(--handle-inset) var(--handle-gutter);
    z-index: 1;
  }
  .handle.active {
    background: rgba(148, 163, 184, 0.12);
    border-radius: 999px;
  }
  .handle-bar {
    flex: 1;
    border-radius: 999px;
    min-width: 4px;
    min-height: 4px;
    background: rgba(148, 163, 184, 0.7);
    box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.35);
  }
  .split-pane > .handle {
    cursor: col-resize;
  }
  .split-pane.column > .handle {
    cursor: row-resize;
    padding: var(--handle-gutter) var(--handle-inset);
  }
  .handle.hidden {
    pointer-events: none;
    opacity: 0;
    padding: 0;
  }
</style>
