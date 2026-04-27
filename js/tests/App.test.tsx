import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import {
  App,
  extractPanelNames,
  isPanelVisible,
  parseHash,
} from "../src/ts/App.tsx";
import type { AgentSummary, DashboardState } from "../src/ts/App.tsx";

// Mock the api module so the app doesn't make real HTTP calls
vi.mock("../src/ts/api.ts", () => ({
  listAgents: vi.fn().mockResolvedValue([]),
  getAgent: vi.fn().mockResolvedValue({
    agent_id: "a1",
    profile_name: "test",
    status: "running",
  }),
  stopAgent: vi.fn().mockResolvedValue({ status: "stopping" }),
  killAgent: vi.fn().mockResolvedValue({ status: "killed" }),
  restartAgent: vi.fn().mockResolvedValue({}),
  launchAgent: vi.fn().mockResolvedValue({}),
  listProfiles: vi.fn().mockResolvedValue([]),
  createProfile: vi
    .fn()
    .mockResolvedValue({ id: "p1", name: "test", version: 1 }),
  updateProfile: vi
    .fn()
    .mockResolvedValue({ id: "p1", name: "test", version: 2 }),
  fetchActivity: vi.fn().mockResolvedValue([]),
  queryMessages: vi.fn().mockResolvedValue([]),
  queryAudit: vi.fn().mockResolvedValue([]),
  sendMessageToAgent: vi
    .fn()
    .mockResolvedValue({ message_id: "m1", sequence: 1 }),
  listPreconfiguredAgents: vi.fn().mockResolvedValue([]),
  getProfile: vi.fn().mockResolvedValue({}),
  deleteProfile: vi.fn().mockResolvedValue({ deleted: true }),
  listPreconfigured: vi.fn().mockResolvedValue([]),
  saveAgentToDisk: vi.fn().mockResolvedValue({ path: "/tmp/test.md" }),
  generateAgentProfile: vi
    .fn()
    .mockResolvedValue({ message_id: "m1", sequence: 1, prompt_sent: "" }),
  listChannels: vi.fn().mockResolvedValue([]),
  listCheckpoints: vi.fn().mockResolvedValue([]),
  replayMessage: vi.fn().mockResolvedValue({ message_id: "m1", sequence: 1 }),
  fetchProviders: vi.fn().mockResolvedValue([
    {
      id: "github-copilot",
      name: "GitHub Copilot",
      models: [
        {
          id: "claude-sonnet-4.6",
          name: "Claude Sonnet 4.6",
          billing: { type: "multiplier", multiplier: 1.0 },
        },
      ],
    },
    {
      id: "openai",
      name: "OpenAI",
      models: [
        {
          id: "gpt-5.4",
          name: "GPT-5.4",
          billing: {
            type: "per_token",
            input_per_mtok: 2.5,
            output_per_mtok: 15.0,
          },
        },
      ],
    },
    {
      id: "anthropic",
      name: "Anthropic",
      models: [
        {
          id: "claude-sonnet-4-6",
          name: "Claude Sonnet 4.6",
          billing: {
            type: "per_token",
            input_per_mtok: 3.0,
            output_per_mtok: 15.0,
          },
        },
      ],
    },
    {
      id: "google",
      name: "Google",
      models: [
        {
          id: "gemini-2.5-pro",
          name: "Gemini 2.5 Pro",
          billing: {
            type: "per_token",
            input_per_mtok: 1.25,
            output_per_mtok: 10.0,
          },
        },
      ],
    },
  ]),
}));

// Mock the ws module so the app doesn't create real WebSocket connections
vi.mock("../src/ts/ws.ts", () => {
  class MockLangleyWsClient {
    connect = vi.fn();
    disconnect = vi.fn();
    subscribe = vi.fn().mockReturnValue(vi.fn());
    onConnect: (() => void) | null = null;
    onDisconnect: (() => void) | null = null;
    onError: ((message: string) => void) | null = null;
  }

  return {
    LangleyWsClient: MockLangleyWsClient,
  };
});

