import { useEffect, useRef, useState } from 'react';
import { wsUrl } from '../services/api';

export function useWebSocket(channel = 'alerts', onMessage) {
  const [connected, setConnected] = useState(false);
  const onMessageRef = useRef(onMessage);

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    let ws = null;
    let retryTimer = null;
    let disposed = false;

    const connect = () => {
      if (disposed || ws?.readyState === WebSocket.OPEN) return;
      ws = new WebSocket(wsUrl(channel));

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!disposed) retryTimer = setTimeout(connect, 3000);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);
          onMessageRef.current?.(data);
        } catch {
          /* ignore malformed */
        }
      };
    };

    connect();
    return () => {
      disposed = true;
      clearTimeout(retryTimer);
      ws?.close();
    };
  }, [channel]);

  return { connected };
}
