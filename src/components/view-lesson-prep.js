/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * Teach-back 수업 준비 화면.
 *
 * 미션 목록에서 "Teach-back: Today's Lesson"을 고르면 이 화면이 뜬다.
 * `GET /api/lesson`으로 최근 수업 기록의 날짜 목록과 절 제목을 미리 보여 주고,
 * 날짜를 바꾸면 `?date=`로 다시 부른다.
 * 404·500이면 서버가 준 한국어 메시지를 그대로 보여 주고 시작 버튼을 막는다.
 */
class ViewLessonPrep extends HTMLElement {
  constructor() {
    super();
    this._mission = null;
    this._language = null;
    this._fromLanguage = null;
    this._mode = null;
    this._lesson = null;
    this._started = false;
    this._seniorMode = this._readSeniorMode();
    this._lessonAbort = null;
    this._lessonSeq = 0;
  }

  set mission(value) {
    this._mission = value;
    this.render();
  }

  set language(value) {
    this._language = value;
  }

  set fromLanguage(value) {
    this._fromLanguage = value;
  }

  set mode(value) {
    this._mode = value;
  }

  connectedCallback() {
    this.render();
    if (!this._started) {
      this._started = true;
      this._loadLesson();
    }
  }

  // ── 저장된 선배 개입 설정 ────────────────────────────────────────────────
  // 사생활 보호 모드 등 localStorage 접근이 막힌 환경에서도 죽지 않게 try/catch.
  _readSeniorMode() {
    try {
      return localStorage.getItem('teachback.seniorMode') === 'after' ? 'after' : 'during';
    } catch (e) {
      return 'during';
    }
  }

  _writeSeniorMode(value) {
    try {
      localStorage.setItem('teachback.seniorMode', value);
    } catch (e) {
      /* 저장이 막혀도 이번 화면에서는 선택을 유지한다. */
    }
  }

  render() {
    if (!this._mission) return;

    this.innerHTML = `
      <div class="container" style="max-width: 560px; min-height: 100vh; position: relative;">
        <button id="prep-back" aria-label="미션 목록으로 돌아가기" style="
          position: absolute;
          top: var(--spacing-md);
          left: var(--spacing-md);
          background: transparent;
          border: none;
          cursor: pointer;
          padding: 10px;
          border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          opacity: 0.7;
          transition: opacity 0.2s;
          color: var(--color-text-main);
          z-index: 10;
        " onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.7">
          <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg>
        </button>

        <div style="margin-top: var(--spacing-xxl); text-align: center;">
          <div style="font-size: 2.5rem; line-height: 1; margin-bottom: var(--spacing-sm);">🧑‍🏫</div>
          <h2 style="font-size: 1.6rem; margin-bottom: var(--spacing-xs);">Teach-back: Today's Lesson</h2>
          <p style="opacity: 0.75; font-size: 1rem; line-height: 1.5; margin: 0 auto var(--spacing-lg) auto; max-width: 440px;">
            오늘 공부한 내용을 미국 중학생 3명에게 <strong>영어로 가르쳐</strong> 보세요.<br>
            아래에서 가르칠 수업 기록을 확인하세요.
          </p>
        </div>

        <div id="lesson-body" class="card" style="text-align: left;">
          <p style="color: var(--color-text-sub); margin: 0;">수업 기록을 불러오는 중…</p>
        </div>

        <div id="senior-block" style="margin-top: var(--spacing-lg);"></div>

        <div style="flex: 1;"></div>

        <button id="prep-start" disabled style="
          margin-top: var(--spacing-lg);
          margin-bottom: var(--spacing-xxl);
          width: 100%;
          min-height: 56px;
          background: var(--color-accent-primary);
          color: white;
          padding: 18px var(--spacing-xl);
          font-size: 1.2rem;
          font-weight: 800;
          border-radius: var(--radius-lg);
          border: 1px solid rgba(255,255,255,0.1);
          box-shadow: 0 10px 20px -5px rgba(0,0,0,0.3);
          cursor: pointer;
          transition: all 0.3s cubic-bezier(0.19, 1, 0.22, 1);
          opacity: 0.45;
        ">Start Lesson</button>
      </div>
    `;

    this.querySelector('#prep-back').addEventListener('click', () => {
      this.dispatchEvent(new CustomEvent('navigate', {
        bubbles: true,
        detail: { view: 'missions' }
      }));
    });

    this._renderSeniorBlock();
    this._bindStart();
  }

  _bindStart() {
    const btn = this.querySelector('#prep-start');
    if (!btn) return;
    btn.addEventListener('click', () => {
      if (btn.disabled || !this._lesson) return;
      this.dispatchEvent(new CustomEvent('navigate', {
        bubbles: true,
        detail: {
          view: 'chat',
          mission: this._mission,
          language: this._language,
          fromLanguage: this._fromLanguage,
          mode: 'teachback',
          lesson: this._lesson,
          lessonDate: this._lesson.date,
          seniorMode: this._seniorMode
        }
      }));
    });
  }