// Mock regular-layout: jsdom can't run real web components, so we register
// stub custom elements that expose the imperative API as no-ops.
vi.mock("regular-layout", () => {
  if (typeof customElements !== "undefined") {
    if (!customElements.get("regular-layout")) {
      customElements.define(
        "regular-layout",
        class extends HTMLElement {
          private _panels: string[] = [];
          private _selected: number = 0;
          insertPanel(name: string) {
            if (!this._panels.includes(name)) {
              this._panels.push(name);
              this._selected = this._panels.length - 1;
            }
          }
          removePanel(name: string) {
            const idx = this._panels.indexOf(name);
            if (idx < 0) return;
            this._panels.splice(idx, 1);
            if (this._selected >= this._panels.length) {
              this._selected = Math.max(0, this._panels.length - 1);
            }
          }
          save() {
            if (this._panels.length === 0) return null;
            return {
              type: "tab-layout",
              tabs: [...this._panels],
              selected: this._selected,
            };
          }
          restore(tree: { tabs?: string[]; selected?: number } | null) {
            if (
              tree &&
              Array.isArray(tree.tabs) &&
              typeof tree.selected === "number"
            ) {
              this._panels = [...tree.tabs];
              this._selected = tree.selected;
            }
          }
          getPanel(name: string) {
            return this._panels.includes(name)
              ? { type: "tab-layout", tabs: [name] }
              : null;
          }
        },
      );
    }
    if (!customElements.get("regular-layout-frame")) {
      customElements.define(
        "regular-layout-frame",
        class extends HTMLElement {},
      );
    }
  }
  return {};
});

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  // jsdom doesn't implement scrollIntoView
  Element.prototype.scrollIntoView = vi.fn();
  // Clear persisted layout so tests start fresh
  window.localStorage.removeItem("langley-layout");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("App", () => {
  test("renders the app header", async () => {
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByText("hq")).toBeInTheDocument();
  });

  test("shows disconnected status by default", async () => {
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByTestId("connection-status")).toHaveTextContent(
      "Disconnected",
    );
  });

  test("shows no agents message when list is empty", async () => {
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByTestId("no-agents")).toHaveTextContent(
      "No agents running.",
    );
  });

  test("renders summary cards with zero counts initially", async () => {
    await act(async () => {
      render(<App />);
    });
    const total = screen.getByTestId("card-total");
    expect(total).toHaveTextContent("0");
    expect(total).toHaveTextContent("Total");
  });

  test("renders status filter dropdown", async () => {
    await act(async () => {
      render(<App />);
    });
    const filter = screen.getByTestId("status-filter");
    expect(filter).toBeInTheDocument();
    expect(filter).toHaveValue("all");
  });

  test("has all filter options", async () => {
    await act(async () => {
      render(<App />);
    });
    const options = screen
      .getByTestId("status-filter")
      .querySelectorAll("option");
    const values = Array.from(options).map(
      (o) => (o as HTMLOptionElement).value,
    );
    expect(values).toEqual(["all", "running", "stopped", "errored", "pending"]);
  });
});

describe("SummaryCards", () => {
  test("all cards are rendered", async () => {
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByTestId("card-total")).toBeInTheDocument();
    expect(screen.getByTestId("card-running")).toBeInTheDocument();
    expect(screen.getByTestId("card-stopped")).toBeInTheDocument();
    expect(screen.getByTestId("card-errored")).toBeInTheDocument();
    expect(screen.getByTestId("card-pending")).toBeInTheDocument();
  });
});

describe("AgentTable", () => {
  test("shows empty message when no agents", async () => {
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByTestId("no-agents")).toBeInTheDocument();
    expect(screen.queryByTestId("agent-table")).not.toBeInTheDocument();
  });

  test("stopped agent shows Restart button", async () => {
    const { AgentTable } = await import("../src/ts/components/AgentTable.tsx");
    const onAction = vi.fn();
    await act(async () => {
      render(
        <AgentTable
          agents={[
            {
              id: "a1",
              name: "test",
              profile: "p",
              tenant_id: "t",
              status: "stopped",
              uptime_seconds: 0,
            },
          ]}
          onAction={onAction}
        />,
      );
    });
    const btn = screen.getByTestId("restart-a1");
    expect(btn).toHaveTextContent("Restart");
    fireEvent.click(btn);
    expect(onAction).toHaveBeenCalledWith("a1", "restart");
  });

  test("errored agent shows Restart button", async () => {
    const { AgentTable } = await import("../src/ts/components/AgentTable.tsx");
    const onAction = vi.fn();
    await act(async () => {
      render(
        <AgentTable
          agents={[
            {
              id: "e1",
              name: "broken",
              profile: "p",
              tenant_id: "t",
              status: "errored",
              uptime_seconds: 0,
            },
          ]}
          onAction={onAction}
        />,
      );
    });
    expect(screen.getByTestId("restart-e1")).toHaveTextContent("Restart");
  });
});

