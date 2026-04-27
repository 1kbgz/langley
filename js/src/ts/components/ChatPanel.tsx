import { useState, useEffect, useCallback, useRef } from "react";
import { queryMessages, sendMessageToAgent } from "../api.ts";
import type { MessageInfo } from "../api.ts";
import type { LangleyWsClient } from "../ws.ts";
import { marked } from "marked";
import DOMPurify from "dompurify";

// Configure marked for safe defaults
marked.setOptions({ breaks: true, gfm: true });

function renderMarkdown(text: string): string {
  const raw = marked.parse(text);
  // raw may be string or Promise<string>; our config is synchronous
  return DOMPurify.sanitize(raw as string);
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
  type?: string;
}

/** Convert raw inbox messages into ChatMessages (user turns). */
function inboxToChatMessages(msgs: MessageInfo[]): ChatMessage[] {
  const result: ChatMessage[] = [];
  for (const msg of msgs) {
    const body = msg.body as Record<string, unknown>;
    const text = (body.text as string) ?? (body.body as string) ?? "";
    if (!text) continue;
    result.push({
      id: msg.id,
      role: "user",
      content: text,
      timestamp: msg.timestamp ?? Date.now() / 1000,
    });
  }
  return result;
}

/**
 * Convert raw outbox messages into ChatMessages (assistant / system turns).
 * Handles delta accumulation: consecutive delta messages are merged into the
 * following "message" or "turn_complete" entry.
 */
function outboxToChatMessages(
  msgs: Array<{
    id: string;
    body: Record<string, unknown>;
    timestamp?: number;
  }>,
): ChatMessage[] {
  const result: ChatMessage[] = [];
  let pending = "";
  for (const msg of msgs) {
    const body = msg.body;
    const type = (body.type as string) ?? "";
    if (type === "delta") {
      pending += (body.content as string) ?? "";
    } else if (type === "message" || type === "turn_complete") {
      const content = pending || (body.content as string) || "";
      pending = "";
      if (content) {
        result.push({
          id: msg.id,
          role: "assistant",
          content,
          timestamp:
            (body.timestamp as number) ?? msg.timestamp ?? Date.now() / 1000,
          type: "message",
        });
      }
    } else if (type === "tool_start") {
      result.push({
        id: msg.id,
        role: "system",
        content: `Using tool: ${body.tool_name}`,
        timestamp:
          (body.timestamp as number) ?? msg.timestamp ?? Date.now() / 1000,
        type: "tool",
      });
    } else if (type === "error") {
      result.push({
        id: msg.id,
        role: "system",
        content: `Error: ${body.message}`,
        timestamp:
          (body.timestamp as number) ?? msg.timestamp ?? Date.now() / 1000,
        type: "error",
      });
    }
  }
  return result;
}

// Hard cap on chat history to keep React from choking on long sessions.
const MAX_CHAT_MESSAGES = 500;

/** Merge two ChatMessage arrays by id, sort by timestamp, cap to last N. */
function mergeMessages(
  existing: ChatMessage[],
  incoming: ChatMessage[],
): ChatMessage[] {
  const map = new Map<string, ChatMessage>();
  for (const m of existing) map.set(m.id, m);
  for (const m of incoming) map.set(m.id, m);
  const merged = Array.from(map.values()).sort(
    (a, b) => a.timestamp - b.timestamp,
  );
  return merged.length > MAX_CHAT_MESSAGES
    ? merged.slice(merged.length - MAX_CHAT_MESSAGES)
    : merged;
}

/** Single chat message with markdown rendering and raw toggle. */
function ChatMessageBubble({ msg }: { msg: ChatMessage }) {
  const [showRaw, setShowRaw] = useState(false);

  return (
    <div
      className={`langley-chat-message langley-chat-${msg.role}`}
      data-testid={`chat-msg-${msg.id}`}
    >
      <div className="langley-chat-meta">
        <span className="langley-chat-role">{msg.role}</span>
        <button
          className="langley-chat-raw-toggle"
          onClick={() => setShowRaw((v) => !v)}
          title={showRaw ? "Show rendered" : "Show raw"}
          data-testid={`chat-raw-toggle-${msg.id}`}
        >
          {showRaw ? "rendered" : "raw"}
        </button>
      </div>
      {showRaw ? (
        <pre className="langley-chat-content langley-chat-raw">
          {msg.content}
        </pre>
      ) : (
        <div
          className="langley-chat-content langley-chat-markdown"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
        />
      )}
    </div>
  );
}

