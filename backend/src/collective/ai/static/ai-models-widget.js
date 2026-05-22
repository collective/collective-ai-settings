/*
 * Classic-Plone editor for the `IAISettings.models` JSONField.
 * Mirrors the Volto ModelsWidget feature-for-feature using vanilla JS.
 *
 * The element rendered by the page template is just a hidden input plus
 * an empty <div class="ai-models-list">. This script builds the rich UI
 * imperatively, serializing state back to the hidden input on every
 * change so the standard z3c.form submit picks it up.
 *
 * Data shape (matches IAISettings.models JSON schema):
 *   [
 *     {
 *       url: "...",
 *       api_key: "...",
 *       models: [
 *         { model, capabilities[], protect_with_permission, permissions[] }
 *       ]
 *     }
 *   ]
 * A connection with empty `models` is a generic passthrough.
 */
(function () {
  "use strict";

  var COMMON_PERMISSIONS = [
    "View",
    "Modify portal content",
    "Add portal content",
  ];

  function getCsrfToken() {
    var input = document.querySelector('input[name="_authenticator"]');
    if (input && input.value) return input.value;
    var match = document.cookie.match(/_authenticator=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function makeApi(apiBase) {
    return function api(path, init) {
      init = init || {};
      var headers = Object.assign(
        {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        init.headers || {},
      );
      if ((init.method || "GET").toUpperCase() !== "GET") {
        var token = getCsrfToken();
        if (token) headers["X-CSRF-Token"] = token;
      }
      return fetch(apiBase + path, {
        credentials: "include",
        ...init,
        headers: headers,
      }).then(function (response) {
        if (!response.ok) {
          return response.text().then(function (text) {
            throw new Error("HTTP " + response.status + ": " + text);
          });
        }
        return response.json();
      });
    };
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === "className") node.className = attrs[key];
      else if (key === "text") node.textContent = attrs[key];
      else if (key.indexOf("on") === 0)
        node.addEventListener(key.slice(2).toLowerCase(), attrs[key]);
      else if (attrs[key] === true) node.setAttribute(key, "true");
      else if (attrs[key] === false || attrs[key] == null) {
        /* skip */
      } else node.setAttribute(key, attrs[key]);
    });
    (children || []).forEach(function (child) {
      if (child == null) return;
      if (typeof child === "string") node.appendChild(document.createTextNode(child));
      else node.appendChild(child);
    });
    return node;
  }

  function init(widget) {
    var input = widget.querySelector('input[type="hidden"]');
    var list = widget.querySelector(".ai-models-list");
    var empty = widget.querySelector(".ai-models-empty");
    var addBtn = widget.querySelector(".ai-models-add");

    var portalUrl = (widget.getAttribute("data-portal-url") || "").replace(
      /\/$/,
      "",
    );
    var api = makeApi(portalUrl + "/++api++");

    var connections = [];
    try {
      var parsed = JSON.parse(input.value || "[]");
      connections = Array.isArray(parsed) ? parsed : [];
    } catch (_) {
      connections = [];
    }

    var capabilities = [];
    var modelsByUrl = {};

    // Drag state at two scopes — connection level and model level.
    var connDragIndex = null;
    var connDropIndex = null;
    var modelDrag = null; // {connIndex, modelIndex} or null
    var modelDrop = null;

    function commit() {
      input.value = JSON.stringify(connections);
    }

    function cleanupDragClasses() {
      var nodes = list.querySelectorAll(".is-dragging, .is-drop-target");
      for (var i = 0; i < nodes.length; i++) {
        nodes[i].classList.remove("is-dragging");
        nodes[i].classList.remove("is-drop-target");
      }
    }

    if (addBtn) {
      addBtn.textContent = "+ Add connection";
      addBtn.classList.add("ai-add-connection");
    }

    function render() {
      list.innerHTML = "";
      if (connections.length === 0) {
        list.hidden = true;
        empty.hidden = false;
        empty.textContent =
          "No AI connections configured yet. Click “+ Add connection” to start.";
        return;
      }
      empty.hidden = true;
      list.hidden = false;

      connections.forEach(function (conn, connIndex) {
        list.appendChild(renderConnection(conn, connIndex));
      });
    }

    // ---- Connection card ----
    function renderConnection(conn, connIndex) {
      var card = el("div", { className: "ai-connection" });

      // Connection-level drop target.
      card.addEventListener("dragover", function (e) {
        if (connDragIndex === null || connDragIndex === connIndex) return;
        // Don't claim drops that belong to model-level drag.
        if (modelDrag !== null) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        if (connDropIndex !== connIndex) {
          var prev = list.querySelector(".ai-connection.is-drop-target");
          if (prev && prev !== card) prev.classList.remove("is-drop-target");
          card.classList.add("is-drop-target");
          connDropIndex = connIndex;
        }
      });

      card.addEventListener("dragleave", function (e) {
        if (!e.relatedTarget || !card.contains(e.relatedTarget)) {
          card.classList.remove("is-drop-target");
          if (connDropIndex === connIndex) connDropIndex = null;
        }
      });

      card.addEventListener("drop", function (e) {
        if (modelDrag !== null) return;
        e.preventDefault();
        var from = connDragIndex;
        cleanupDragClasses();
        connDragIndex = null;
        connDropIndex = null;
        if (from === null || from === connIndex) return;
        var moved = connections.splice(from, 1)[0];
        var targetIndex = from < connIndex ? connIndex - 1 : connIndex;
        connections.splice(targetIndex, 0, moved);
        commit();
        render();
      });

      // Connection drag handle / header.
      var header = el("div", {
        className: "ai-connection-header",
        draggable: true,
      });
      header.draggable = true;

      header.addEventListener("dragstart", function (e) {
        connDragIndex = connIndex;
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", "conn:" + connIndex);
        setTimeout(function () {
          card.classList.add("is-dragging");
        }, 0);
      });

      header.addEventListener("dragend", function () {
        cleanupDragClasses();
        connDragIndex = null;
        connDropIndex = null;
      });

      header.appendChild(
        el("span", {
          className: "ai-drag-handle",
          title: "Drag to reorder connection",
          text: "⋮⋮",
        }),
      );
      header.appendChild(
        el("span", {
          className: "ai-connection-title",
          text:
            "Connection #" + (connIndex + 1) +
            (conn.url ? " — " + conn.url : ""),
        }),
      );
      header.appendChild(
        el("button", {
          type: "button",
          className: "ai-remove",
          text: "Remove",
          onclick: function () {
            connections.splice(connIndex, 1);
            commit();
            render();
          },
        }),
      );
      card.appendChild(header);

      // Body
      var body = el("div", { className: "ai-connection-body" });
      var connModels = conn.models || [];

      body.appendChild(renderUrlField(conn, connIndex, connModels.length > 0));
      body.appendChild(renderApiKeyField(conn, connIndex, connModels.length > 0));
      body.appendChild(renderModelsList(conn, connIndex, connModels));

      card.appendChild(body);
      return card;
    }

    function renderUrlField(conn, connIndex, hasModels) {
      var input = el("input", {
        type: "url",
        value: conn.url || "",
        placeholder: "http://localhost:11434",
        required: true,
        oninput: function (e) {
          conn.url = e.target.value;
          commit();
        },
        onblur: function (e) {
          if (hasModels && e.target.value)
            loadModels(e.target.value, conn.api_key);
        },
      });
      return el("div", { className: "ai-field" }, [
        el("label", { text: "URL" }),
        input,
      ]);
    }

    function renderApiKeyField(conn, connIndex, hasModels) {
      var input = el("input", {
        type: "password",
        value: conn.api_key || "",
        placeholder: "(optional)",
        oninput: function (e) {
          conn.api_key = e.target.value;
          commit();
        },
        onblur: function (e) {
          if (hasModels && conn.url) loadModels(conn.url, e.target.value);
        },
      });
      return el("div", { className: "ai-field" }, [
        el("label", { text: "API key" }),
        input,
      ]);
    }

    function renderModelsList(conn, connIndex, connModels) {
      var wrap = el("div", { className: "ai-connection-models" });

      if (connModels.length === 0) {
        wrap.appendChild(
          el("p", {
            className: "ai-hint ai-models-passthrough",
            text:
              "No models — this connection acts as a generic passthrough " +
              "(usable only when an @ai caller names a model explicitly).",
          }),
        );
      } else {
        connModels.forEach(function (mdl, modelIndex) {
          wrap.appendChild(renderModelCard(conn, connIndex, mdl, modelIndex));
        });
      }

      wrap.appendChild(
        el("button", {
          type: "button",
          className: "ai-add ai-add-model",
          text: "+ Add model",
          onclick: function () {
            conn.models = conn.models || [];
            conn.models.push({
              model: "",
              capabilities: [],
              protect_with_permission: false,
              permissions: [],
            });
            commit();
            if (conn.url) loadModels(conn.url, conn.api_key);
            render();
          },
        }),
      );

      return wrap;
    }

    function renderModelCard(conn, connIndex, mdl, modelIndex) {
      var state = conn.url ? modelsByUrl[conn.url] : null;
      var models = (state && state.items) || [];

      var card = el("div", { className: "ai-model-card" });

      card.addEventListener("dragover", function (e) {
        if (
          !modelDrag ||
          modelDrag.connIndex !== connIndex ||
          modelDrag.modelIndex === modelIndex
        )
          return;
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = "move";
        var key = connIndex + ":" + modelIndex;
        var currentKey = modelDrop
          ? modelDrop.connIndex + ":" + modelDrop.modelIndex
          : null;
        if (currentKey !== key) {
          var prev = list.querySelector(".ai-model-card.is-drop-target");
          if (prev && prev !== card) prev.classList.remove("is-drop-target");
          card.classList.add("is-drop-target");
          modelDrop = { connIndex: connIndex, modelIndex: modelIndex };
        }
      });

      card.addEventListener("dragleave", function (e) {
        if (!e.relatedTarget || !card.contains(e.relatedTarget)) {
          card.classList.remove("is-drop-target");
          if (
            modelDrop &&
            modelDrop.connIndex === connIndex &&
            modelDrop.modelIndex === modelIndex
          ) {
            modelDrop = null;
          }
        }
      });

      card.addEventListener("drop", function (e) {
        if (!modelDrag || modelDrag.connIndex !== connIndex) return;
        e.preventDefault();
        e.stopPropagation();
        var fromIndex = modelDrag.modelIndex;
        cleanupDragClasses();
        modelDrag = null;
        modelDrop = null;
        if (fromIndex === modelIndex) return;
        var moved = conn.models.splice(fromIndex, 1)[0];
        var targetIndex =
          fromIndex < modelIndex ? modelIndex - 1 : modelIndex;
        conn.models.splice(targetIndex, 0, moved);
        commit();
        render();
      });

      // Model header (drag handle source)
      var header = el("div", {
        className: "ai-model-card-header",
        draggable: true,
      });
      header.draggable = true;

      header.addEventListener("dragstart", function (e) {
        e.stopPropagation();
        modelDrag = { connIndex: connIndex, modelIndex: modelIndex };
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData(
          "text/plain",
          "model:" + connIndex + ":" + modelIndex,
        );
        setTimeout(function () {
          card.classList.add("is-dragging");
        }, 0);
      });

      header.addEventListener("dragend", function () {
        cleanupDragClasses();
        modelDrag = null;
        modelDrop = null;
      });

      header.appendChild(
        el("span", {
          className: "ai-drag-handle",
          title: "Drag to reorder model",
          text: "⋮⋮",
        }),
      );
      header.appendChild(
        el("span", {
          className: "ai-model-card-title",
          text:
            "Model #" + (modelIndex + 1) +
            (mdl.model ? " — " + mdl.model : ""),
        }),
      );
      header.appendChild(
        el("button", {
          type: "button",
          className: "ai-remove",
          text: "Remove",
          onclick: function () {
            conn.models.splice(modelIndex, 1);
            commit();
            render();
          },
        }),
      );
      card.appendChild(header);

      var body = el("div", { className: "ai-model-card-body" });

      body.appendChild(renderModelField(conn, mdl, connIndex, modelIndex, models, state));
      body.appendChild(renderCapabilities(mdl));
      body.appendChild(renderProtectToggle(mdl));
      if (mdl.protect_with_permission) {
        body.appendChild(renderPermissions(mdl));
      }

      card.appendChild(body);
      return card;
    }

    function renderModelField(conn, mdl, connIndex, modelIndex, models, state) {
      var loading = state && state.loading;
      var error = state && state.error;
      var label = el("label", {}, ["Model"]);
      if (loading)
        label.appendChild(
          el("span", { className: "ai-hint", text: " (loading…)" }),
        );
      if (error)
        label.appendChild(
          el("span", {
            className: "ai-hint ai-error",
            text: " (could not reach service)",
          }),
        );

      var select = el("select", {
        required: true,
        disabled: !conn.url || loading,
        onchange: function (e) {
          mdl.model = e.target.value;
          commit();
          render();
          autoDetectCapabilities(conn, mdl, connIndex, modelIndex);
        },
      });
      var placeholder = el("option", {
        value: "",
        disabled: true,
        text: !conn.url
          ? "Enter a URL first"
          : loading
            ? "Loading…"
            : models.length
              ? "Select a model"
              : "No models available",
      });
      if (!mdl.model) placeholder.setAttribute("selected", "");
      select.appendChild(placeholder);

      models.forEach(function (m) {
        var opt = el("option", { value: m, text: m });
        if (m === mdl.model) opt.setAttribute("selected", "");
        select.appendChild(opt);
      });

      if (mdl.model && models.indexOf(mdl.model) === -1 && !loading) {
        var opt = el("option", {
          value: mdl.model,
          text: mdl.model + " (not currently available)",
        });
        opt.setAttribute("selected", "");
        select.appendChild(opt);
      }

      return el("div", { className: "ai-field" }, [label, select]);
    }

    function renderCapabilities(mdl) {
      var fieldset = el("fieldset", { className: "ai-field ai-capabilities" });
      fieldset.appendChild(el("legend", { text: "Capabilities" }));
      if (capabilities.length === 0) {
        fieldset.appendChild(
          el("span", { className: "ai-hint", text: "Loading capabilities…" }),
        );
        return fieldset;
      }
      capabilities.forEach(function (cap) {
        var checkbox = el("input", {
          type: "checkbox",
          onchange: function (e) {
            var set = new Set(mdl.capabilities || []);
            if (e.target.checked) set.add(cap.token);
            else set.delete(cap.token);
            mdl.capabilities = Array.from(set);
            commit();
          },
        });
        if ((mdl.capabilities || []).indexOf(cap.token) !== -1) {
          checkbox.checked = true;
        }
        fieldset.appendChild(
          el("label", { className: "ai-checkbox" }, [
            checkbox,
            el("span", { text: cap.title }),
          ]),
        );
      });
      return fieldset;
    }

    function renderProtectToggle(mdl) {
      var checkbox = el("input", {
        type: "checkbox",
        onchange: function (e) {
          mdl.protect_with_permission = e.target.checked;
          commit();
          render();
        },
      });
      if (mdl.protect_with_permission) checkbox.checked = true;
      return el("label", { className: "ai-checkbox ai-toggle" }, [
        checkbox,
        el("span", { text: "Protect with permission" }),
      ]);
    }

    function renderPermissions(mdl) {
      var fieldset = el("fieldset", { className: "ai-field ai-permissions" });
      fieldset.appendChild(
        el("legend", {
          text: "Allowed permissions (any one grants access)",
        }),
      );

      var selected = mdl.permissions || [];

      if (selected.length > 0) {
        var chips = el("div", { className: "ai-perm-chips" });
        selected.forEach(function (name) {
          var chip = el("span", { className: "ai-perm-chip" }, [name]);
          chip.appendChild(
            el("button", {
              type: "button",
              className: "ai-perm-chip-remove",
              text: "×",
              "aria-label": "Remove " + name,
              onclick: function () {
                mdl.permissions = (mdl.permissions || []).filter(
                  function (p) {
                    return p !== name;
                  },
                );
                commit();
                render();
              },
            }),
          );
          chips.appendChild(chip);
        });
        fieldset.appendChild(chips);
      }

      COMMON_PERMISSIONS.forEach(function (name) {
        var checkbox = el("input", {
          type: "checkbox",
          onchange: function (e) {
            var set = new Set(mdl.permissions || []);
            if (e.target.checked) set.add(name);
            else set.delete(name);
            mdl.permissions = Array.from(set);
            commit();
            render();
          },
        });
        if (selected.indexOf(name) !== -1) checkbox.checked = true;
        fieldset.appendChild(
          el("label", { className: "ai-checkbox" }, [
            checkbox,
            el("span", { text: name }),
          ]),
        );
      });

      var draftInput = el("input", {
        type: "text",
        placeholder: "Custom permission (e.g. Manage portal)",
      });
      var addBtn = el("button", {
        type: "button",
        className: "ai-perm-add-btn",
        text: "+",
      });
      function commitDraft() {
        var draft = (draftInput.value || "").trim();
        if (!draft) return;
        var set = new Set(mdl.permissions || []);
        if (!set.has(draft)) {
          set.add(draft);
          mdl.permissions = Array.from(set);
          commit();
        }
        draftInput.value = "";
        render();
      }
      addBtn.addEventListener("click", commitDraft);
      draftInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          e.preventDefault();
          commitDraft();
        }
      });

      fieldset.appendChild(
        el("div", { className: "ai-perm-add" }, [draftInput, addBtn]),
      );
      return fieldset;
    }

    function loadModels(url, apiKey) {
      if (!url) return;
      modelsByUrl[url] = {
        loading: true,
        items: (modelsByUrl[url] || {}).items || [],
      };
      render();
      api("/@ai-list-models", {
        method: "POST",
        body: JSON.stringify({ url: url, api_key: apiKey || undefined }),
      })
        .then(function (data) {
          modelsByUrl[url] = { loading: false, items: data.models || [] };
        })
        .catch(function (err) {
          modelsByUrl[url] = { loading: false, items: [], error: String(err) };
        })
        .then(render);
    }

    function autoDetectCapabilities(conn, mdl, connIndex, modelIndex) {
      if (!conn.url || !mdl.model) return;
      var capturedModel = mdl.model;
      api("/@ai-model-capabilities", {
        method: "POST",
        body: JSON.stringify({
          url: conn.url,
          api_key: conn.api_key || undefined,
          model: mdl.model,
        }),
      })
        .then(function (data) {
          if (!data.capabilities || !data.capabilities.length) return;
          var live = connections[connIndex];
          var liveMdl = live && (live.models || [])[modelIndex];
          if (!liveMdl || liveMdl.model !== capturedModel) return;
          liveMdl.capabilities = data.capabilities;
          commit();
          render();
        })
        .catch(function () {
          /* leave checkboxes alone on failure */
        });
    }

    addBtn.addEventListener("click", function () {
      connections.push({ url: "", api_key: "", models: [] });
      commit();
      render();
    });

    // Initial load: capabilities vocabulary, then model lists for every
    // connection that already has at least one pinned model.
    api("/@vocabularies/collective.ai.Capabilities")
      .then(function (data) {
        capabilities = (data.items || []).map(function (item) {
          return { token: item.token, title: item.title };
        });
      })
      .catch(function () {
        capabilities = [];
      })
      .then(function () {
        connections.forEach(function (conn) {
          if (conn.url && (conn.models || []).length > 0) {
            loadModels(conn.url, conn.api_key);
          }
        });
        render();
      });
  }

  function start() {
    document
      .querySelectorAll("[data-ai-models-widget]:not([data-initialized])")
      .forEach(function (widget) {
        widget.setAttribute("data-initialized", "true");
        init(widget);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