describe("isPanelVisible", () => {
  test("returns true for the selected tab in a tab-layout", () => {
    expect(
      isPanelVisible(
        { type: "tab-layout", tabs: ["a", "b"], selected: 1 },
        "b",
      ),
    ).toBe(true);
  });

  test("returns false for a non-selected tab in a tab-layout", () => {
    expect(
      isPanelVisible(
        { type: "tab-layout", tabs: ["a", "b"], selected: 1 },
        "a",
      ),
    ).toBe(false);
  });

  test("recurses into split-layout children", () => {
    const tree = {
      type: "split-layout",
      orientation: "horizontal",
      sizes: [0.5, 0.5],
      children: [
        { type: "tab-layout", tabs: ["a"], selected: 0 },
        { type: "tab-layout", tabs: ["b", "c"], selected: 0 },
      ],
    };
    expect(isPanelVisible(tree, "a")).toBe(true);
    expect(isPanelVisible(tree, "b")).toBe(true);
    expect(isPanelVisible(tree, "c")).toBe(false);
    expect(isPanelVisible(tree, "missing")).toBe(false);
  });

  test("returns false for absent panel", () => {
    expect(
      isPanelVisible({ type: "tab-layout", tabs: ["a"], selected: 0 }, "z"),
    ).toBe(false);
  });
});

describe("ActivityFeed", () => {
  test("shows no activity message initially", async () => {
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByTestId("no-activity")).toHaveTextContent(
      "No recent activity.",
    );
  });
});

