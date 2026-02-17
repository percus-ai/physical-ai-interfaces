export type ViewNode = {
  id: string;
  type: 'view';
  viewType: string;
  config: Record<string, unknown>;
};

export type SplitNode = {
  id: string;
  type: 'split';
  direction: 'row' | 'column';
  sizes: [number, number];
  children: [BlueprintNode, BlueprintNode];
};

export type TabItem = {
  id: string;
  title: string;
  child: BlueprintNode;
};

export type TabsNode = {
  id: string;
  type: 'tabs';
  activeId: string;
  tabs: TabItem[];
};

export type BlueprintNode = ViewNode | SplitNode | TabsNode;

const createId = () => Math.random().toString(36).slice(2, 10);

export const createViewNode = (viewType = 'placeholder', config: Record<string, unknown> = {}): ViewNode => ({
  id: createId(),
  type: 'view',
  viewType,
  config
});

export const createPlaceholderView = (id?: string): ViewNode => ({
  id: id ?? createId(),
  type: 'view',
  viewType: 'placeholder',
  config: {}
});

export const createSplitNode = (
  direction: 'row' | 'column',
  first: BlueprintNode,
  second: BlueprintNode,
  sizes: [number, number] = [0.5, 0.5]
): SplitNode => ({
  id: createId(),
  type: 'split',
  direction,
  sizes,
  children: [first, second]
});

export const createTabsNode = (tabs: TabItem[], activeId?: string): TabsNode => ({
  id: createId(),
  type: 'tabs',
  activeId: activeId ?? (tabs[0]?.id ?? ''),
  tabs
});

export const createTabItem = (title: string, child: BlueprintNode): TabItem => ({
  id: createId(),
  title,
  child
});

export const findNode = (node: BlueprintNode, id: string): BlueprintNode | null => {
  if (node.id === id) return node;
  if (node.type === 'split') {
    return findNode(node.children[0], id) ?? findNode(node.children[1], id);
  }
  if (node.type === 'tabs') {
    for (const tab of node.tabs) {
      const found = findNode(tab.child, id);
      if (found) return found;
    }
  }
  return null;
};

export const updateNode = (
  node: BlueprintNode,
  id: string,
  updater: (target: BlueprintNode) => BlueprintNode
): BlueprintNode => {
  if (node.id === id) return updater(node);
  if (node.type === 'split') {
    return {
      ...node,
      children: [
        updateNode(node.children[0], id, updater),
        updateNode(node.children[1], id, updater)
      ]
    };
  }
  if (node.type === 'tabs') {
    return {
      ...node,
      tabs: node.tabs.map((tab) => ({
        ...tab,
        child: updateNode(tab.child, id, updater)
      }))
    };
  }
  return node;
};

export const replaceNode = (node: BlueprintNode, id: string, next: BlueprintNode): BlueprintNode =>
  updateNode(node, id, () => next);

export const updateSplitSizes = (node: BlueprintNode, id: string, sizes: [number, number]): BlueprintNode =>
  updateNode(node, id, (target) =>
    target.type === 'split'
      ? {
          ...target,
          sizes
        }
      : target
  );

export const updateSplitDirection = (
  node: BlueprintNode,
  id: string,
  direction: 'row' | 'column'
): BlueprintNode =>
  updateNode(node, id, (target) =>
    target.type === 'split'
      ? {
          ...target,
          direction
        }
      : target
  );

export const updateTabsActive = (node: BlueprintNode, id: string, activeId: string): BlueprintNode =>
  updateNode(node, id, (target) =>
    target.type === 'tabs'
      ? {
          ...target,
          activeId
        }
      : target
  );

export const updateViewType = (node: BlueprintNode, id: string, viewType: string): BlueprintNode =>
  updateNode(node, id, (target) =>
    target.type === 'view'
      ? {
          ...target,
          viewType
        }
      : target
  );

export const updateViewConfig = (
  node: BlueprintNode,
  id: string,
  config: Record<string, unknown>
): BlueprintNode =>
  updateNode(node, id, (target) =>
    target.type === 'view'
      ? {
          ...target,
          config
        }
      : target
  );