export function ChatPanel({
  agentId,
  agentName,
  wsClient,
  onClose,
}: {
  agentId: string;
  agentName: string;
  wsClient?: LangleyWsClient | null;
  onClose?: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const outboxSeqRef = useRef(0);
  const inboxSeqRef = useRef(0);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const pendingContentRef = useRef("");

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "auto" });
  }, []);

  // Reset state when agent changes
  useEffect(() => {
    setMessages([]);
    outboxSeqRef.current = 0;
    inboxSeqRef.current = 0;
    pendingContentRef.current = "";
  }, [agentId]);

  // Subscribe to outbox via WebSocket for real-time delivery, with HTTP
  // polling as a catch-up / reconnection safety net.  On mount the poll
  // replays both inbox (user turns) and outbox (assistant turns) so the
  // full conversation history is restored.
  useEffect(() => {
    const outboxChannel = `agent.${agentId}.outbox`;
    const inboxChannel = `agent.${agentId}.inbox`;

    const poll = async () => {
      try {
        // Fetch outbox (assistant) messages
        const outboxMsgs = await queryMessages(outboxChannel, {
          from_seq: outboxSeqRef.current,
          limit: 100,
        });
        // Fetch inbox (user) messages
        const inboxMsgs = await queryMessages(inboxChannel, {
          from_seq: inboxSeqRef.current,
          limit: 100,
        });

        // Advance sequence cursors
        for (const m of outboxMsgs) {
          if (m.sequence > outboxSeqRef.current)
            outboxSeqRef.current = m.sequence;
        }
        for (const m of inboxMsgs) {
          if (m.sequence > inboxSeqRef.current)
            inboxSeqRef.current = m.sequence;
        }

        // Convert to ChatMessages
        const assistantMsgs = outboxToChatMessages(
          outboxMsgs.map((m) => ({
            id: m.id,
            body: m.body as Record<string, unknown>,
            timestamp: m.timestamp,
          })),
        );
        const userMsgs = inboxToChatMessages(inboxMsgs);

        const incoming = [...assistantMsgs, ...userMsgs];
        if (incoming.length > 0) {
          setMessages((prev) => mergeMessages(prev, incoming));
        }
      } catch {
        // Non-critical polling error
      }
    };

    // Initial catch-up (replays full history since seqRefs start at 0)
    poll();
    const interval = setInterval(poll, 3000);

    // WebSocket subscription for real-time outbox delivery
    let unsubWs: (() => void) | undefined;
    if (wsClient) {
      unsubWs = wsClient.subscribe(outboxChannel, (data) => {
        const seq = (data.sequence as number) ?? 0;
        if (seq && seq <= outboxSeqRef.current) return;
        if (seq > outboxSeqRef.current) outboxSeqRef.current = seq;

        const body = (data.body ?? data) as Record<string, unknown>;
        const id = (data.id as string) ?? `ws-${Date.now()}`;
        const type = (body.type as string) ?? "";

        if (type === "delta") {
          pendingContentRef.current += (body.content as string) ?? "";
          return;
        }

        const incoming = outboxToChatMessages([
          { id, body, timestamp: body.timestamp as number },
        ]);

        // If there's accumulated delta content and we got a message/turn_complete,
        // use the pending content instead
        if (
          (type === "message" || type === "turn_complete") &&
          pendingContentRef.current
        ) {
          const content = pendingContentRef.current;
          pendingContentRef.current = "";
          if (content) {
            const ts = (body.timestamp as number) ?? Date.now() / 1000;
            setMessages((prev) =>
              mergeMessages(prev, [
                {
                  id,
                  role: "assistant",
                  content,
                  timestamp: ts,
                  type: "message",
                },
              ]),
            );
            return;
          }
        }

        if (incoming.length > 0) {
          setMessages((prev) => mergeMessages(prev, incoming));
        }
      });
    }

    return () => {
      clearInterval(interval);
      unsubWs?.();
    };
  }, [agentId, wsClient]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setSending(true);
    setInput("");

    // Optimistic user message with a temporary id
    const tempId = `user-${Date.now()}`;
    const userMsg: ChatMessage = {
      id: tempId,
      role: "user",
      content: text,
      timestamp: Date.now() / 1000,
    };
    setMessages((prev) => mergeMessages(prev, [userMsg]));

    try {
      const receipt = await sendMessageToAgent(agentId, { text });
      // Replace the temp id with the real transport id so the inbox
      // poll won't create a duplicate entry.
      setMessages((prev) =>
        prev.map((m) =>
          m.id === tempId ? { ...m, id: receipt.message_id } : m,
        ),
      );
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: "system",
          content: "Failed to send message",
          timestamp: Date.now() / 1000,
          type: "error",
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="langley-chat-panel" data-testid="chat-panel">
      <div className="langley-chat-header">
        <h3>Chat — {agentName}</h3>
        {onClose && (
          <button
            className="langley-btn"
            onClick={onClose}
            data-testid="close-chat"
          >
            &times;
          </button>
        )}
      </div>
      <div className="langley-chat-messages" data-testid="chat-messages">
        {messages.length === 0 && (
          <p className="langley-empty">
            No messages yet. Send a prompt to get started.
          </p>
        )}
        {messages.map((msg) => (
          <ChatMessageBubble key={msg.id} msg={msg} />
        ))}
        <div ref={messagesEndRef} />
      </div>
      <div className="langley-chat-input">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          placeholder="Type a message..."
          disabled={sending}
          data-testid="chat-input"
        />
        <button
          className="langley-btn langley-btn-primary"
          onClick={handleSend}
          disabled={sending || !input.trim()}
          data-testid="chat-send"
        >
          Send
        </button>
      </div>
    </div>
  );
}