describe("LaunchDialog", () => {
  test("launch agent button opens dialog", async () => {
    await act(async () => {
      render(<App />);
    });
    const openBtn = screen.getByTestId("open-launch");
    expect(openBtn).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(openBtn);
    });
    expect(screen.getByTestId("launch-dialog")).toBeInTheDocument();
  });

  test("dialog can be closed", async () => {
    await act(async () => {
      render(<App />);
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("open-launch"));
    });
    expect(screen.getByTestId("launch-dialog")).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByTestId("close-dialog"));
    });
    expect(screen.queryByTestId("launch-dialog")).not.toBeInTheDocument();
  });

  test("new profile toggle shows form", async () => {
    await act(async () => {
      render(<App />);
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("open-launch"));
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("new-profile-toggle"));
    });
    expect(screen.getByTestId("new-profile-form")).toBeInTheDocument();
    expect(screen.getByTestId("np-name")).toBeInTheDocument();
    expect(screen.getByTestId("np-provider")).toBeInTheDocument();
    expect(screen.getByTestId("np-prompt")).toBeInTheDocument();
    // Command field visible by default (no provider selected)
    expect(screen.getByTestId("np-command")).toBeInTheDocument();
  });

  test("selecting a provider shows model selector and hides command", async () => {
    await act(async () => {
      render(<App />);
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("open-launch"));
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("new-profile-toggle"));
    });
    // Select OpenAI provider
    await act(async () => {
      fireEvent.change(screen.getByTestId("np-provider"), {
        target: { value: "openai" },
      });
    });
    // Model selector should appear, command should be hidden
    expect(screen.getByTestId("np-model")).toBeInTheDocument();
    expect(screen.queryByTestId("np-command")).not.toBeInTheDocument();
  });

  test("selecting custom provider shows command field without model", async () => {
    await act(async () => {
      render(<App />);
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("open-launch"));
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("new-profile-toggle"));
    });
    await act(async () => {
      fireEvent.change(screen.getByTestId("np-provider"), {
        target: { value: "custom" },
      });
    });
    expect(screen.getByTestId("np-command")).toBeInTheDocument();
    expect(screen.queryByTestId("np-model")).not.toBeInTheDocument();
  });

  test("provider with base_url exposes editable Base URL field", async () => {
    const api = await import("../src/ts/api.ts");
    const fetchSpy = api.fetchProviders as ReturnType<typeof vi.fn>;
    const original = fetchSpy.getMockImplementation();
    fetchSpy.mockResolvedValue([
      {
        id: "lmstudio",
        name: "LM Studio",
        base_url: "http://localhost:1234/v1",
        online: true,
        models: [{ id: "qwen/qwen3-coder", name: "qwen/qwen3-coder" }],
      },
    ]);
    try {
      await act(async () => {
        render(<App />);
      });
      await act(async () => {
        fireEvent.click(screen.getByTestId("open-launch"));
      });
      await act(async () => {
        fireEvent.click(screen.getByTestId("new-profile-toggle"));
      });
      await act(async () => {
        fireEvent.change(screen.getByTestId("np-provider"), {
          target: { value: "lmstudio" },
        });
      });

      const baseUrlInput = screen.getByTestId(
        "np-base-url",
      ) as HTMLInputElement;
      expect(baseUrlInput).toBeInTheDocument();
      expect(baseUrlInput.value).toBe("http://localhost:1234/v1");
    } finally {
      if (original) fetchSpy.mockImplementation(original);
    }
  });

  test("creating an LM Studio profile sends base_url to the server", async () => {
    const api = await import("../src/ts/api.ts");
    const fetchSpy = api.fetchProviders as ReturnType<typeof vi.fn>;
    const original = fetchSpy.getMockImplementation();
    fetchSpy.mockResolvedValue([
      {
        id: "lmstudio",
        name: "LM Studio",
        base_url: "http://localhost:1234/v1",
        online: true,
        models: [{ id: "qwen/qwen3-coder", name: "qwen/qwen3-coder" }],
      },
    ]);
    const createSpy = api.createProfile as ReturnType<typeof vi.fn>;
    createSpy.mockClear();
    try {
      await act(async () => {
        render(<App />);
      });
      await act(async () => {
        fireEvent.click(screen.getByTestId("open-launch"));
      });
      await act(async () => {
        fireEvent.click(screen.getByTestId("new-profile-toggle"));
      });
      await act(async () => {
        fireEvent.change(screen.getByTestId("np-name"), {
          target: { value: "lm" },
        });
      });
      await act(async () => {
        fireEvent.change(screen.getByTestId("np-provider"), {
          target: { value: "lmstudio" },
        });
      });
      await act(async () => {
        fireEvent.change(screen.getByTestId("np-model"), {
          target: { value: "qwen/qwen3-coder" },
        });
      });
      await act(async () => {
        fireEvent.click(screen.getByTestId("create-and-launch"));
      });

      expect(createSpy).toHaveBeenCalled();
      const payload = createSpy.mock.calls[0][0];
      expect(payload.llm_provider).toBe("lmstudio");
      expect(payload.base_url).toBe("http://localhost:1234/v1");
    } finally {
      if (original) fetchSpy.mockImplementation(original);
    }
  });
});

