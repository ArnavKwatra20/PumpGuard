import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import type { ReactNode } from 'react';
import type { DiagnosticChatMessage, PumpApi } from './api';

interface Props {
  api: PumpApi;
  pumpId: string | null;
  clientSessionId?: string;
  contextAvailable: boolean;
}

const SUGGESTIONS = [
  'Why is this pump showing a warning?',
  'Which telemetry signals support this assessment?',
  'What should an engineer inspect first?',
  'How has the pump condition changed?',
];

const displayTime = (timestamp: string) => new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

const normalizeAssistantText = (content: string) => content
  .replace(/\\\*\\\*/g, '**')
  .replace(/\r\n/g, '\n')
  .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '')
  .trim();

function inlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  return text.split(/(\*\*[^*\n]+\*\*)/g).filter(Boolean).map((part, index) => {
    const key = `${keyPrefix}-inline-${index}`;
    return part.startsWith('**') && part.endsWith('**')
      ? <strong key={key}>{part.slice(2, -2)}</strong>
      : <span key={key}>{part}</span>;
  });
}

export function renderAssistantContent(content: string): ReactNode {
  const blocks = normalizeAssistantText(content).split(/\n{2,}/).filter(Boolean);
  return blocks.map((block, blockIndex) => {
    const lines = block.split('\n');
    const bullets = lines.length > 0 && lines.every((line) => /^\s*-\s+/.test(line));
    if (bullets) {
      return <ul key={`block-${blockIndex}`}>{lines.map((line, lineIndex) => <li key={`line-${lineIndex}`}>{inlineMarkdown(line.replace(/^\s*-\s+/, ''), `block-${blockIndex}-line-${lineIndex}`)}</li>)}</ul>;
    }
    return <p key={`block-${blockIndex}`}>{lines.map((line, lineIndex) => <span key={`line-${lineIndex}`}>{lineIndex > 0 && <br />}{inlineMarkdown(line, `block-${blockIndex}-line-${lineIndex}`)}</span>)}</p>;
  });
}

export function DiagnosticChat({ api, pumpId, clientSessionId, contextAvailable }: Props) {
  const [messages, setMessages] = useState<(DiagnosticChatMessage & { provider?: 'mock' | 'amd' | 'amd_unavailable'; is_mock?: boolean })[]>([]);
  const [question, setQuestion] = useState('');
  const [sending, setSending] = useState(false);
  const [failure, setFailure] = useState<{ question: string; message: string } | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Provider status is informational. The chat endpoint is the authoritative
  // availability check and can return a clear provider failure itself.
  const chatAvailable = Boolean(api.diagnosticChat);
  useEffect(() => {
    setMessages([]);
    setQuestion('');
    setFailure(null);
  }, [pumpId, clientSessionId]);

  const send = async (value = question.trim(), retry = false) => {
    if (!value || !pumpId || !api.diagnosticChat || sending || !chatAvailable || !contextAvailable) return;
    const userMessage: DiagnosticChatMessage = { role: 'user', content: value, timestamp: new Date().toISOString() };
    const history = messages.map(({ role, content }) => ({ role, content }));
    if (!retry) setMessages((current) => [...current, userMessage]);
    setQuestion('');
    setFailure(null);
    setSending(true);
    try {
      const result = await api.diagnosticChat({ pump_id: pumpId, ...(clientSessionId ? { client_session_id: clientSessionId } : {}), question: value, history });
      setMessages((current) => [...current, { role: 'assistant', content: result.assistant_message, timestamp: new Date().toISOString(), provider: result.provider, is_mock: result.is_mock }]);
    } catch (error) {
      setFailure({ question: value, message: error instanceof Error ? error.message : 'Diagnostic assistant request failed.' });
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void send();
    }
  };

  const clear = () => {
    if (!messages.length || window.confirm('Clear this pump’s diagnostic conversation?')) {
      setMessages([]);
      setFailure(null);
      setQuestion('');
      textareaRef.current?.focus();
    }
  };

  return <section className="diagnostic-chat" aria-label="Diagnostic Assistant">
    <div className="diagnostic-chat-heading">
      <div><span className="panel-kicker">CONTEXTUAL FOLLOW-UP</span><h4>Diagnostic Assistant</h4></div>
      <button type="button" className="chat-clear-button" onClick={clear} disabled={!messages.length || sending}>Clear conversation</button>
    </div>
    <p className="diagnostic-chat-note">Answers use the selected pump’s authoritative backend telemetry and rule assessment. They do not change measurements, alerts, or controls.</p>
    <div className="diagnostic-chat-log" role="log" aria-live="polite" aria-label="Diagnostic conversation">
      {!messages.length && <p className="chat-empty">Ask a focused question about the current evidence.</p>}
      {messages.map((message, index) => <article className={`chat-message ${message.role}`} key={`${message.timestamp ?? 'message'}-${index}`}>
        <div className="chat-message-meta"><b>{message.role === 'user' ? 'YOU' : 'ASSISTANT'}</b>{message.role === 'assistant' && <span>{message.provider === 'amd' && !message.is_mock ? 'AMD-generated response' : message.is_mock ? 'TEST MOCK — not AMD-generated' : 'Provider unavailable'}</span>}<time dateTime={message.timestamp}>{message.timestamp ? displayTime(message.timestamp) : ''}</time></div>
        <div className="chat-message-content">{renderAssistantContent(message.content)}</div>
      </article>)}
      {sending && <div className="chat-loading" role="status"><span className="loading-dot" /> Consulting the configured diagnostic provider…</div>}
    </div>
    {failure && <div className="chat-error" role="alert"><span>{failure.message}</span><button type="button" onClick={() => void send(failure.question, true)} disabled={sending}>Retry</button></div>}
    <div className="chat-suggestions" aria-label="Suggested questions">
      {SUGGESTIONS.map((suggestion) => <button type="button" key={suggestion} onClick={() => { setQuestion(suggestion); textareaRef.current?.focus(); }} disabled={sending || !chatAvailable || !contextAvailable}>{suggestion}</button>)}
    </div>
    <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); void send(); }}>
      <label htmlFor="diagnostic-chat-question">Ask about this pump</label>
      <textarea ref={textareaRef} id="diagnostic-chat-question" value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={onKeyDown} placeholder={contextAvailable ? 'Ask about the current condition, evidence, or next inspection…' : 'Generate a simulation to enable contextual chat.'} maxLength={2000} rows={3} disabled={sending || !chatAvailable || !contextAvailable} />
      <div className="chat-composer-footer"><small>Enter to send · Shift+Enter for a new line</small><button type="submit" disabled={sending || !question.trim() || !chatAvailable || !contextAvailable}>{sending ? 'Sending…' : 'Send'}</button></div>
    </form>
  </section>;
}

