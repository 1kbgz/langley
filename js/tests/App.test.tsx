import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { App, extractPanelNames, parseHash } from "../src/ts/App.tsx";
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
  return {
    LangleyWsClient: vi.fn().mockImplementation(() => ({
      connect: vi.fn(),
      disconnect: vi.fn(),
      subscribe: vi.fn().mockReturnValue(vi.fn()),
      onConnect: null,
      onDisconnect: null,
      onError: null,
    })),
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
          insertPanel() {}
          removePanel() {}
          save() {
            return null;
          }
          restore() {}
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
  localStorage.removeItem("langley-layout");
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

  test("ignores child-panel when child is not an array", () => {
    const layout = { type: "child-panel", child: "status" };
    expect(extractPanelNames(layout).size).toBe(0);
  });

  test("does not use a 'tabs' field (regression for infinite recursion bug)", () => {
    // The old buggy code used n.tabs instead of n.child.  A layout with the
    // correct `child` field but no `tabs` field must still be parsed.
    const layout = {
      type: "child-panel",
      child: ["status"],
      selected: 0,
    };
    const names = extractPanelNames(layout);
    expect(names.size).toBe(1);
    expect(names.has("status")).toBe(true);

    // Ensure a layout that has *only* a `tabs` field is NOT recognized.
    // This catches if someone accidentally re-introduces the old bug.
    const buggyLayout = {
      type: "child-panel",
      tabs: ["status"],
      selected: 0,
    } as unknown;
    const buggyNames = extractPanelNames(buggyLayout);
    expect(buggyNames.size).toBe(0);
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
    localStorage.setItem("langley-layout", savedLayout);

    // This should not throw or hang — if extractPanelNames is broken,
    // restore → event → insertPanel("status") → restore → ... would blow up
    await act(async () => {
      render(<App />);
    });

    // App should render successfully
    expect(screen.getByTestId("langley-app")).toBeInTheDocument();
  });
});