describe("RegularLayout", () => {
  test("layout container is present", async () => {
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByTestId("layout-container")).toBeInTheDocument();
  });

  test("all panel frames are rendered in the DOM", async () => {
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByTestId("panel-status")).toBeInTheDocument();
    expect(screen.getByTestId("panel-chat")).toBeInTheDocument();
    expect(screen.getByTestId("panel-logs")).toBeInTheDocument();
    expect(screen.getByTestId("panel-messages")).toBeInTheDocument();
    expect(screen.getByTestId("panel-traces")).toBeInTheDocument();
    expect(screen.getByTestId("panel-profiles")).toBeInTheDocument();
  });

  test("all nav tabs are rendered", async () => {
    await act(async () => {
      render(<App />);
    });
    for (const id of [
      "status",
      "chat",
      "logs",
      "messages",
      "traces",
      "profiles",
    ]) {
      expect(screen.getByTestId(`tab-${id}`)).toBeInTheDocument();
    }
  });

  test("status tab is active by default", async () => {
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByTestId("tab-status")).toHaveClass("active");
  });

  test("other tabs are not active by default", async () => {
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByTestId("tab-chat")).not.toHaveClass("active");
    expect(screen.getByTestId("tab-logs")).not.toHaveClass("active");
    expect(screen.getByTestId("tab-messages")).not.toHaveClass("active");
    expect(screen.getByTestId("tab-traces")).not.toHaveClass("active");
    expect(screen.getByTestId("tab-profiles")).not.toHaveClass("active");
  });

  test("panel content is always accessible (status)", async () => {
    await act(async () => {
      render(<App />);
    });
    // Status panel content should be in the DOM regardless of layout state
    expect(screen.getByTestId("no-agents")).toBeInTheDocument();
  });

  test("clicking a nav tab does not throw", async () => {
    await act(async () => {
      render(<App />);
    });
    // togglePanel calls insertPanel/removePanel on the web component stub
    await act(async () => {
      fireEvent.click(screen.getByTestId("tab-chat"));
    });
    // Should not crash — mock methods are no-ops
    expect(screen.getByTestId("langley-app")).toBeInTheDocument();
  });

  test("clicking the same nav tab twice does not duplicate panels", async () => {
    await act(async () => {
      render(<App />);
    });
    const layoutEl = screen.getByTestId("layout-container") as HTMLElement & {
      getPanel: (n: string) => unknown;
      insertPanel: (n: string) => void;
    };

    // Open chat
    await act(async () => {
      fireEvent.click(screen.getByTestId("tab-chat"));
    });
    expect(layoutEl.getPanel("chat")).not.toBeNull();

    // Spy on insertPanel; clicking again on an active panel should remove
    // (toggle), not insert a second copy.
    const insertSpy = vi.spyOn(layoutEl, "insertPanel");
    await act(async () => {
      fireEvent.click(screen.getByTestId("tab-chat"));
    });
    expect(insertSpy).not.toHaveBeenCalled();
    expect(layoutEl.getPanel("chat")).toBeNull();
  });

  test("status panel is not duplicated when default-inserted by initial route", async () => {
    await act(async () => {
      render(<App />);
    });
    const layoutEl = screen.getByTestId("layout-container") as HTMLElement & {
      getPanel: (n: string) => unknown;
      insertPanel: (n: string) => void;
    };
    // Status should be present exactly once after mount.
    expect(layoutEl.getPanel("status")).not.toBeNull();

    const insertSpy = vi.spyOn(layoutEl, "insertPanel");
    // Clicking the status nav tab while status is active should remove,
    // not duplicate.
    await act(async () => {
      fireEvent.click(screen.getByTestId("tab-status"));
    });
    expect(insertSpy).not.toHaveBeenCalled();
  });

  test("pointercancel scrubs stale .overlay class from layout children", async () => {
    await act(async () => {
      render(<App />);
    });
    const layoutEl = screen.getByTestId("layout-container") as HTMLElement;
    // Simulate the regular-layout 0.4 bug: a frame is left with the
    // ".overlay" class because the lib's clear(null, ...) early-returned.
    const ghost = document.createElement("regular-layout-frame");
    ghost.setAttribute("name", "status");
    ghost.classList.add("overlay");
    layoutEl.appendChild(ghost);

    expect(ghost.classList.contains("overlay")).toBe(true);

    await act(async () => {
      window.dispatchEvent(new Event("pointercancel"));
      // setTimeout(0) inside the cleanup needs the timer to advance
      vi.advanceTimersByTime(5);
    });

    expect(ghost.classList.contains("overlay")).toBe(false);
  });

  test("clicking nav tab brings hidden panel to foreground instead of closing it", async () => {
    await act(async () => {
      render(<App />);
    });
    const layoutEl = screen.getByTestId("layout-container") as HTMLElement & {
      save: () => unknown;
      restore: (t: unknown) => void;
      insertPanel: (n: string) => void;
      removePanel: (n: string) => void;
      getPanel: (n: string) => unknown;
    };
    // Start: status only. Open chat — it becomes the selected tab and status
    // is now hidden behind it (single tab-layout in the mock).
    await act(async () => {
      fireEvent.click(screen.getByTestId("tab-chat"));
    });
    const tree = layoutEl.save() as {
      tabs: string[];
      selected: number;
    };
    expect(tree.tabs).toContain("status");
    expect(tree.tabs[tree.selected]).toBe("chat");

    const removeSpy = vi.spyOn(layoutEl, "removePanel");
    const restoreSpy = vi.spyOn(layoutEl, "restore");
    // Now click status — it should foreground, NOT remove.
    await act(async () => {
      fireEvent.click(screen.getByTestId("tab-status"));
    });
    expect(removeSpy).not.toHaveBeenCalled();
    expect(restoreSpy).toHaveBeenCalled();
    const after = layoutEl.save() as {
      tabs: string[];
      selected: number;
    };
    expect(after.tabs[after.selected]).toBe("status");
  });

  test("clicking nav tab on the visible panel closes it", async () => {
    await act(async () => {
      render(<App />);
    });
    const layoutEl = screen.getByTestId("layout-container") as HTMLElement & {
      getPanel: (n: string) => unknown;
    };
    expect(layoutEl.getPanel("status")).not.toBeNull();
    await act(async () => {
      fireEvent.click(screen.getByTestId("tab-status"));
    });
    expect(layoutEl.getPanel("status")).toBeNull();
  });
});

