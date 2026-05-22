import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

type Capability = { token: string; title: string };

type ModelDef = {
  model: string;
  capabilities?: string[];
  protect_with_permission?: boolean;
  permissions?: string[];
};

type Connection = {
  url: string;
  api_key?: string;
  models?: ModelDef[];
};

type Props = {
  id: string;
  value?: Connection[] | string;
  onChange: (id: string, value: Connection[]) => void;
};

type ModelDragKey = { connIndex: number; modelIndex: number };

const EMPTY_CONNECTION: Connection = {
  url: '',
  api_key: '',
  models: [],
};

const EMPTY_MODEL: ModelDef = {
  model: '',
  capabilities: [],
  protect_with_permission: false,
  permissions: [],
};

const COMMON_PERMISSIONS = [
  'View',
  'Modify portal content',
  'Add portal content',
];

const API_PREFIX = '/++api++';

async function apiFetch<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function parseValue(value: Props['value']): Connection[] {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string' && value) {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

function reorder<T>(list: T[], from: number, to: number): T[] {
  const next = [...list];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

const ModelsWidget: React.FC<Props> = ({ id, value, onChange }) => {
  const connections = useMemo(() => parseValue(value), [value]);
  const connectionsRef = useRef<Connection[]>(connections);
  useEffect(() => {
    connectionsRef.current = connections;
  }, [connections]);

  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [modelsByUrl, setModelsByUrl] = useState<
    Record<string, { loading: boolean; items: string[]; error?: string }>
  >({});

  // Drag state at two scopes — connection-level and model-level.
  const [connDragIndex, setConnDragIndex] = useState<number | null>(null);
  const [connDropIndex, setConnDropIndex] = useState<number | null>(null);
  const [modelDrag, setModelDrag] = useState<ModelDragKey | null>(null);
  const [modelDrop, setModelDrop] = useState<ModelDragKey | null>(null);

  // Permission drafts keyed by "<connIndex>:<modelIndex>" so each model
  // card has its own custom-permission input state.
  const [permDrafts, setPermDrafts] = useState<Record<string, string>>({});
  const draftKey = (c: number, m: number) => `${c}:${m}`;

  useEffect(() => {
    apiFetch<{ items: Array<{ token: string; title: string }> }>(
      '/@vocabularies/collective.ai.Capabilities',
    )
      .then((data) =>
        setCapabilities(
          (data.items || []).map((item) => ({
            token: item.token,
            title: item.title,
          })),
        ),
      )
      .catch(() => setCapabilities([]));
  }, []);

  const loadModels = useCallback(async (url: string, apiKey?: string) => {
    if (!url) return;
    setModelsByUrl((prev) => ({
      ...prev,
      [url]: { loading: true, items: prev[url]?.items || [] },
    }));
    try {
      const data = await apiFetch<{ models: string[] }>('/@ai-list-models', {
        method: 'POST',
        body: JSON.stringify({ url, api_key: apiKey || undefined }),
      });
      setModelsByUrl((prev) => ({
        ...prev,
        [url]: { loading: false, items: data.models || [] },
      }));
    } catch (err) {
      setModelsByUrl((prev) => ({
        ...prev,
        [url]: {
          loading: false,
          items: [],
          error: (err as Error).message,
        },
      }));
    }
  }, []);

  // Only prefetch model lists for connections that have at least one
  // pinned model (they're the only ones that show a dropdown).
  useEffect(() => {
    connections.forEach((conn) => {
      if (
        conn.url &&
        (conn.models?.length || 0) > 0 &&
        modelsByUrl[conn.url] === undefined
      ) {
        loadModels(conn.url, conn.api_key);
      }
    });
  }, [connections, modelsByUrl, loadModels]);

  // ---- Connection mutators ----
  const updateConnection = (connIndex: number, patch: Partial<Connection>) => {
    onChange(
      id,
      connections.map((c, i) => (i === connIndex ? { ...c, ...patch } : c)),
    );
  };

  const addConnection = () =>
    onChange(id, [...connections, { ...EMPTY_CONNECTION, models: [] }]);

  const removeConnection = (connIndex: number) =>
    onChange(
      id,
      connections.filter((_, i) => i !== connIndex),
    );

  // ---- Model mutators ----
  const updateModel = (
    connIndex: number,
    modelIndex: number,
    patch: Partial<ModelDef>,
  ) => {
    onChange(
      id,
      connections.map((c, i) =>
        i === connIndex
          ? {
              ...c,
              models: (c.models || []).map((m, j) =>
                j === modelIndex ? { ...m, ...patch } : m,
              ),
            }
          : c,
      ),
    );
  };

  const addModel = (connIndex: number) => {
    const target = connections[connIndex];
    onChange(
      id,
      connections.map((c, i) =>
        i === connIndex
          ? { ...c, models: [...(c.models || []), { ...EMPTY_MODEL }] }
          : c,
      ),
    );
    if (target.url) loadModels(target.url, target.api_key);
  };

  const removeModel = (connIndex: number, modelIndex: number) =>
    onChange(
      id,
      connections.map((c, i) =>
        i === connIndex
          ? {
              ...c,
              models: (c.models || []).filter((_, j) => j !== modelIndex),
            }
          : c,
      ),
    );

  const toggleCapability = (
    connIndex: number,
    modelIndex: number,
    token: string,
    checked: boolean,
  ) => {
    const current = new Set(
      connections[connIndex].models?.[modelIndex]?.capabilities || [],
    );
    if (checked) current.add(token);
    else current.delete(token);
    updateModel(connIndex, modelIndex, { capabilities: Array.from(current) });
  };

  const togglePermission = (
    connIndex: number,
    modelIndex: number,
    name: string,
    checked: boolean,
  ) => {
    const current = new Set(
      connections[connIndex].models?.[modelIndex]?.permissions || [],
    );
    if (checked) current.add(name);
    else current.delete(name);
    updateModel(connIndex, modelIndex, { permissions: Array.from(current) });
  };

  const addCustomPermission = (connIndex: number, modelIndex: number) => {
    const key = draftKey(connIndex, modelIndex);
    const draft = (permDrafts[key] || '').trim();
    if (!draft) return;
    const current = new Set(
      connections[connIndex].models?.[modelIndex]?.permissions || [],
    );
    if (current.has(draft)) {
      setPermDrafts((p) => ({ ...p, [key]: '' }));
      return;
    }
    current.add(draft);
    updateModel(connIndex, modelIndex, { permissions: Array.from(current) });
    setPermDrafts((p) => ({ ...p, [key]: '' }));
  };

  const removePermission = (
    connIndex: number,
    modelIndex: number,
    name: string,
  ) => {
    const current = (
      connections[connIndex].models?.[modelIndex]?.permissions || []
    ).filter((p) => p !== name);
    updateModel(connIndex, modelIndex, { permissions: current });
  };

  // ---- Model selection (auto-detect capabilities on change) ----
  const handleModelChange = async (
    connIndex: number,
    modelIndex: number,
    modelName: string,
  ) => {
    const conn = connectionsRef.current[connIndex];
    updateModel(connIndex, modelIndex, { model: modelName });
    if (!modelName || !conn?.url) return;
    try {
      const data = await apiFetch<{ capabilities: string[] }>(
        '/@ai-model-capabilities',
        {
          method: 'POST',
          body: JSON.stringify({
            url: conn.url,
            api_key: conn.api_key || undefined,
            model: modelName,
          }),
        },
      );
      if (data.capabilities && data.capabilities.length > 0) {
        const latest = connectionsRef.current;
        const latestModel = latest[connIndex]?.models?.[modelIndex];
        if (latestModel?.model !== modelName) return;
        onChange(
          id,
          latest.map((c, i) =>
            i === connIndex
              ? {
                  ...c,
                  models: (c.models || []).map((m, j) =>
                    j === modelIndex
                      ? { ...m, capabilities: data.capabilities }
                      : m,
                  ),
                }
              : c,
          ),
        );
      }
    } catch {
      // Auto-detection failed; leave checkboxes alone.
    }
  };

  // ---- Drag-and-drop (connections) ----
  const onConnDragStart =
    (i: number) => (e: React.DragEvent<HTMLDivElement>) => {
      setConnDragIndex(i);
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', `conn:${i}`);
    };

  const onConnDragOver =
    (i: number) => (e: React.DragEvent<HTMLDivElement>) => {
      if (connDragIndex === null) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (connDropIndex !== i) setConnDropIndex(i);
    };

  const onConnDrop = (i: number) => (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (connDragIndex === null || connDragIndex === i) {
      setConnDragIndex(null);
      setConnDropIndex(null);
      return;
    }
    onChange(id, reorder(connections, connDragIndex, i));
    setConnDragIndex(null);
    setConnDropIndex(null);
  };

  const onConnDragEnd = () => {
    setConnDragIndex(null);
    setConnDropIndex(null);
  };

  // ---- Drag-and-drop (models inside one connection) ----
  const onModelDragStart =
    (connIndex: number, modelIndex: number) =>
    (e: React.DragEvent<HTMLDivElement>) => {
      e.stopPropagation();
      setModelDrag({ connIndex, modelIndex });
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', `model:${connIndex}:${modelIndex}`);
    };

  const onModelDragOver =
    (connIndex: number, modelIndex: number) =>
    (e: React.DragEvent<HTMLDivElement>) => {
      if (!modelDrag || modelDrag.connIndex !== connIndex) return;
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = 'move';
      if (
        !modelDrop ||
        modelDrop.connIndex !== connIndex ||
        modelDrop.modelIndex !== modelIndex
      ) {
        setModelDrop({ connIndex, modelIndex });
      }
    };

  const onModelDrop =
    (connIndex: number, modelIndex: number) =>
    (e: React.DragEvent<HTMLDivElement>) => {
      if (!modelDrag || modelDrag.connIndex !== connIndex) return;
      e.preventDefault();
      e.stopPropagation();
      if (modelDrag.modelIndex === modelIndex) {
        setModelDrag(null);
        setModelDrop(null);
        return;
      }
      const conn = connections[connIndex];
      const reordered = reorder(
        conn.models || [],
        modelDrag.modelIndex,
        modelIndex,
      );
      onChange(
        id,
        connections.map((c, i) =>
          i === connIndex ? { ...c, models: reordered } : c,
        ),
      );
      setModelDrag(null);
      setModelDrop(null);
    };

  const onModelDragEnd = () => {
    setModelDrag(null);
    setModelDrop(null);
  };

  return (
    <div className="ai-models-widget">
      {connections.length === 0 && (
        <p className="ai-models-empty">
          No AI connections configured yet. Click <em>Add connection</em> below
          to start.
        </p>
      )}

      {connections.map((conn, connIndex) => {
        const state = conn.url ? modelsByUrl[conn.url] : undefined;
        const availableModels = state?.items || [];
        const isConnDragging = connDragIndex === connIndex;
        const isConnDropTarget =
          connDropIndex === connIndex && connDragIndex !== connIndex;
        const connModels = conn.models || [];

        return (
          <div
            key={connIndex}
            className={[
              'ai-connection',
              isConnDragging ? 'is-dragging' : '',
              isConnDropTarget ? 'is-drop-target' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            onDragOver={onConnDragOver(connIndex)}
            onDrop={onConnDrop(connIndex)}
            onDragEnd={onConnDragEnd}
          >
            <div
              className="ai-connection-header"
              draggable
              onDragStart={onConnDragStart(connIndex)}
            >
              <span
                className="ai-drag-handle"
                aria-label="Drag to reorder connection"
                title="Drag to reorder connection"
              >
                ⋮⋮
              </span>
              <span className="ai-connection-title">
                Connection #{connIndex + 1}
                {conn.url ? ` — ${conn.url}` : ''}
              </span>
              <button
                type="button"
                className="ai-remove"
                onClick={() => removeConnection(connIndex)}
              >
                Remove
              </button>
            </div>

            <div className="ai-connection-body">
              <div className="ai-field">
                <label htmlFor={`${id}-${connIndex}-url`}>URL</label>
                <input
                  id={`${id}-${connIndex}-url`}
                  type="url"
                  placeholder="http://localhost:11434"
                  value={conn.url || ''}
                  onChange={(e) =>
                    updateConnection(connIndex, { url: e.target.value })
                  }
                  onBlur={(e) => {
                    if (e.target.value && connModels.length > 0) {
                      loadModels(e.target.value, conn.api_key);
                    }
                  }}
                  required
                />
              </div>

              <div className="ai-field">
                <label htmlFor={`${id}-${connIndex}-api-key`}>API key</label>
                <input
                  id={`${id}-${connIndex}-api-key`}
                  type="password"
                  placeholder="(optional)"
                  value={conn.api_key || ''}
                  onChange={(e) =>
                    updateConnection(connIndex, { api_key: e.target.value })
                  }
                  onBlur={(e) => {
                    if (conn.url && connModels.length > 0) {
                      loadModels(conn.url, e.target.value || undefined);
                    }
                  }}
                />
              </div>

              <div className="ai-connection-models">
                {connModels.length === 0 && (
                  <p className="ai-hint ai-models-passthrough">
                    No models — this connection acts as a generic passthrough
                    (usable only when an @ai caller names a model explicitly).
                  </p>
                )}

                {connModels.map((mdl, modelIndex) => {
                  const isModelDragging =
                    modelDrag?.connIndex === connIndex &&
                    modelDrag?.modelIndex === modelIndex;
                  const isModelDropTarget =
                    modelDrop?.connIndex === connIndex &&
                    modelDrop?.modelIndex === modelIndex &&
                    !isModelDragging;
                  const modelMissing =
                    mdl.model &&
                    !availableModels.includes(mdl.model) &&
                    !state?.loading;
                  const selectedPerms = mdl.permissions || [];
                  const dKey = draftKey(connIndex, modelIndex);
                  const draftPerm = permDrafts[dKey] || '';

                  return (
                    <div
                      key={modelIndex}
                      className={[
                        'ai-model-card',
                        isModelDragging ? 'is-dragging' : '',
                        isModelDropTarget ? 'is-drop-target' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      onDragOver={onModelDragOver(connIndex, modelIndex)}
                      onDrop={onModelDrop(connIndex, modelIndex)}
                      onDragEnd={onModelDragEnd}
                    >
                      <div
                        className="ai-model-card-header"
                        draggable
                        onDragStart={onModelDragStart(connIndex, modelIndex)}
                      >
                        <span
                          className="ai-drag-handle"
                          aria-label="Drag to reorder model"
                          title="Drag to reorder model"
                        >
                          ⋮⋮
                        </span>
                        <span className="ai-model-card-title">
                          Model #{modelIndex + 1}
                          {mdl.model ? ` — ${mdl.model}` : ''}
                        </span>
                        <button
                          type="button"
                          className="ai-remove"
                          onClick={() => removeModel(connIndex, modelIndex)}
                        >
                          Remove
                        </button>
                      </div>

                      <div className="ai-model-card-body">
                        <div className="ai-field">
                          <label
                            htmlFor={`${id}-${connIndex}-${modelIndex}-model`}
                          >
                            Model{' '}
                            {state?.loading && (
                              <span className="ai-hint">(loading…)</span>
                            )}
                            {state?.error && (
                              <span className="ai-hint ai-error">
                                (could not reach service)
                              </span>
                            )}
                          </label>
                          <select
                            id={`${id}-${connIndex}-${modelIndex}-model`}
                            value={mdl.model || ''}
                            onChange={(e) =>
                              handleModelChange(
                                connIndex,
                                modelIndex,
                                e.target.value,
                              )
                            }
                            disabled={!conn.url || state?.loading}
                            required
                          >
                            <option value="" disabled>
                              {!conn.url
                                ? 'Enter a URL first'
                                : state?.loading
                                  ? 'Loading…'
                                  : availableModels.length
                                    ? 'Select a model'
                                    : 'No models available'}
                            </option>
                            {availableModels.map((m) => (
                              <option key={m} value={m}>
                                {m}
                              </option>
                            ))}
                            {modelMissing && (
                              <option value={mdl.model}>
                                {mdl.model} (not currently available)
                              </option>
                            )}
                          </select>
                        </div>

                        <fieldset className="ai-field ai-capabilities">
                          <legend>Capabilities</legend>
                          {capabilities.length === 0 && (
                            <span className="ai-hint">
                              Loading capabilities…
                            </span>
                          )}
                          {capabilities.map((cap) => (
                            <label key={cap.token} className="ai-checkbox">
                              <input
                                type="checkbox"
                                checked={(mdl.capabilities || []).includes(
                                  cap.token,
                                )}
                                onChange={(e) =>
                                  toggleCapability(
                                    connIndex,
                                    modelIndex,
                                    cap.token,
                                    e.target.checked,
                                  )
                                }
                              />
                              <span>{cap.title}</span>
                            </label>
                          ))}
                        </fieldset>

                        <label className="ai-checkbox ai-toggle">
                          <input
                            type="checkbox"
                            checked={!!mdl.protect_with_permission}
                            onChange={(e) =>
                              updateModel(connIndex, modelIndex, {
                                protect_with_permission: e.target.checked,
                              })
                            }
                          />
                          <span>Protect with permission</span>
                        </label>

                        {mdl.protect_with_permission && (
                          <fieldset className="ai-field ai-permissions">
                            <legend>
                              Allowed permissions (any one grants access)
                            </legend>

                            {selectedPerms.length > 0 && (
                              <div className="ai-perm-chips">
                                {selectedPerms.map((p) => (
                                  <span key={p} className="ai-perm-chip">
                                    {p}
                                    <button
                                      type="button"
                                      className="ai-perm-chip-remove"
                                      aria-label={`Remove ${p}`}
                                      onClick={() =>
                                        removePermission(
                                          connIndex,
                                          modelIndex,
                                          p,
                                        )
                                      }
                                    >
                                      ×
                                    </button>
                                  </span>
                                ))}
                              </div>
                            )}

                            {COMMON_PERMISSIONS.map((name) => (
                              <label key={name} className="ai-checkbox">
                                <input
                                  type="checkbox"
                                  checked={selectedPerms.includes(name)}
                                  onChange={(e) =>
                                    togglePermission(
                                      connIndex,
                                      modelIndex,
                                      name,
                                      e.target.checked,
                                    )
                                  }
                                />
                                <span>{name}</span>
                              </label>
                            ))}

                            <div className="ai-perm-add">
                              <input
                                type="text"
                                placeholder="Custom permission (e.g. Manage portal)"
                                value={draftPerm}
                                onChange={(e) =>
                                  setPermDrafts((p) => ({
                                    ...p,
                                    [dKey]: e.target.value,
                                  }))
                                }
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') {
                                    e.preventDefault();
                                    addCustomPermission(connIndex, modelIndex);
                                  }
                                }}
                              />
                              <button
                                type="button"
                                className="ai-perm-add-btn"
                                onClick={() =>
                                  addCustomPermission(connIndex, modelIndex)
                                }
                                disabled={!draftPerm.trim()}
                              >
                                +
                              </button>
                            </div>
                          </fieldset>
                        )}
                      </div>
                    </div>
                  );
                })}

                <button
                  type="button"
                  className="ai-add ai-add-model"
                  onClick={() => addModel(connIndex)}
                >
                  + Add model
                </button>
              </div>
            </div>
          </div>
        );
      })}

      <button type="button" className="ai-add" onClick={addConnection}>
        + Add connection
      </button>
    </div>
  );
};

export default ModelsWidget;
