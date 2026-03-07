import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { App } from "../src/ts/App.tsx";
import type { AgentSummary, DashboardState } from "../src/ts/App.tsx";

// Mock the api module so the app doesn't make real HTTP calls
vi.mock("../src/ts/api.ts", () => ({
  listAgents: vi.fn().mockResolvedValue([]),
  stopAgent: vi.fn().mockResolvedValue({ status: "stopping" }),
  killAgent: vi.fn().mockResolvedValue({ status: "killed" }),
  restartAgent: vi.fn().mockResolvedValue({}),
  launchAgent: vi.fn().mockResolvedValue({}),
  listProfiles: vi.fn().mockResolvedValue([]),
  createProfile: vi.fn().mockResolvedValue({ id: "p1", name: "test", version: 1 }),
  fetchActivity: vi.fn().mockResolvedValue([]),
  queryMessages: vi.fn().mockResolvedValue([]),
  sendMessageToAgent: vi.fn().mockResolvedValue({ message_id: "m1", sequence: 1 }),
  listPreconfiguredAgents: vi.fn().mockResolvedValue([]),
  getProfile: vi.fn().mockResolvedValue({}),
  deleteProfile: vi.fn().mockResolvedValue({ deleted: true }),
  listPreconfigured: vi.fn().mockResolvedValue([]),
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

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("App", () => {
  test("renders the app header", async () => {
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByText("Langley")).toBeInTheDocument();
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
    const options = screen.getByTestId("status-filter").querySelectorAll("option");
    const values = Array.from(options).map((o) => (o as HTMLOptionElement).value);
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
    expect(screen.getByTestId("no-activity")).toHaveTextContent("No recent activity.");
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
      fireEvent.change(screen.getByTestId("np-provider"), { target: { value: "openai" } });
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
      fireEvent.change(screen.getByTestId("np-provider"), { target: { value: "custom" } });
    });
    expect(screen.getByTestId("np-command")).toBeInTheDocument();
    expect(screen.queryByTestId("np-model")).not.toBeInTheDocument();
  });
});