// ── extractPanelNames ──────────────────────────────────────

describe("extractPanelNames", () => {
  test("returns empty set for null/undefined", () => {
    expect(extractPanelNames(null).size).toBe(0);
    expect(extractPanelNames(undefined).size).toBe(0);
  });

  test("returns empty set for non-object primitives", () => {
    expect(extractPanelNames(42).size).toBe(0);
    expect(extractPanelNames("string").size).toBe(0);
    expect(extractPanelNames(true).size).toBe(0);
  });

  test("returns empty set for empty object", () => {
    expect(extractPanelNames({}).size).toBe(0);
  });

  test("extracts names from a single child-panel (TabLayout)", () => {
    const layout = {
      type: "child-panel",
      child: ["status"],
      selected: 0,
    };
    const names = extractPanelNames(layout);
    expect(names).toEqual(new Set(["status"]));
  });

  test("extracts all tab names from a child-panel with multiple tabs", () => {
    const layout = {
      type: "child-panel",
      child: ["status", "chat", "logs"],
      selected: 1,
    };
    const names = extractPanelNames(layout);
    expect(names).toEqual(new Set(["status", "chat", "logs"]));
  });

  test("extracts names from a split-panel with child-panel children", () => {
    const layout = {
      type: "split-panel",
      children: [
        { type: "child-panel", child: ["status"], selected: 0 },
        { type: "child-panel", child: ["chat"], selected: 0 },
      ],
      sizes: [0.5, 0.5],
      orientation: "horizontal",
    };
    const names = extractPanelNames(layout);
    expect(names).toEqual(new Set(["status", "chat"]));
  });

  test("extracts names from deeply nested split-panels", () => {
    const layout = {
      type: "split-panel",
      children: [
        {
          type: "split-panel",
          children: [
            { type: "child-panel", child: ["status"], selected: 0 },
            { type: "child-panel", child: ["logs"], selected: 0 },
          ],
          sizes: [0.5, 0.5],
          orientation: "vertical",
        },
        { type: "child-panel", child: ["chat", "messages"], selected: 0 },
      ],
      sizes: [0.6, 0.4],
      orientation: "horizontal",
    };
    const names = extractPanelNames(layout);
    expect(names).toEqual(new Set(["status", "logs", "chat", "messages"]));
  });

  test("extracts all six panels from a complex layout", () => {
    const layout = {
      type: "split-panel",
      children: [
        {
          type: "split-panel",
          children: [
            { type: "child-panel", child: ["status", "profiles"], selected: 0 },
            { type: "child-panel", child: ["chat"], selected: 0 },
          ],
          sizes: [0.5, 0.5],
          orientation: "vertical",
        },
        {
          type: "split-panel",
          children: [
            { type: "child-panel", child: ["logs", "traces"], selected: 0 },
            { type: "child-panel", child: ["messages"], selected: 0 },
          ],
          sizes: [0.5, 0.5],
          orientation: "vertical",
        },
      ],
      sizes: [0.5, 0.5],
      orientation: "horizontal",
    };
    const names = extractPanelNames(layout);
    expect(names).toEqual(
      new Set(["status", "profiles", "chat", "logs", "traces", "messages"]),
    );
  });

  test("handles empty child array", () => {
    const layout = { type: "child-panel", child: [], selected: 0 };
    expect(extractPanelNames(layout).size).toBe(0);
  });

  test("handles split-panel with empty children array", () => {
    const layout = {
      type: "split-panel",
      children: [],
      sizes: [],
      orientation: "horizontal",
    };
    expect(extractPanelNames(layout).size).toBe(0);
  });

  test("ignores unknown node types", () => {
    const layout = { type: "unknown-panel", child: ["status"] };
    expect(extractPanelNames(layout).size).toBe(0);
  });

  test("accepts a single-string tabs/child value (regular-layout 0.4 form)", () => {
    // The 0.4 schema shows `{ type: "tab-layout", tabs: "sidebar" }` in
    // its docs as a valid form, so we accept a bare string in both
    // schema spellings.
    expect(extractPanelNames({ type: "child-panel", child: "status" })).toEqual(
      new Set(["status"]),
    );
    expect(extractPanelNames({ type: "tab-layout", tabs: "status" })).toEqual(
      new Set(["status"]),
    );
  });

  test("does not use a 'tabs' field (regression for infinite recursion bug)", () => {
    // Both 0.2-era (`child-panel` + `child`) and 0.4-era
    // (`tab-layout` + `tabs`) schemas must be recognized.  The bug this
    // test guards against: forgetting to update extractPanelNames after
    // the regular-layout schema rename, which causes detectEmpty=true,
    // which triggers re-insert "status" forever, which causes either an
    // infinite loop (RESULT_CODE_HUNG) or duplicate tabs.
    expect(
      extractPanelNames({
        type: "child-panel",
        child: ["status"],
        selected: 0,
      }),
    ).toEqual(new Set(["status"]));

    expect(
      extractPanelNames({
        type: "tab-layout",
        tabs: ["status"],
        selected: 0,
      }),
    ).toEqual(new Set(["status"]));
  });

  test("recognizes the 0.4 'tab-layout' / 'tabs' schema", () => {
    expect(
      extractPanelNames({
        type: "tab-layout",
        tabs: ["status", "chat", "logs"],
        selected: 1,
      }),
    ).toEqual(new Set(["status", "chat", "logs"]));
  });

  test("recognizes the 0.4 'split-layout' schema", () => {
    const layout = {
      type: "split-layout",
      orientation: "horizontal",
      children: [
        { type: "tab-layout", tabs: ["status"] },
        { type: "tab-layout", tabs: ["chat", "logs"] },
      ],
      sizes: [0.5, 0.5],
    };
    expect(extractPanelNames(layout)).toEqual(
      new Set(["status", "chat", "logs"]),
    );
  });

  test("recognizes a 0.4 tab-layout with single string tabs value", () => {
    expect(extractPanelNames({ type: "tab-layout", tabs: "status" })).toEqual(
      new Set(["status"]),
    );
  });
});