export const wrapInSplit = (
  node: BlueprintNode,
  id: string,
  direction: 'row' | 'column'
): BlueprintNode =>
  updateNode(node, id, (target) =>
    createSplitNode(direction, target, createViewNode('placeholder'))
  );

export const wrapInTabs = (node: BlueprintNode, id: string): BlueprintNode =>
  updateNode(node, id, (target) =>
    createTabsNode([
      createTabItem('View', target),
      createTabItem('New', createViewNode('placeholder'))
    ])
  );

export const addTab = (node: BlueprintNode, id: string, title = 'New'): BlueprintNode =>
  updateNode(node, id, (target) => {
    if (target.type !== 'tabs') return target;
    const newTab = createTabItem(title, createViewNode('placeholder'));
    return {
      ...target,
      tabs: [...target.tabs, newTab],
      activeId: newTab.id
    };
  });

export const renameTab = (node: BlueprintNode, id: string, tabId: string, title: string): BlueprintNode =>
  updateNode(node, id, (target) => {
    if (target.type !== 'tabs') return target;
    return {
      ...target,
      tabs: target.tabs.map((tab) => (tab.id === tabId ? { ...tab, title } : tab))
    };
  });

export const removeTab = (node: BlueprintNode, id: string, tabId: string): BlueprintNode =>
  updateNode(node, id, (target) => {
    if (target.type !== 'tabs') return target;
    const nextTabs = target.tabs.filter((tab) => tab.id !== tabId);
    if (nextTabs.length === 0) {
      return target;
    }
    const nextActive = target.activeId === tabId ? nextTabs[0].id : target.activeId;
    return {
      ...target,
      tabs: nextTabs,
      activeId: nextActive
    };
  });

type DeleteResult = { node: BlueprintNode; removed: boolean };

const deleteNodeRecursive = (node: BlueprintNode, id: string): DeleteResult => {
  if (node.id === id) {
    return { node, removed: true };
  }
  if (node.type === 'split') {
    const left = deleteNodeRecursive(node.children[0], id);
    if (left.removed) {
      return { node: node.children[1], removed: false };
    }
    const right = deleteNodeRecursive(node.children[1], id);
    if (right.removed) {
      return { node: node.children[0], removed: false };
    }
    return {
      node: {
        ...node,
        children: [left.node, right.node]
      },
      removed: false
    };
  }
  if (node.type === 'tabs') {
    let removed = false;
    const nextTabs = node.tabs
      .map((tab) => {
        const result = deleteNodeRecursive(tab.child, id);
        if (result.removed) {
          removed = true;
          return null;
        }
        return { ...tab, child: result.node };
      })
      .filter((tab): tab is TabItem => tab !== null);

    if (removed && nextTabs.length === 0) {
      return { node, removed: true };
    }

    const activeExists = nextTabs.some((tab) => tab.id === node.activeId);
    const nextActive = activeExists ? node.activeId : nextTabs[0]?.id ?? '';
    return {
      node: {
        ...node,
        tabs: nextTabs,
        activeId: nextActive
      },
      removed: false
    };
  }
  return { node, removed: false };
};

export const deleteNode = (node: BlueprintNode, id: string): BlueprintNode => {
  const result = deleteNodeRecursive(node, id);
  if (result.removed) {
    return createPlaceholderView(node.id);
  }
  return result.node;
};

export const ensureValidSelection = (node: BlueprintNode, selectedId: string | null): string => {
  if (selectedId && findNode(node, selectedId)) return selectedId;
  return node.id;
};

export const createDefaultBlueprint = (): BlueprintNode =>
  createSplitNode(
    'column',
    createSplitNode(
      'row',
      createSplitNode(
        'column',
        createViewNode('camera', { topic: '' }),
        createViewNode('joint_state', { topic: '' }),
        [0.6, 0.4]
      ),
      createTabsNode([
        createTabItem('Status', createViewNode('status', { topic: '/lerobot_recorder/status' })),
        createTabItem('Controls', createViewNode('controls', {}))
      ]),
      [0.7, 0.3]
    ),
    createViewNode('timeline', {}),
    [0.78, 0.22]
  );
