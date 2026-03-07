/**
 * Langley WebSocket client with auto-reconnect and subscription management.
 */

export type MessageHandler = (data: Record<string, unknown>) => void;

export interface WsFrame {
  type: string;
  channel?: string;
  body?: unknown;
  headers?: Record<string, string>;
  data?: Record<string, unknown>;
  message?: string;
  message_id?: string;
  sequence?: number;
}

export class LangleyWsClient {
  private url: string;
  private ws: WebSocket | null = null;
  private subscriptions = new Map<string, Set<MessageHandler>>();
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private currentDelay = 1000;
  private shouldReconnect = true;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (err: string) => void;

  constructor(url?: string) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.url = url ?? `${proto}//${window.location.host}/ws`;
  }

  connect(): void {
    this.shouldReconnect = true;
    this._connect();
  }

  private _connect(): void {
    if (this.ws) return;
    try {
      this.ws = new WebSocket(this.url);
    } catch {
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.currentDelay = this.reconnectDelay;
      this.onConnect?.();
      // Re-subscribe to channels that were active before reconnect
      for (const channel of this.subscriptions.keys()) {
        this._sendFrame({ type: "subscribe", channel });
      }
    };

    this.ws.onmessage = (event) => {
      let frame: WsFrame;
      try {
        frame = JSON.parse(event.data) as WsFrame;
      } catch {
        return;
      }
      this._handleFrame(frame);
    };

    this.ws.onclose = () => {
      this.ws = null;
      this.onDisconnect?.();
      this._scheduleReconnect();
    };

    this.ws.onerror = () => {
      // onclose will fire after onerror
    };
  }

  disconnect(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  subscribe(channel: string, handler: MessageHandler): () => void {
    let handlers = this.subscriptions.get(channel);
    if (!handlers) {
      handlers = new Set();
      this.subscriptions.set(channel, handlers);
      // Send subscribe frame if connected
      this._sendFrame({ type: "subscribe", channel });
    }
    handlers.add(handler);

    // Return unsubscribe function
    return () => {
      handlers!.delete(handler);
      if (handlers!.size === 0) {
        this.subscriptions.delete(channel);
        this._sendFrame({ type: "unsubscribe", channel });
      }
    };
  }

  send(channel: string, body: unknown, headers?: Record<string, string>): void {
    this._sendFrame({ type: "send", channel, body, headers });
  }

  ping(): void {
    this._sendFrame({ type: "ping" });
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  private _sendFrame(frame: WsFrame): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(frame));
    }
  }

  private _handleFrame(frame: WsFrame): void {
    if (frame.type === "message" && frame.channel && frame.data) {
      const handlers = this.subscriptions.get(frame.channel);
      if (handlers) {
        for (const h of handlers) {
          h(frame.data);
        }
      }
    } else if (frame.type === "error") {
      this.onError?.(frame.message ?? "Unknown error");
    }
    // "subscribed", "unsubscribed", "pong", "sent" are acknowledged silently
  }

  private _scheduleReconnect(): void {
    if (!this.shouldReconnect) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this._connect();
    }, this.currentDelay);
    this.currentDelay = Math.min(this.currentDelay * 2, this.maxReconnectDelay);
  }
}