// ── parseHash ──────────────────────────────────────────────

describe("parseHash", () => {
  test("defaults to status panel for empty hash", () => {
    expect(parseHash("")).toEqual({ panels: ["status"] });
    expect(parseHash("#")).toEqual({ panels: ["status"] });
    expect(parseHash("#/")).toEqual({ panels: ["status"] });
  });

  test("parses known panel names", () => {
    expect(parseHash("#status")).toEqual({ panels: ["status"] });
    expect(parseHash("#chat")).toEqual({ panels: ["chat"] });
    expect(parseHash("#logs")).toEqual({ panels: ["logs"] });
    expect(parseHash("#messages")).toEqual({ panels: ["messages"] });
    expect(parseHash("#traces")).toEqual({ panels: ["traces"] });
    expect(parseHash("#profiles")).toEqual({ panels: ["profiles"] });
  });

  test("defaults to status for unknown panel", () => {
    expect(parseHash("#unknown")).toEqual({ panels: ["status"] });
    expect(parseHash("#foo/bar")).toEqual({ panels: ["status"] });
  });

  test("parses agent deep link", () => {
    const result = parseHash("#agent/abc-123");
    expect(result.panels).toEqual(["status"]);
    expect(result.inspector).toEqual({ agentId: "abc-123" });
  });

  test("parses chat deep link with agent id", () => {
    const result = parseHash("#chat/agent-42");
    expect(result.panels).toEqual(["chat"]);
    expect(result.chatAgentId).toBe("agent-42");
  });

  test("handles leading slash in hash", () => {
    expect(parseHash("#/chat")).toEqual({ panels: ["chat"] });
    expect(parseHash("#/status")).toEqual({ panels: ["status"] });
  });
});

