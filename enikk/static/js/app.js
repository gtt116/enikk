// Main Alpine.js application component

function chatApp() {
  return {
    sessions: [],
    activeSessionId: null,
    inputText: '',
    isTyping: false,
    _streamingMsg: null,
    errorMessage: '',
    _errorTimer: null,

    showThinking: true,
    thinkingExpanded: true,

    showToolCalls: true,
    toolCallsExpanded: false,
    eventSource: null,
    sidebarCollapsed: false,
    showUserMenu: false,
    showConfigModal: false,
    configTab: 'basic',
    config: {
      model: { default: '', provider: '', base_url: '', api_key: '', max_tokens: 65535, context_length: 262144 },
      im: { platforms: { qqbot: { enabled: false, token: '', extra: { app_id: '', client_secret: '' } } } },
      workspace: { screenshot_dir: '', weights_dir: '', screenshot_max_dim: 1366, max_iterations: 120 },
      memory: { memory_enabled: true, nudge_interval: 10, creation_nudge_interval: 10 },
      log_level: 'INFO'
    },
    configSaving: false,
    imTesting: false,
    imTestResult: '',
    showAppId: false,
    showClientSecret: false,
    configSaved: false,
    modelTesting: false,
    modelTestResult: '',
    systemStatus: { icon_finder: { available: false, message: '' }, ocr: { available: false, message: '' }, im: { enabled: false, connected: false, platform: null } },
    iconFinderTooltip: false,
    ocrTooltip: false,
    imTooltip: false,
    apps: [],
    showAppEditor: false,
    appEditor: { editing: false, name: '', app_path: '', launcher_path: '', launch_timeout: 120 },
    providers: [],
    contextLengthMode: 'auto',
    appVersion: '',
    _nextUid: 1,  // unique ID counter for message parts
    _scrollTimer: null,
    _streamMsgVer: 0,  // version counter to force x-for re-evaluation on SSE events
    _showJumpBottom: false,
    currentLang: 'zh-CN',
    currentTipText: '',
    // Register currentLang as a reactive dependency so Alpine re-evaluates all t() bindings when language changes
    t(key, ...args) { void this.currentLang; return t(key, ...args); },

    init() {
      this.currentLang = currentLang;
      window.addEventListener('language-changed', () => {
        this.currentLang = currentLang;
        this.$nextTick(() => this.$refs.inputRef?.focus());
      });
      this.fetchSessions();
      this.fetchSystemStatus();
      fetch('/api/version').then(r => r.ok ? r.json() : null).then(d => { if (d) this.appVersion = 'v' + d.version; }).catch(() => {});
      this._systemStatusTimer = setInterval(() => this.fetchSystemStatus(), 5000);
      // Initialize and rotate tips every 8 seconds (random order)
      const tips = () => [t('chat.stop_hint'), t('chat.teach_hint'), t('chat.images_hint'), t('chat.admin_hint'), t('chat.mouse_hint')];
      let lastTipIndex = -1;
      const getRandomTipIndex = () => {
        const allTips = tips();
        let newIndex = Math.floor(Math.random() * allTips.length);
        // Avoid repeating the same tip consecutively
        while (newIndex === lastTipIndex) {
          newIndex = Math.floor(Math.random() * allTips.length);
        }
        lastTipIndex = newIndex;
        return newIndex;
      };
      this.currentTipText = tips()[getRandomTipIndex()];
      if (this._tipTimer) {
        clearInterval(this._tipTimer);
      }
      this._tipTimer = setInterval(() => {
        this.currentTipText = tips()[getRandomTipIndex()];
      }, 8000);
      this.$nextTick(() => { this.initMarked(); });
      window.addEventListener('popstate', (e) => {
        const sessionId = e.state?.sessionId || new URLSearchParams(window.location.search).get('session');
        if (sessionId && this.sessions.some(s => s.id === sessionId)) {
          this.switchSession(sessionId);
        }
      });
    },

    async changeLanguage(lang) {
      setLang(lang);
      try {
        await fetch('/api/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ language: lang })
        });
      } catch (e) {
        console.error('Failed to save language to config:', e);
      }
    },

    shakeModal() {
      const modal = document.getElementById('config-modal-content');
      modal.classList.remove('shake');
      void modal.offsetWidth;
      modal.classList.add('shake');
    },

    async fetchApps() {
      try {
        const resp = await fetch('/api/apps');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        this.apps = data.apps || [];
      } catch (e) {
        console.error('Failed to fetch apps:', e);
      }
    },

    addApp() {
      this.appEditor = { editing: false, name: '', app_path: '', launcher_path: '', launch_timeout: 120 };
      this.showAppEditor = true;
    },

    editApp(app) {
      this.appEditor = {
        editing: true,
        name: app.name,
        app_path: app.app_path,
        launcher_path: app.launcher_path || '',
        launch_timeout: app.launch_timeout || 120,
      };
      this.showAppEditor = true;
    },

    async saveApp() {
      if (!this.appEditor.name.trim()) {
        this.showError(this.t('apps.name_required'));
        return;
      }
      if (!this.appEditor.app_path.trim()) {
        this.showError(this.t('apps.path_required'));
        return;
      }
      try {
        const method = this.appEditor.editing ? 'PUT' : 'POST';
        const url = this.appEditor.editing ? `/api/apps/${this.appEditor.name}` : '/api/apps';
        const resp = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: this.appEditor.name,
            app_path: this.appEditor.app_path,
            launcher_path: this.appEditor.launcher_path || null,
            launch_timeout: this.appEditor.launch_timeout,
          }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.detail || 'HTTP ' + resp.status);
        }
        this.showAppEditor = false;
        await this.fetchApps();
      } catch (e) {
        this.showError(this.t('apps.save_failed') + ': ' + e.message);
      }
    },

    async deleteApp(name) {
      if (!confirm(this.t('apps.confirm_delete').replace('{name}', name))) return;
      try {
        const resp = await fetch(`/api/apps/${name}`, { method: 'DELETE' });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.detail || 'HTTP ' + resp.status);
        }
        await this.fetchApps();
      } catch (e) {
        this.showError(this.t('apps.delete_failed') + ': ' + e.message);
      }
    },

    async pickFile(target, ext) {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_file) {
        try {
          const fileTypes = ext ? `*.${ext}` : '';
          const result = await window.pywebview.api.pick_file(fileTypes);
          if (result) {
            const parts = target.split('.');
            if (parts.length === 2) {
              this[parts[0]][parts[1]] = result;
            }
          }
        } catch (e) {
          console.error('File picker failed:', e);
        }
      } else {
        alert('File picker requires pywebview runtime');
      }
    },

    async fetchSystemStatus() {
      try {
        const resp = await fetch('/api/status');
        if (resp.ok) this.systemStatus = await resp.json();
      } catch (e) {
        // silent
      }
    },

    async fetchSessions() {
      try {
        const resp = await fetch('/api/sessions?limit=50');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        this.sessions = data.map(s => {
          const sess = {
            id: s.id,
            title: s.title || s.preview || s.id.slice(0, 12),
            createdAt: new Date(s.started_at * 1000),
            messages: [],
            messageCount: s.message_count,
            isRunning: s.is_running || false,
          };
          return sess;
        });
        if (this.sessions.length && !this.activeSessionId) {
          const urlSessionId = new URLSearchParams(window.location.search).get('session');
          const targetId = urlSessionId && this.sessions.some(s => s.id === urlSessionId)
            ? urlSessionId
            : this.sessions[0].id;
          this.switchSession(targetId);
        }
      } catch (e) {
        console.error('Failed to fetch sessions:', e);
      }
    },

    initMarked() {
      marked.setOptions({
        highlight: (code, lang) => {
          if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, { language: lang }).value;
          return hljs.highlightAuto(code).value;
        },
        breaks: true, gfm: true,
      });
    },

    renderMarkdown(text) {
      if (!text) return '';
      return marked.parse(text);
    },

    isToolError(part) {
      if (part.error) return true;
      if (part.result && typeof part.result === 'string') {
        try {
          const obj = JSON.parse(part.result);
          return obj && obj.error;
        } catch { return false; }
      }
      return false;
    },

    prettyJson(text) {
      if (!text) return '';
      try {
        const obj = typeof text === 'string' ? JSON.parse(text) : text;
        return JSON.stringify(obj, null, 2);
      } catch {
        return text;
      }
    },

    formatTime(ts) {
      if (!ts) return '';
      void this.currentLang;
      const ms = String(Math.floor((ts % 1) * 1000)).padStart(3, '0');
      const d = new Date(ts * 1000);
      const now = new Date();
      const locale = currentLang === 'zh-CN' ? 'zh-CN' : 'en-US';
      const time = d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + '.' + ms;
      if (d.toDateString() === now.toDateString()) return time;
      const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
      if (d.toDateString() === yesterday.toDateString()) return this.t('time.yesterday') + ' ' + time;
      return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + time;
    },

    getMsgText(msg) {
      if (msg.parts && msg.parts.length) {
        return msg.parts.filter(p => p.type === 'content').map(p => p.content).join('\n\n');
      }
      return msg.content || '';
    },

    activeMessages() {
      const s = this.sessions.find(s => s.id === this.activeSessionId);
      if (!s) return [];
      const msgs = [...s.messages];
      if (this._streamingMsg) msgs.push(this._streamingMsg);
      return msgs;
    },

    activeSession() {
      return this.sessions.find(s => s.id === this.activeSessionId) || null;
    },

    groupedSessions() {
      const now = Date.now(), day = 86400000;
      const groups = [
        { label: this.t('time.today'), sessions: [] }, { label: this.t('time.yesterday'), sessions: [] },
        { label: this.t('time.last_7_days'), sessions: [] }, { label: this.t('time.older'), sessions: [] },
      ];
      this.sessions.forEach(s => {
        const diff = now - new Date(s.createdAt).getTime();
        if (diff < day) groups[0].sessions.push(s);
        else if (diff < 2*day) groups[1].sessions.push(s);
        else if (diff < 7*day) groups[2].sessions.push(s);
        else groups[3].sessions.push(s);
      });
      return groups.filter(g => g.sessions.length > 0);
    },

    newChat() {
      if (this.eventSource) {
        this.eventSource.close();
        this.eventSource = null;
      }
      this.isTyping = false;
      this._streaming = false;
      this._streamingMsg = null;
      this.activeSessionId = null;
      history.pushState({}, '', window.location.pathname);
      this.$nextTick(() => this.$refs.inputRef.focus());
    },

    switchSession(id) {
      if (this.eventSource) {
        this.eventSource.close();
        this.eventSource = null;
      }
      this.isTyping = false;
      this._streaming = false;
      this._streamingMsg = null;
      this.activeSessionId = id;
      history.pushState({ sessionId: id }, '', `?session=${id}`);
      const session = this.sessions.find(s => s.id === id);
      if (session && !session._loaded) {
        session._loaded = true;
        this.loadSessionMessages(id).then(() => {
          if (session.isRunning) {
            this.isTyping = true;
            this._streaming = true;
            this._streamingMsg = { role: 'assistant', content: '', images: [], parts: [], _streaming: true };
            this.startStream(session);
          }
        });
      } else if (session && session.isRunning) {
        this.isTyping = true;
        this._streaming = true;
        this._streamingMsg = { role: 'assistant', content: '', images: [], parts: [], _streaming: true };
        this.startStream(session);
      }
      this.$nextTick(() => this.scrollToBottom());
    },

    async loadSessionMessages(sessionId) {
      try {
        const resp = await fetch('/api/sessions/' + sessionId + '/messages?limit=100');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        const session = this.sessions.find(s => s.id === sessionId);
        if (!session) return;
        if (this._streaming) return;
        if (session.messages.some(m => m._streaming)) return;

        const newMessages = this.buildMessages(data.messages);
        session.messages.splice(0, session.messages.length);
        session.messages.push(...newMessages);
        session.hasMore = data.has_more;
        this.$nextTick(() => this.scrollToBottom());
      } catch (e) {
        console.error('Failed to load messages:', e);
      }
    },

    async loadMoreMessages(sessionId) {
      const session = this.sessions.find(s => s.id === sessionId);
      if (!session || !session.hasMore || session._loadingMore) return;

      const firstMsg = session.messages[0];
      if (!firstMsg || !firstMsg.id) return;

      session._loadingMore = true;
      const scrollEl = this.$refs.msgContainer;
      const prevHeight = scrollEl.scrollHeight;

      try {
        const resp = await fetch(
          `/api/sessions/${sessionId}/messages?limit=100&before_id=${encodeURIComponent(firstMsg.id)}`
        );
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        const older = this.buildMessages(data.messages);
        session.messages.unshift(...older);
        session.hasMore = data.has_more;

        this.$nextTick(() => {
          scrollEl.scrollTop += scrollEl.scrollHeight - prevHeight;
          session._loadingMore = false;
        });
      } catch (e) {
        console.error('Failed to load more messages:', e);
        session._loadingMore = false;
      }
    },

    buildMessages(rawMessages) {
      const result = [];
      for (const m of rawMessages) {
        if (m.role === 'tool' && m.tool_call_id) {
          // Merge tool result into the preceding assistant message's tool_call part
          for (let i = result.length - 1; i >= 0; i--) {
            const prev = result[i];
            if (prev.parts) {
              const part = prev.parts.find(p => p.type === 'tool_call' && p.call_id === m.tool_call_id);
              if (part) {
                part.result = typeof m.content === 'string' ? m.content : JSON.stringify(m.content);
                if (m.timestamp && prev.timestamp) {
                  part.duration_ms = (m.timestamp - prev.timestamp) * 1000;
                }
                if (m.imageUrl) {
                  // Insert image part after this tool_call part
                  const idx = prev.parts.indexOf(part);
                  prev.parts.splice(idx + 1, 0, { type: 'image', imageUrl: m.imageUrl, _uid: this._nextUid++ });
                }
                break;
              }
            }
          }
        } else if (m.role === 'assistant' || m.role === 'user') {
          result.push(this.mapMessage(m));
        }
      }
      return result;
    },

    mapMessage(m) {
      const msg = { id: m.id, role: m.role, content: '', images: [], timestamp: m.timestamp };
      let textContent = '';
      if (typeof m.content === 'string') {
        textContent = m.content;
      } else if (Array.isArray(m.content)) {
        const texts = [];
        m.content.forEach(c => {
          if (c.type === 'text') texts.push(c.text);
          else if (c.type === 'image_url') msg.images.push(c.image_url.url);
        });
        textContent = texts.join('\n');
      }
      msg.content = textContent;

      const parts = [];
      if (m.reasoning) {
        parts.push({ type: 'thinking', content: m.reasoning, done: true, _uid: this._nextUid++ });
      }
      if (m.tool_calls) {
        m.tool_calls.forEach(tc => {
          parts.push({
            type: 'tool_call',
            call_id: tc.id,
            name: tc.function.name,
            args: (() => { try { return JSON.parse(tc.function.arguments); } catch(e) { return tc.function.arguments; } })(),
            _uid: this._nextUid++,
          });
        });
      }
      if (textContent) {
        parts.push({ type: 'content', content: textContent, _uid: this._nextUid++ });
      }
      if (parts.length) {
        msg.parts = parts;
      }
      return msg;
    },

    async deleteSession(id) {
      try {
        await fetch('/api/sessions/' + id, { method: 'DELETE' });
      } catch (e) {
        console.error('Failed to delete session:', e);
      }
      this.sessions = this.sessions.filter(s => s.id !== id);
      if (this.activeSessionId === id) this.activeSessionId = this.sessions[0]?.id || null;
    },

    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed;
      const el = document.getElementById('sidebar');
      el.classList.toggle('collapsed', this.sidebarCollapsed);
    },


    handleEnter(e) {
      if (e.shiftKey) { this.inputText += '\n'; this.$nextTick(() => this.autoResize(this.$refs.inputRef)); }
      else this.sendMessage();
    },

    async sendMessage() {
      const text = this.inputText.trim();
      if (!text) return;

      this.inputText = '';
      this.$nextTick(() => this.autoResize(this.$refs.inputRef));

      // If agent is running, just steer it (don't create new stream)
      if (this.isTyping && this.activeSessionId) {
        const session = this.sessions.find(s => s.id === this.activeSessionId);
        if (!session) return;

        // Freeze current streaming message and push to session.messages
        // so user steer appears in the right chronological position
        if (this._streamingMsg && this._streamingMsg.parts.length > 0) {
          const frozen = { ...this._streamingMsg, _streaming: false };
          session.messages.push(frozen);
          this._streamingMsg = { role: 'assistant', content: '', images: [], parts: [], _streaming: true };
        }

        // Push user message immediately for responsive UX
        session.messages.push({ role: 'user', content: text, images: [] });
        this.$nextTick(() => this.scrollToBottom());

        try {
          const resp = await fetch(`/api/sessions/${session.id}/steer`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
          });
          if (!resp.ok) {
            const error = await resp.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(error.detail || 'HTTP ' + resp.status);
          }
        } catch (e) {
          console.error('Failed to steer:', e);
          this.showError(e.message);
        }
        return;
      }

      let session;
      let userMsgPushed = false;
      // Set guard BEFORE any await so loadSessionMessages won't replace messages
      this._streaming = true;

      if (!this.activeSessionId) {
        // Create new session
        try {
          const resp = await fetch('/api/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task: text })
          });
          if (!resp.ok) {
            const error = await resp.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(error.detail || 'HTTP ' + resp.status);
          }
          const { session_id } = await resp.json();
          session = {
            id: session_id,
            title: text.length > 28 ? text.slice(0, 28) + '…' : text,
            createdAt: new Date(),
            messages: [],
            _loaded: true,
          };
          this.sessions.unshift(session);
          this.activeSessionId = session_id;
          history.pushState({ sessionId: session_id }, '', `?session=${session_id}`);
        } catch (e) {
          console.error('Failed to create session:', e);
          this.showError(e.message);
          this.inputText = text;
          this._streaming = false;
          this.$nextTick(() => this.autoResize(this.$refs.inputRef));
          return;
        }
      } else {
        session = this.sessions.find(s => s.id === this.activeSessionId);
        if (!session) return;

        // Push user message immediately for responsive UX
        session.messages.push({ role: 'user', content: text, images: [] });
        this.$nextTick(() => this.scrollToBottom());
        userMsgPushed = true;

        try {
          const resp = await fetch(`/api/sessions/${session.id}/steer`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
          });
          if (!resp.ok) {
            const error = await resp.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(error.detail || 'HTTP ' + resp.status);
          }
        } catch (e) {
          console.error('Failed to steer:', e);
          this.showError(e.message);
          return;
        }
      }

      // Push user message for new session (steer already pushed above)
      if (!userMsgPushed) {
        session.messages.push({ role: 'user', content: text, images: [] });
        this.$nextTick(() => this.scrollToBottom());
      }
      this.isTyping = true;

      // Create streaming assistant message as separate Alpine property
      this._streamingMsg = { role: 'assistant', content: '', images: [], parts: [], _streaming: true };

      this.startStream(session);
    },

    startStream(session) {
      if (this.eventSource) this.eventSource.close();

      this.eventSource = new EventSource(`/api/sessions/${session.id}/stream`);

      this.eventSource.onmessage = (event) => {
        let parsed;
        try {
          parsed = JSON.parse(event.data);
        } catch (e) {
          console.error('SSE parse error:', e);
          return;
        }
        const { event: type, data } = parsed;

        if (type === 'tool_call') {
          this._streamingMsg.parts = [
            ...this._streamingMsg.parts,
            {
              type: 'tool_call',
              call_id: data.call_id || 'stream-' + Date.now(),
              name: data.name,
              args: data.args,
              _uid: this._nextUid++,
            }
          ];
          this.$nextTick(() => this.scrollToBottom());
        } else if (type === 'tool_result') {
          const parts = [...this._streamingMsg.parts];
          for (let i = parts.length - 1; i >= 0; i--) {
            if (parts[i].type === 'tool_call' && parts[i].call_id === data.call_id && !parts[i].result) {
              parts[i] = {
                ...parts[i],
                result: typeof data.result === 'string' ? data.result : JSON.stringify(data.result, null, 2),
              };
              if (data.imageUrl) {
                // Insert image part after this tool_call, matching buildMessages format
                parts.splice(i + 1, 0, { type: 'image', imageUrl: data.imageUrl, _uid: this._nextUid++ });
              }
              break;
            }
          }
          this._streamingMsg.parts = parts;
          this.$nextTick(() => this.scrollToBottom());
        } else if (type === 'delta') {
          const parts = [...this._streamingMsg.parts];
          const last = parts[parts.length - 1];
          if (last && last.type === 'content' && !last._done) {
            parts[parts.length - 1] = { ...last, content: last.content + data.text };
          } else {
            parts.push({ type: 'content', content: data.text, _uid: this._nextUid++ });
          }
          this._streamingMsg.parts = parts;
          this.$nextTick(() => this.scrollToBottom());
        } else if (type === 'reasoning') {
          const parts = [...this._streamingMsg.parts];
          const last = parts[parts.length - 1];
          if (last && last.type === 'thinking') {
            parts[parts.length - 1] = { ...last, content: last.content + data.text };
          } else {
            parts.push({ type: 'thinking', content: data.text, done: true, _uid: this._nextUid++ });
          }
          this._streamingMsg.parts = parts;
          this.$nextTick(() => this.scrollToBottom());
        } else if (type === 'session') {
          if (data.status === 'completed' || data.status === 'error' || data.status === 'stopped') {
            this.eventSource.close();
            this.eventSource = null;
            this.isTyping = false;
            this._streaming = false;
            if (data.status === 'stopped') {
              this._streamingMsg.parts = [
                ...this._streamingMsg.parts,
                { type: 'content', content: '*Session stopped*', _uid: this._nextUid++ }
              ];
            }
            // Fallback: if streaming was incomplete, append final_response
            if (data.final_response && this._streamingMsg) {
              const streamedContent = this._streamingMsg.parts
                .filter(p => p.type === 'content')
                .map(p => p.content)
                .join('');
              if (streamedContent.length < data.final_response.length) {
                this._streamingMsg.parts = [
                  ...this._streamingMsg.parts,
                  { type: 'content', content: data.final_response.slice(streamedContent.length), _uid: this._nextUid++ }
                ];
              }
            }
            session.isRunning = false;
            this._streamingMsg = null;
            this.loadSessionMessages(session.id);
          }
        } else if (type === 'step_context') {
          if (data.current !== undefined && data.limit !== undefined) {
            const pct = ((data.current / data.limit) * 100).toFixed(1);
            const parts = [...this._streamingMsg.parts];
            parts.push({ type: 'context', step: data.step, current: data.current, limit: data.limit, pct: pct, _uid: this._nextUid++ });
            this._streamingMsg.parts = parts;
            this.$nextTick(() => this.scrollToBottom());
          }
        } else if (type === 'error') {
          console.error('Stream error:', data.message);
          this._streamingMsg.parts = [
            ...this._streamingMsg.parts,
            { type: 'content', content: '**Error:** ' + data.message, _uid: this._nextUid++ }
          ];
        }
        this._streamMsgVer++;
      };

      this.eventSource.onerror = () => {
        this.isTyping = false;
        if (this.eventSource) {
          this.eventSource.close();
          this.eventSource = null;
        }
        this._streaming = false;
      };
    },

    async stopTyping() {
      if (this.activeSessionId) {
        try {
          await fetch(`/api/sessions/${this.activeSessionId}/stop`, { method: 'POST' });
        } catch (e) {
          console.error('Failed to stop session:', e);
        }
      }
      // Don't close EventSource or clear _streamingMsg here.
      // The backend will emit a 'session: stopped' SSE event, which
      // triggers the normal cleanup path (including loadSessionMessages).
      // If no event arrives within 3s, fall back to manual cleanup.
      setTimeout(() => {
        if (this._streaming) {
          if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
          }
          this.isTyping = false;
          this._streaming = false;
          this._streamingMsg = null;
          if (this.activeSessionId) {
            this.loadSessionMessages(this.activeSessionId);
          }
        }
      }, 3000);
    },

    async copyMsg(text, btn) {
      await navigator.clipboard.writeText(text).catch(() => {});
      const orig = btn.innerHTML;
      btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="#10a37f" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>';
      setTimeout(() => btn.innerHTML = orig, 1500);
    },

    openLightbox(src) {
      document.getElementById('lightbox-img').src = src;
      document.getElementById('lightbox').classList.add('open');
    },

    scrollToBottom() {
      if (this._scrollTimer) return;
      this._scrollTimer = setTimeout(() => {
        this._scrollTimer = null;
        const el = this.$refs.msgContainer;
        if (el) el.scrollTop = el.scrollHeight;
      }, 100);
    },

    handleScroll() {
      const el = this.$refs.msgContainer;
      if (!el) return;
      // Show jump-to-bottom when scrolled more than 200px from bottom
      this._showJumpBottom = (el.scrollHeight - el.scrollTop - el.clientHeight) > 200;
      // Load more messages when near top
      if (el.scrollTop <= 100) {
        const session = this.sessions.find(s => s.id === this.activeSessionId);
        if (session && session.hasMore && !session._loadingMore) {
          this.loadMoreMessages(this.activeSessionId);
        }
      }
    },

    jumpToBottom() {
      const el = this.$refs.msgContainer;
      if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    },

    async openDir(nameOrPath) {
      try {
        const params = new URLSearchParams();
        if (nameOrPath === 'home' || nameOrPath === 'logs') {
          params.set('name', nameOrPath);
        } else {
          params.set('path', nameOrPath);
        }
        await fetch('/api/open_dir?' + params.toString());
      } catch (e) {
        console.error('Failed to open directory:', e);
      }
    },

    autoResize(el) {
      el.style.height = '28px';
      el.style.height = Math.min(el.scrollHeight, 192) + 'px';
    },

    showError(message) {
      this.errorMessage = message;
      if (this._errorTimer) clearTimeout(this._errorTimer);
      this._errorTimer = setTimeout(() => {
        this.errorMessage = '';
      }, 8000);
    },

    async openConfig() {
      this.configTab = 'basic';
      this.showConfigModal = true;
      this.config = null;
      this.configSaved = false;
      await Promise.all([this.fetchApps(), this.loadProviders()]);
      try {
        const resp = await fetch('/api/config');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        this.config = await resp.json();
        // Set context_length mode based on current value
        this.contextLengthMode = this.config.model?.context_length === 0 ? 'auto' : 'custom';
        // Ensure qqbot platform exists
        if (!this.config.im) this.config.im = { platforms: {} };
        if (!this.config.im.platforms) this.config.im.platforms = {};
        if (!this.config.im.platforms.qqbot) {
          this.config.im.platforms.qqbot = { enabled: false, token: '', extra: {} };
        }
        if (!this.config.im.platforms.qqbot.extra) {
          this.config.im.platforms.qqbot.extra = {};
        }
      } catch (e) {
        console.error('Failed to load config:', e);
        this.showError('Failed to load configuration: ' + e.message);
        this.showConfigModal = false;
      }
    },

    async loadProviders() {
      try {
        const resp = await fetch('/api/providers');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        this.providers = data.providers || [];
      } catch (e) {
        console.error('Failed to load providers:', e);
        this.providers = [];
      }
    },

    onProviderChange() {
      const provider = this.providers.find(p => p.name === this.config.model.provider);
      if (provider && provider.builtin) {
        // Built-in provider: auto-fill base_url and set context_length to auto
        this.config.model.base_url = provider.base_url;
        this.contextLengthMode = 'auto';
        this.config.model.context_length = 0;
      }
    },

    onContextLengthModeChange() {
      if (this.contextLengthMode === 'auto') {
        this.config.model.context_length = 0;
      } else if (this.config.model.context_length === 0) {
        // Switching to custom mode with auto value, set default
        this.config.model.context_length = 262144;
      }
    },

    get isBuiltinProvider() {
      if (!this.providers || !this.config?.model?.provider) return false;
      const provider = this.providers.find(p => p.name === this.config.model.provider);
      return provider && provider.builtin;
    },

    async saveConfig() {
      if (!this.config) return;
      this.configSaving = true;
      this.configSaved = false;
      try {
        const resp = await fetch('/api/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.config)
        });
        if (!resp.ok) {
          const error = await resp.json().catch(() => ({ detail: 'Unknown error' }));
          throw new Error(error.detail || 'HTTP ' + resp.status);
        }
        this.configSaved = true;
      } catch (e) {
        console.error('Failed to save config:', e);
        this.showError('Failed to save configuration: ' + e.message);
      } finally {
        this.configSaving = false;
      }
    },

    async testModelConnection() {
      if (!this.config || !this.config.model) return;
      this.modelTesting = true;
      this.modelTestResult = '';
      try {
        const resp = await fetch('/api/model/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.config.model)
        });
        const data = await resp.json();
        if (resp.ok && data.status === 'success') {
          this.modelTestResult = '✓ Connection successful';
        } else {
          this.modelTestResult = '✗ ' + (data.message || 'Connection failed');
        }
      } catch (e) {
        console.error('Model test failed:', e);
        this.modelTestResult = '✗ Test failed: ' + e.message;
      } finally {
        this.modelTesting = false;
        setTimeout(() => { this.modelTestResult = ''; }, 5000);
      }
    },

    async testIMConnection(platform) {
      if (!this.config || !this.config.im || !this.config.im.platforms || !this.config.im.platforms[platform]) return;
      this.imTesting = true;
      this.imTestResult = '';
      try {
        const ps = this.config.im.platforms[platform];
        const resp = await fetch('/api/im/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            platform: platform,
            token: ps.token,
            extra: ps.extra || {}
          })
        });
        const data = await resp.json();
        if (resp.ok && data.status === 'success') {
          this.imTestResult = '✓ Connection successful';
        } else {
          this.imTestResult = '✗ ' + (data.message || 'Connection failed');
        }
      } catch (e) {
        console.error('IM test failed:', e);
        this.imTestResult = '✗ Test failed: ' + e.message;
      } finally {
        this.imTesting = false;
        setTimeout(() => { this.imTestResult = ''; }, 5000);
      }
    },

    async pickDir(target) {
      if (typeof pywebview !== 'undefined' && pywebview.api && pywebview.api.pick_dir) {
        try {
          const currentValue = target.split('.').reduce((obj, key) => obj[key], this);
          const selected = await pywebview.api.pick_dir(currentValue);
          if (selected) {
            const keys = target.split('.');
            let obj = this;
            for (let i = 0; i < keys.length - 1; i++) {
              obj = obj[keys[i]];
            }
            obj[keys[keys.length - 1]] = selected;
          }
        } catch (e) {
          console.error('pick_dir failed:', e);
          this.showError('Failed to open directory picker');
        }
      } else {
        this.showError('Directory picker is only available in the desktop app');
      }
    },
  };
}

function closeLightbox() {
  document.getElementById('lightbox').classList.remove('open');
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLightbox(); });