  // ── 선배 개입 토글 ───────────────────────────────────────────────────────
  _renderSeniorBlock() {
    const host = this.querySelector('#senior-block');
    if (!host) return;

    const optionBtn = (value, title, sub) => {
      const active = this._seniorMode === value;
      return `
        <button type="button" data-senior="${value}" aria-pressed="${active ? 'true' : 'false'}" style="
          flex: 1;
          min-width: 140px;
          min-height: 64px;
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          justify-content: center;
          gap: 2px;
          padding: 12px 16px;
          border-radius: var(--radius-md);
          background: ${active ? 'rgba(163, 177, 138, 0.12)' : 'rgba(255,255,255,0.03)'};
          border: 1px solid ${active ? 'var(--color-accent-primary)' : 'transparent'};
          color: var(--color-text-main);
          text-align: left;
          cursor: pointer;
          transition: all 0.2s;
          box-shadow: ${active ? 'var(--shadow-sm)' : 'none'};
        ">
          <span style="font-weight: 800; font-size: 1rem;">${title}</span>
          <span style="font-size: 0.82rem; opacity: 0.7; line-height: 1.3;">${sub}</span>
        </button>
      `;
    };

    host.innerHTML = `
      <div class="glass-panel" style="padding: var(--spacing-lg);">
        <div style="font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; color: var(--color-text-sub); font-weight: 700; margin-bottom: 12px;">
          선배 선생님 개입
        </div>
        <div style="display: flex; flex-wrap: wrap; gap: var(--spacing-md);">
          ${optionBtn('during', '수업 중', '영어가 막히면 Ms. Park이 짧게 도와줘요')}
          ${optionBtn('after', '수업 후', '수업 내내 조용히 듣고, 끝난 뒤 피드백해요')}
        </div>
      </div>
    `;

    // 선택을 바꿀 때마다 강조와 aria-pressed를 두 버튼에 바로 반영한다.
    const applySelection = () => {
      host.querySelectorAll('[data-senior]').forEach((btn) => {
        const active = btn.getAttribute('data-senior') === this._seniorMode;
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        btn.style.background = active ? 'rgba(163, 177, 138, 0.12)' : 'rgba(255,255,255,0.03)';
        btn.style.border = `1px solid ${active ? 'var(--color-accent-primary)' : 'transparent'}`;
        btn.style.boxShadow = active ? 'var(--shadow-sm)' : 'none';
      });
    };
    applySelection();

    host.addEventListener('click', (event) => {
      const btn = event.target.closest('[data-senior]');
      if (!btn) return;
      this._seniorMode = btn.getAttribute('data-senior') === 'after' ? 'after' : 'during';
      this._writeSeniorMode(this._seniorMode);
      applySelection();
    });
  }

  // ── 수업 기록 불러오기 ──────────────────────────────────────────────────
  async _loadLesson(date) {
    const host = this.querySelector('#lesson-body');
    if (!host) return;

    const requestedDate = date || null;
    // 날짜를 빠르게 바꾸면 앞 요청을 취소하고, 늦게 온 응답은 버린다.
    if (this._lessonAbort) this._lessonAbort.abort();
    const controller = new AbortController();
    this._lessonAbort = controller;
    const seq = (this._lessonSeq += 1);

    host.innerHTML = `<p style="color: var(--color-text-sub); margin: 0;">수업 기록을 불러오는 중…</p>`;
    this._setStartEnabled(false);

    try {
      const url = date ? `/api/lesson?date=${encodeURIComponent(date)}` : '/api/lesson';
      const res = await fetch(url, { signal: controller.signal });
      if (seq !== this._lessonSeq || controller.signal.aborted) return;
      if (!res.ok) {
        const message = await this._errorMessage(res);
        if (seq !== this._lessonSeq || controller.signal.aborted) return;
        this._renderError(host, message);
        return;
      }
      const data = await res.json();
      if (seq !== this._lessonSeq || controller.signal.aborted) return;
      // 서버가 돌려준 date가 지금 고른 날짜와 다르면 버린다(스테일 응답).
      if (requestedDate && data.date && data.date !== requestedDate) return;
      this._lesson = data;
      this._renderLesson(host, data);
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      if (seq !== this._lessonSeq) return;
      console.error('Lesson load failed:', err);
      this._renderError(host, '수업 기록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.');
    }
  }

  // 서버가 준 한국어 메시지를 그대로 꺼낸다. (FastAPI는 {detail: "..."} 형태)
  async _errorMessage(res) {
    try {
      const body = await res.json();
      const detail = body && (body.detail || body.message || body.error);
      if (detail) return String(detail);
    } catch (e) {
      /* JSON이 아니면 기본 문구 */
    }
    if (res.status === 404) return '이 날짜의 수업 기록이 없습니다.';
    return '수업 기록을 불러오지 못했습니다. (HTTP ' + res.status + ')';
  }

