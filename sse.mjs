// Shared streaming parser. Handles network chunk boundaries, CRLF and ping frames.
export async function* readSSE(stream) {
  if (!stream) throw new Error('Missing response stream');
  const reader = stream.getReader(); const decoder = new TextDecoder();
  let buffer = ''; let event = 'message'; let lines = [];
  const consume = line => {
    if (line === '') {
      const result = lines.length ? { event, data: JSON.parse(lines.join('\n')) } : null;
      event = 'message'; lines = []; return result;
    }
    if (line.startsWith('event:')) event = line.slice(6).trim();
    if (line.startsWith('data:')) lines.push(line.slice(5).replace(/^ /, ''));
    return null;
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let newline;
      while ((newline = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, newline).replace(/\r$/, ''); buffer = buffer.slice(newline + 1);
        const frame = consume(line); if (frame) yield frame;
      }
      if (buffer.length > 2 * 1024 * 1024) throw new Error('SSE frame too large');
      if (done) {
        if (buffer) consume(buffer.replace(/\r$/, ''));
        const frame = consume(''); if (frame) yield frame;
        break;
      }
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