// ── Layout handler integration ─────────────────────────────

describe("Layout handler (insertPanel recursion guard)", () => {
  test("insertPanel is not called when panels exist in layout event", async () => {
    const insertPanelSpy = vi.fn();

    // Override the regular-layout mock to track insertPanel calls
    const origDefine = customElements.define.bind(customElements);
    const origGet = customElements.get.bind(customElements);

    // We need to re-render with a custom mock. The simplest approach is to
    // spy on the stub that was already registered.
    await act(async () => {
      render(<App />);
    });

    const layoutEl = screen.getByTestId("layout-container")
      .firstElementChild as HTMLElement & {
      insertPanel: (...args: unknown[]) => void;
    };

    if (layoutEl && layoutEl.tagName === "REGULAR-LAYOUT") {
      // Replace insertPanel with a spy
      layoutEl.insertPanel = insertPanelSpy;

      // Dispatch an update event that contains a non-empty layout
      const detail = {
        type: "child-panel",
        child: ["status"],
        selected: 0,
      };
      const event = new CustomEvent("regular-layout-update", { detail });
      await act(async () => {
        layoutEl.dispatchEvent(event);
      });

      // insertPanel should NOT be called because the layout is non-empty
      expect(insertPanelSpy).not.toHaveBeenCalled();
    }
  });

  test("insertPanel IS called with 'status' when layout event has empty panels", async () => {
    const insertPanelSpy = vi.fn();

    await act(async () => {
      render(<App />);
    });

    const layoutEl = screen.getByTestId("layout-container")
      .firstElementChild as HTMLElement & {
      insertPanel: (...args: unknown[]) => void;
    };

    if (layoutEl && layoutEl.tagName === "REGULAR-LAYOUT") {
      layoutEl.insertPanel = insertPanelSpy;

      // Dispatch an update event with an empty layout (no panels)
      const detail = {
        type: "child-panel",
        child: [],
        selected: 0,
      };
      const event = new CustomEvent("regular-layout-update", { detail });
      await act(async () => {
        layoutEl.dispatchEvent(event);
      });

      // insertPanel should be called exactly once with "status"
      expect(insertPanelSpy).toHaveBeenCalledTimes(1);
      expect(insertPanelSpy).toHaveBeenCalledWith("status");
    }
  });

  test("layout restore from localStorage does not trigger infinite recursion", async () => {
    // Simulate a saved layout in localStorage
    const savedLayout = JSON.stringify({
      type: "split-panel",
      children: [
        { type: "child-panel", child: ["status"], selected: 0 },
        { type: "child-panel", child: ["chat"], selected: 0 },
      ],
      sizes: [0.5, 0.5],
      orientation: "horizontal",
    });
    window.localStorage.setItem("langley-layout", savedLayout);

    // This should not throw or hang — if extractPanelNames is broken,
    // restore → event → insertPanel("status") → restore → ... would blow up
    await act(async () => {
      render(<App />);
    });

    // App should render successfully
    expect(screen.getByTestId("langley-app")).toBeInTheDocument();
  });
});