  _renderError(host, message) {
    this._lesson = null;
    host.innerHTML = `
      <div style="border-left: 4px solid var(--color-danger); padding-left: var(--spacing-md);">
        <h4 style="margin: 0 0 var(--spacing-sm) 0; color: var(--color-danger);">수업 기록을 열 수 없어요</h4>
        <p style="margin: 0; color: var(--color-text-sub); line-height: 1.5; overflow-wrap: anywhere;">${this._esc(message)}</p>
        <button id="lesson-retry" style="
          margin-top: var(--spacing-md);
          min-height: 44px;
          background: transparent;
          color: var(--color-accent-primary);
          border: 1px solid var(--color-accent-primary);
          border-radius: var(--radius-md);
          padding: 10px 16px;
          font-weight: 700;
          cursor: pointer;
        ">다시 불러오기</button>
      </div>
    `;
    const retry = host.querySelector('#lesson-retry');
    if (retry) retry.addEventListener('click', () => this._loadLesson(this._lessonDate()));
    this._setStartEnabled(false);
  }

  _lessonDate() {
    const sel = this.querySelector('#lesson-date');
    return sel ? sel.value : null;
  }

  _renderLesson(host, data) {
    const dates = Array.isArray(data.dates) ? data.dates : [];
    const sections = Array.isArray(data.sections) ? data.sections : [];
    const current = data.date || '';
    const hidden = Number(data.hidden_count) || 0;

    const dateOptions = dates.map((d) =>
      `<option value="${this._esc(d)}"${d === current ? ' selected' : ''}>${this._esc(d)}</option>`
    ).join('');

    const sectionsHtml = sections.length
      ? sections.map((s) => `
          <div style="padding: var(--spacing-sm) 0; border-bottom: 1px solid rgba(127,127,127,0.15);">
            <p style="margin: 0 0 2px 0; font-weight: 800; color: var(--color-accent-secondary); overflow-wrap: anywhere;">
              ${this._esc(s.heading || '')}
            </p>
            <p style="margin: 0; color: var(--color-text-sub); font-size: 0.9rem; line-height: 1.5; overflow-wrap: anywhere;">
              ${this._esc(this._snippet(s.body))}
            </p>
          </div>
        `).join('')
      : '<p style="margin: 0; color: var(--color-text-sub); line-height: 1.5;">이 날짜는 보낼 수 있는 내용이 없어요(거름망에 모두 걸림)</p>';

    host.innerHTML = `
      <h4 style="border-bottom: 2px solid var(--color-bg); padding-bottom: var(--spacing-sm); margin: 0 0 var(--spacing-md) 0;">
        오늘 가르칠 기록
      </h4>

      <div style="display: flex; flex-direction: column; gap: 6px; margin-bottom: var(--spacing-md);">
        <label for="lesson-date" style="font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; color: var(--color-text-sub); font-weight: 700;">수업 날짜</label>
        <select id="lesson-date" style="
          width: 100%;
          min-height: 44px;
          padding: 10px 14px;
          border: var(--glass-border);
          border-radius: var(--radius-md);
          background: var(--color-surface);
          color: var(--color-text-main);
          font-family: var(--font-body);
          font-weight: 700;
          font-size: 1rem;
          cursor: pointer;
        ">
          ${dateOptions || `<option value="${this._esc(current)}">${this._esc(current)}</option>`}
        </select>
      </div>

      <p style="margin: 0 0 var(--spacing-sm) 0; font-size: 1.05rem; font-weight: 700; overflow-wrap: anywhere;">
        ${this._esc(data.day_title || '제목 없음')}
      </p>
      ${hidden > 0 ? `<p style="margin: 0 0 var(--spacing-sm) 0; font-size: 0.82rem; opacity: 0.6;">차단어로 가린 절 ${hidden}개는 제외했어요.</p>` : ''}

      <div style="max-height: 320px; overflow-y: auto; -webkit-overflow-scrolling: touch;">
        ${sectionsHtml}
      </div>
    `;

    const sel = host.querySelector('#lesson-date');
    if (sel) {
      sel.addEventListener('change', () => this._loadLesson(sel.value));
    }

    // 가르칠 절이 0개면(거름망에 모두 걸림) Start를 막는다.
    this._setStartEnabled(sections.length > 0);
  }

  _snippet(body) {
    const text = String(body == null ? '' : body).replace(/\s+/g, ' ').trim();
    return text.length > 180 ? text.slice(0, 180) + '…' : text;
  }

  _setStartEnabled(enabled) {
    const btn = this.querySelector('#prep-start');
    if (!btn) return;
    btn.disabled = !enabled;
    btn.style.opacity = enabled ? '1' : '0.45';
    btn.style.cursor = enabled ? 'pointer' : 'not-allowed';
  }

  _esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
}

customElements.define('view-lesson-prep', ViewLessonPrep);
