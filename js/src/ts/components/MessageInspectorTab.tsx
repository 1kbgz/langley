import { useState, useEffect, useCallback, useRef } from "react";
import { listChannels, queryMessages, replayMessage } from "../api.ts";
import type { ChannelInfo, MessageInfo } from "../api.ts";

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString();
}

export function MessageInspectorTab() {
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [selectedChannel, setSelectedChannel] = useState<string>("");
  const [messages, setMessages] = useState<MessageInfo[]>([]);
  const [search, setSearch] = useState("");
  const [expandedMsg, setExpandedMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [replayTarget, setReplayTarget] = useState<string>("");
  const [replayFeedback, setReplayFeedback] = useState<string | null>(null);
  const seqRef = useRef(0);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Fetch channels list
  const refreshChannels = useCallback(async () => {
    try {
      const chs = await listChannels();
      setChannels(chs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load channels");
    }
  }, []);

  useEffect(() => {
    refreshChannels();
    const interval = setInterval(refreshChannels, 10000);
    return () => clearInterval(interval);
  }, [refreshChannels]);

  // Reset when channel changes
  useEffect(() => {
    setMessages([]);
    seqRef.current = 0;
  }, [selectedChannel]);

  // Poll selected channel for messages
  useEffect(() => {
    if (!selectedChannel) return;
    const poll = async () => {
      try {
        const msgs = await queryMessages(selectedChannel, {
          from_seq: seqRef.current,
          limit: 100,
        });
        if (msgs.length > 0) {
          for (const msg of msgs) {
            if (msg.sequence > seqRef.current) seqRef.current = msg.sequence;
          }
          setMessages((prev) => [...prev, ...msgs]);
        }
      } catch {
        /* non-critical */
      }
    };
    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [selectedChannel]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, autoScroll]);

  const handleReplay = useCallback(
    async (msgId: string) => {
      if (!replayTarget) return;
      try {
        await replayMessage(selectedChannel, msgId, replayTarget);
        setReplayFeedback(`Message replayed to ${replayTarget}`);
        setTimeout(() => setReplayFeedback(null), 3000);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Replay failed");
      }
    },
    [selectedChannel, replayTarget],
  );

  const filteredMessages = messages.filter((msg) => {
    if (!search) return true;
    const s = search.toLowerCase();
    const bodyStr =
      typeof msg.body === "string" ? msg.body : JSON.stringify(msg.body);
    return (
      bodyStr.toLowerCase().includes(s) ||
      msg.sender.toLowerCase().includes(s) ||
      msg.recipient.toLowerCase().includes(s) ||
      msg.id.toLowerCase().includes(s)
    );
  });

  return (
    <div className="langley-message-inspector" data-testid="message-inspector">
      <div className="langley-message-inspector-layout">
        {/* Channel list sidebar */}
        <div className="langley-channel-list" data-testid="channel-list">
          <h3>Channels</h3>
          <button
            className="langley-btn"
            onClick={refreshChannels}
            style={{ marginBottom: 8 }}
          >
            Refresh
          </button>
          {channels.length === 0 ? (
            <div className="langley-empty">No channels found.</div>
          ) : (
            <ul className="langley-channel-items">
              {channels.map((ch) => (
                <li
                  key={ch.channel}
                  className={`langley-channel-item${selectedChannel === ch.channel ? " active" : ""}`}
                >
                  <button
                    className="langley-channel-select"
                    onClick={() => setSelectedChannel(ch.channel)}
                  >
                    <span className="langley-channel-name">{ch.channel}</span>
                    <span className="langley-channel-count">
                      {ch.message_count} msgs
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Message detail area */}
        <div className="langley-channel-detail" data-testid="channel-detail">
          {error && (
            <div className="langley-error">
              {error}
              <button
                className="langley-btn"
                onClick={() => setError(null)}
                style={{ marginLeft: 8 }}
              >
                Dismiss
              </button>
            </div>
          )}
          {replayFeedback && (
            <div className="langley-save-feedback">{replayFeedback}</div>
          )}

          {!selectedChannel ? (
            <div className="langley-empty">
              Select a channel to view messages.
            </div>
          ) : (
            <>
              <div className="langley-message-controls">
                <h3>{selectedChannel}</h3>
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search messages..."
                  className="langley-logs-search"
                  data-testid="message-search"
                />
                <label className="langley-logs-autoscroll">
                  <input
                    type="checkbox"
                    checked={autoScroll}
                    onChange={(e) => setAutoScroll(e.target.checked)}
                  />
                  Auto-scroll
                </label>
              </div>

              <div
                className="langley-message-stream"
                data-testid="message-stream"
              >
                {filteredMessages.length === 0 ? (
                  <div className="langley-empty">
                    No messages in this channel.
                  </div>
                ) : (
                  filteredMessages.map((msg) => (
                    <div
                      key={msg.id}
                      className={`langley-message-entry${expandedMsg === msg.id ? " expanded" : ""}`}
                      data-testid={`message-${msg.id}`}
                    >
                      <div
                        className="langley-message-summary"
                        onClick={() =>
                          setExpandedMsg(expandedMsg === msg.id ? null : msg.id)
                        }
                      >
                        <span className="langley-log-time">
                          {formatTime(msg.timestamp)}
                        </span>
                        <span className="langley-message-seq">
                          #{msg.sequence}
                        </span>
                        <span className="langley-message-sender">
                          {msg.sender || "—"}
                        </span>
                        <span className="langley-message-arrow">→</span>
                        <span className="langley-message-recipient">
                          {msg.recipient || "—"}
                        </span>
                        <span className="langley-message-preview">
                          {typeof msg.body === "string"
                            ? msg.body.slice(0, 80)
                            : JSON.stringify(msg.body).slice(0, 80)}
                        </span>
                      </div>
                      {expandedMsg === msg.id && (
                        <div className="langley-message-detail">
                          <dl className="langley-profile-dl">
                            <dt>Message ID</dt>
                            <dd>
                              <code>{msg.id}</code>
                            </dd>
                            <dt>Sequence</dt>
                            <dd>{msg.sequence}</dd>
                            <dt>Sender</dt>
                            <dd>{msg.sender || "—"}</dd>
                            <dt>Recipient</dt>
                            <dd>{msg.recipient || "—"}</dd>
                            <dt>Channel</dt>
                            <dd>{msg.channel}</dd>
                            <dt>Timestamp</dt>
                            <dd>
                              {new Date(msg.timestamp * 1000).toISOString()}
                            </dd>
                            <dt>Body</dt>
                            <dd>
                              <pre className="langley-message-body-pre">
                                {typeof msg.body === "string"
                                  ? msg.body
                                  : JSON.stringify(msg.body, null, 2)}
                              </pre>
                            </dd>
                          </dl>
                          <div className="langley-message-replay-bar">
                            <input
                              type="text"
                              value={replayTarget}
                              onChange={(e) => setReplayTarget(e.target.value)}
                              placeholder="Target channel for replay..."
                              className="langley-logs-search"
                            />
                            <button
                              className="langley-btn"
                              disabled={!replayTarget}
                              onClick={() => handleReplay(msg.id)}
                            >
                              Replay
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))
                )}
                <div ref={messagesEndRef} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
