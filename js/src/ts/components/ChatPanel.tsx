import { useState, useEffect, useCallback, useRef } from "react";
import { queryMessages, sendMessageToAgent } from "../api.ts";

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
  type?: string;
}

export function ChatPanel({
  agentId,
  agentName,
  onClose,
}: {
  agentId: string;
  agentName: string;
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
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  // Reset state when agent changes
  useEffect(() => {
    setMessages([]);
    outboxSeqRef.current = 0;
    inboxSeqRef.current = 0;
    pendingContentRef.current = "";
  }, [agentId]);

  // Poll outbox for agent responses
  useEffect(() => {
    const outboxChannel = `agent.${agentId}.outbox`;
    const inboxChannel = `agent.${agentId}.inbox`;

    const poll = async () => {
      try {
        const outboxMsgs = await queryMessages(outboxChannel, {
          from_seq: outboxSeqRef.current,
          limit: 50,
        });
        if (outboxMsgs.length > 0) {
          const newMessages: ChatMessage[] = [];
          for (const msg of outboxMsgs) {
            const body = msg.body as Record<string, unknown>;
            if (msg.sequence > outboxSeqRef.current) outboxSeqRef.current = msg.sequence;

            const type = (body.type as string) ?? "";
            if (type === "delta") {
              pendingContentRef.current += (body.content as string) ?? "";
            } else if (type === "message" || type === "turn_complete") {
              const content = pendingContentRef.current || (body.content as string) || "";
              pendingContentRef.current = "";
              if (content) {
                newMessages.push({
                  id: msg.id,
                  role: "assistant",
                  content,
                  timestamp: (body.timestamp as number) ?? Date.now() / 1000,
                  type: "message",
                });
              }
            } else if (type === "tool_start") {
              newMessages.push({
                id: msg.id,
                role: "system",
                content: `Using tool: ${body.tool_name}`,
                timestamp: (body.timestamp as number) ?? Date.now() / 1000,
                type: "tool",
              });
            } else if (type === "error") {
              newMessages.push({
                id: msg.id,
                role: "system",
                content: `Error: ${body.message}`,
                timestamp: (body.timestamp as number) ?? Date.now() / 1000,
                type: "error",
              });
            }
          }
          if (newMessages.length > 0) {
            setMessages((prev) => [...prev, ...newMessages]);
          }
        }

        const inboxMsgs = await queryMessages(inboxChannel, {
          from_seq: inboxSeqRef.current,
          limit: 50,
        });
        if (inboxMsgs.length > 0) {
          for (const msg of inboxMsgs) {
            if (msg.sequence > inboxSeqRef.current) inboxSeqRef.current = msg.sequence;
          }
        }
      } catch {
        // Non-critical polling error
      }
    };

    poll();
    const interval = setInterval(poll, 1000);
    return () => clearInterval(interval);
  }, [agentId]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setSending(true);
    setInput("");

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
      timestamp: Date.now() / 1000,
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      await sendMessageToAgent(agentId, { text });
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
          <button className="langley-btn" onClick={onClose} data-testid="close-chat">
            &times;
          </button>
        )}
      </div>
      <div className="langley-chat-messages" data-testid="chat-messages">
        {messages.length === 0 && (
          <p className="langley-empty">No messages yet. Send a prompt to get started.</p>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`langley-chat-message langley-chat-${msg.role}`}
            data-testid={`chat-msg-${msg.id}`}
          >
            <div className="langley-chat-role">{msg.role}</div>
            <div className="langley-chat-content">{msg.content}</div>
          </div>
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
