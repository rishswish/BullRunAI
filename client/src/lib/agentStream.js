// Minimal SSE-over-fetch client for the agent service.
// EventSource can't send an Authorization header or a POST body, so we read the
// response stream ourselves and parse `event:` / `data:` frames.

export const AGENT_API_URL =
  import.meta.env.VITE_AGENT_API_URL || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080';

export async function streamAgent(path, body, token, onEvent, signal) {
  const res = await fetch(`${AGENT_API_URL}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok || !res.body) {
    const msg = res.status === 429 ? 'You are sending messages too quickly. Try again in a minute.'
      : res.status === 401 ? 'Your session expired. Please sign in again.'
      : `Request failed (${res.status})`;
    onEvent('error', { message: msg });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() ?? '';
    for (const frame of frames) {
      let event = 'message';
      const data = [];
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
      }
      if (!data.length) continue;
      try {
        onEvent(event, JSON.parse(data.join('\n')));
      } catch {
        onEvent(event, data.join('\n'));
      }
    }
  }
}
