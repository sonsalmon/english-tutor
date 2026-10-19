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

class ViewSummary extends HTMLElement {
  constructor() {
    super();
    this._result = null;
    this._mission = null;
    this._language = null;
    this._fromLanguage = null;
    this._mode = null;
    this._retry = null;
    this._startedAt = null;
    this._lesson = null;
    this._lessonDate = null;
    this._seniorMode = null;
    this._unanswered = [];
    this._tutorStarted = false;
  }

  set result(value) {
    this._result = value;
    this.render();
  }

  set mission(value) {
    this._mission = value;
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

  set startedAt(value) {
    this._startedAt = value;
  }

  set lesson(value) {
    this._lesson = value;
  }

  set lessonDate(value) {
    this._lessonDate = value;
  }

  set seniorMode(value) {
    this._seniorMode = value;
  }

  _isTeachback() {
    return !!(this._mission && this._mission.type === 'teachback');
  }

  connectedCallback() {
    this.render();
    this._loadTutor();
  }

  render() {
    if (!this._result) return;

    if (this._result.incomplete) {
      // teach-back 수업은 완료 판정이 없다: "Mission Ended" 대신 수업 종료 안내를 보여 준다.
      const heading = this._isTeachback()
        ? `
            <h2 style="margin-top: var(--spacing-xl); color: var(--color-text-sub);">수업 끝</h2>

            <div style="margin: var(--spacing-xxl) 0; opacity: 0.7;">
                <p style="font-size: 1.1rem; line-height: 1.5;">
                    학생들이 물은 것과 선배 피드백을 확인해요
                </p>
            </div>
        `
        : `
            <h2 style="margin-top: var(--spacing-xl); color: var(--color-text-sub);">Mission Ended</h2>

            <div style="margin: var(--spacing-xxl) 0; opacity: 0.7;">
                <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                <p style="margin-top: var(--spacing-md); font-size: 1.1rem;">
                    You didn't complete the mission objectives.<br>
                    No score awarded this time.
                </p>
            </div>
        `;

      this.innerHTML = `
          <div class="container text-center">
            ${heading}

            <div id="tutor-section"></div>

            <div style="flex: 1;"></div>

            <button id="home-btn" class="btn-primary">Back to mission list</button>
          </div>
        `;
    } else {
      this.innerHTML = `
          <div class="container text-center">
            <h2 style="margin-top: var(--spacing-xl); color: var(--color-accent-secondary);">Mission Accomplished!</h2>

            <div style="margin: var(--spacing-lg) 0;">
              ${this._result.score !== "0" && this._result.score !== 0 ? this._renderScore(this._result.score) : '<p style="font-size: 1.2rem; opacity: 0.8;">Practice session complete!</p>'}
            </div>

            <div class="card" style="text-align: left;">
              <h4 style="border-bottom: 2px solid var(--color-bg); padding-bottom: var(--spacing-sm);">Feedback</h4>
              <ul style="padding-left: var(--spacing-lg); color: var(--color-text-sub);">
                ${(this._result.notes || []).map(note => `<li>${note}</li>`).join('')}
              </ul>
            </div>

            <div id="tutor-section"></div>

            <div style="flex: 1;"></div>

            <button id="home-btn" class="btn-primary">Back to mission list</button>
          </div>
        `;
    }

    const btn = this.querySelector('#home-btn');
    btn.style.cssText = `
        background: var(--color-accent-primary);
        color: white;
        padding: 20px var(--spacing-xl);
        font-size: 1.25rem;
        font-weight: 800;
        border-radius: var(--radius-lg);
        width: 100%;
        margin-bottom: var(--spacing-xxl);
        box-shadow: 0 10px 20px -5px rgba(0,0,0,0.3);
        border: 1px solid rgba(255,255,255,0.1);
        cursor: pointer;
        transition: all 0.3s cubic-bezier(0.19, 1, 0.22, 1);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    `;

    btn.onmouseover = () => {
      btn.style.transform = 'translateY(-4px) scale(1.01)';
      btn.style.boxShadow = '0 15px 30px -10px rgba(163, 177, 138, 0.4)';
      btn.style.filter = 'brightness(1.1)';
    };
    btn.onmouseout = () => {
      btn.style.transform = 'translateY(0) scale(1)';
      btn.style.boxShadow = '0 10px 20px -5px rgba(0,0,0,0.3)';
      btn.style.filter = 'brightness(1)';
    };

    btn.addEventListener('click', () => {
      this.dispatchEvent(new CustomEvent('navigate', {
        bubbles: true,
        detail: { view: 'missions', mission: null, result: null }
      }));
    });
  }

  // ── Tutoring ────────────────────────────────────────────────────────────

  async _loadTutor() {
    if (this._tutorStarted) return;
    this._tutorStarted = true;

    const host = this.querySelector('#tutor-section');
    if (!host) return;

    host.innerHTML = this._tutorLoadingHtml();

    const body = this._startedAt ? { started_at: this._startedAt } : {};
    if (this._isTeachback()) {
      body.mode = 'teachback';
      if (this._lessonDate) body.lesson_date = this._lessonDate;
    }

    try {
      const res = await fetch('/api/tutor', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // 이번 통화 시작 시각(epoch ms)을 보내 서버가 그 이후 저장된 전문만 고르게 한다.
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        let detail = '';
        try {
          const errBody = await res.json();
          if (errBody && errBody.detail) detail = String(errBody.detail);
        } catch (e) { /* 본문이 JSON이 아니면 기본 문구 사용 */ }
        throw new Error(detail || ('HTTP ' + res.status));
      }
      const data = await res.json();
      this._retry = data && data.retry ? data.retry : null;
      this._unanswered = data && Array.isArray(data.unanswered) ? data.unanswered : [];
      host.innerHTML = this._tutorHtml(data || {});
      const retryBtn = host.querySelector('#retry-call-btn');
      if (retryBtn) retryBtn.addEventListener('click', () => this._startRetry());
    } catch (err) {
      console.error('Tutoring failed:', err);
      host.innerHTML = this._tutorErrorHtml(err && err.message);
    }
  }

  _tutorLoadingHtml() {
    return `
      <div class="card" style="text-align: left; margin-top: var(--spacing-lg);">
        <h4 style="border-bottom: 2px solid var(--color-bg); padding-bottom: var(--spacing-sm); margin-bottom: var(--spacing-md);">
          Tutoring
        </h4>
        <p style="color: var(--color-text-sub); margin: 0;">Analyzing your call…</p>
      </div>
    `;
  }

  _tutorErrorHtml(message) {
    // 실패하면 한 줄 안내만 보여 주고 "다시 통화" 버튼은 숨긴다.
    return `
      <div class="card" style="text-align: left; margin-top: var(--spacing-lg);">
        <h4 style="border-bottom: 2px solid var(--color-bg); padding-bottom: var(--spacing-sm); margin-bottom: var(--spacing-md);">
          Tutoring
        </h4>
        <p style="color: var(--color-text-sub); margin: 0; line-height: 1.5; overflow-wrap: anywhere;">
          ${this._esc(message || '튜터링 분석에 실패했습니다. 잠시 후 다시 시도해 주세요.')}
        </p>
      </div>
    `;
  }

  _tutorHtml(data) {
    const corrections = Array.isArray(data.corrections) ? data.corrections : [];
    const good = Array.isArray(data.good) ? data.good : [];
    const vocab = Array.isArray(data.vocab) ? data.vocab : [];
    const pragmatics = Array.isArray(data.pragmatics) ? data.pragmatics : [];
    const retry = data.retry || {};
    const goal = typeof retry.goal === 'string' ? retry.goal : '';
    const phrases = Array.isArray(retry.target_phrases) ? retry.target_phrases.filter(Boolean) : [];
    const unanswered = Array.isArray(data.unanswered) ? data.unanswered : [];
    const isTeachback = this._isTeachback();

    const section = (title, body) => body ? `
      <div style="margin-top: var(--spacing-lg);">
        <h5 style="margin: 0 0 var(--spacing-sm) 0; color: var(--color-accent-secondary); font-size: 0.95rem; letter-spacing: 0.03em;">${title}</h5>
        ${body}
      </div>` : '';

    const correctionsBody = corrections.map(c => `
      <div style="padding: var(--spacing-sm) 0; border-bottom: 1px solid rgba(127,127,127,0.15);">
        <p style="margin: 0 0 2px 0; color: var(--color-text-sub); text-decoration: line-through; overflow-wrap: anywhere;">${this._esc(c.said)}</p>
        <p style="margin: 0 0 2px 0; color: var(--color-accent-primary); font-weight: 700; overflow-wrap: anywhere;">${this._esc(c.better)}</p>
        ${c.why ? `<p style="margin: 0; color: var(--color-text-sub); font-size: 0.9rem; line-height: 1.5; overflow-wrap: anywhere;">${this._esc(c.why)}</p>` : ''}
      </div>
    `).join('');

    const goodBody = good.map(g => `
      <div style="padding: var(--spacing-sm) 0; border-bottom: 1px solid rgba(127,127,127,0.15);">
        <p style="margin: 0 0 2px 0; font-weight: 700; overflow-wrap: anywhere;">${this._esc(g.said)}</p>
        ${g.note ? `<p style="margin: 0; color: var(--color-text-sub); font-size: 0.9rem; line-height: 1.5; overflow-wrap: anywhere;">${this._esc(g.note)}</p>` : ''}
      </div>
    `).join('');

    const vocabBody = vocab.map(v => `
      <div style="padding: var(--spacing-sm) 0; border-bottom: 1px solid rgba(127,127,127,0.15);">
        <p style="margin: 0 0 2px 0; font-weight: 700; color: var(--color-accent-primary); overflow-wrap: anywhere;">${this._esc(v.word)}</p>
        ${v.meaning_ko ? `<p style="margin: 0; overflow-wrap: anywhere;">${this._esc(v.meaning_ko)}</p>` : ''}
        ${v.example ? `<p style="margin: 2px 0 0 0; color: var(--color-text-sub); font-style: italic; font-size: 0.9rem; overflow-wrap: anywhere;">${this._esc(v.example)}</p>` : ''}
        ${v.etymology ? `<p style="margin: 2px 0 0 0; color: var(--color-text-sub); font-size: 0.85rem; overflow-wrap: anywhere;">↳ ${this._esc(v.etymology)}</p>` : ''}
      </div>
    `).join('');

    const pragmaticsBody = pragmatics.map(p => `
      <div style="padding: var(--spacing-sm) 0; border-bottom: 1px solid rgba(127,127,127,0.15);">
        <p style="margin: 0 0 2px 0; font-weight: 700; overflow-wrap: anywhere;">${this._esc(p.pattern)}</p>
        ${p.note ? `<p style="margin: 0; color: var(--color-text-sub); font-size: 0.9rem; line-height: 1.5; overflow-wrap: anywhere;">${this._esc(p.note)}</p>` : ''}
      </div>
    `).join('');

    const hasAny = corrections.length || good.length || vocab.length || pragmatics.length || goal || phrases.length || (isTeachback && unanswered.length);
    const empty = hasAny ? '' : '<p style="color: var(--color-text-sub); margin: 0;">No tutoring notes for this call.</p>';

    // Teach-back: 답하지 못한 질문을 맨 위에 원인 배지와 함께 보여 준다.
    const causeMap = {
      english: { label: '영어', color: '#1a73e8' },
      understanding: { label: '이해', color: '#e57373' },
      both: { label: '둘 다', color: '#d4a373' },
      unclear: { label: '불분명', color: '#949ba4' },
    };
    const unansweredBody = unanswered.length
      ? unanswered.map((u) => {
          const cause = causeMap[u && u.cause] || causeMap.unclear;
          return `
            <div style="padding: var(--spacing-md) 0; border-bottom: 1px solid rgba(127,127,127,0.15);">
              <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: var(--spacing-sm); flex-wrap: wrap;">
                <p style="margin: 0; font-weight: 800; line-height: 1.4; overflow-wrap: anywhere; flex: 1; min-width: 60%;">${this._esc(u && u.question)}</p>
                <span style="
                  flex-shrink: 0;
                  background: ${cause.color}22;
                  color: ${cause.color};
                  border: 1px solid ${cause.color}44;
                  border-radius: var(--radius-full);
                  padding: 3px 10px;
                  font-size: 0.75rem;
                  font-weight: 800;
                ">${cause.label}</span>
              </div>
              ${u && u.teacher_said ? `<p style="margin: 6px 0 0 0; color: var(--color-text-sub); font-size: 0.9rem; line-height: 1.5; overflow-wrap: anywhere;"><strong>선생님이 한 말:</strong> ${this._esc(u.teacher_said)}</p>` : ''}
              ${u && u.evidence ? `<p style="margin: 4px 0 0 0; color: var(--color-text-sub); font-size: 0.9rem; line-height: 1.5; overflow-wrap: anywhere;"><strong>근거:</strong> ${this._esc(u.evidence)}</p>` : ''}
              ${u && u.parked ? `<span style="display: inline-block; margin-top: 6px; background: var(--color-accent-glow); color: var(--color-accent-secondary); border-radius: var(--radius-sm); padding: 2px 8px; font-size: 0.75rem; font-weight: 700;">미룬 질문</span>` : ''}
            </div>`;
        }).join('')
      : '<p style="margin: 0; color: var(--color-text-sub);">답하지 못한 질문이 없어요. 잘 가르쳤습니다! 🎉</p>';
    const unansweredSection = isTeachback
      ? `
      <div style="margin-top: var(--spacing-lg);">
        <h5 style="margin: 0 0 var(--spacing-sm) 0; color: var(--color-accent-secondary); font-size: 0.95rem; letter-spacing: 0.03em;">답 못한 질문</h5>
        ${unansweredBody}
      </div>`
      : '';

    const retryBody = (goal || phrases.length) ? `
      <div style="margin-top: var(--spacing-md); padding: var(--spacing-md); border-radius: var(--radius-md); background: var(--color-accent-glow);">
        ${goal ? `<p style="margin: 0 0 var(--spacing-sm) 0; line-height: 1.5; overflow-wrap: anywhere;"><strong>Next goal:</strong> ${this._esc(goal)}</p>` : ''}
        ${phrases.length ? `
          <div style="display: flex; flex-wrap: wrap; gap: 6px;">
            ${phrases.map(p => `<span style="background: var(--color-surface); border: var(--glass-border); border-radius: var(--radius-full); padding: 4px 12px; font-size: 0.85rem; overflow-wrap: anywhere;">${this._esc(p)}</span>`).join('')}
          </div>` : ''}
      </div>` : '';

    const retryBtn = (this._mission && (goal || phrases.length || isTeachback)) ? `
      <button id="retry-call-btn" style="
        margin-top: var(--spacing-lg);
        width: 100%;
        background: var(--color-accent-secondary);
        color: var(--color-surface-solid);
        padding: 16px var(--spacing-lg);
        font-size: 1.05rem;
        font-weight: 800;
        border: none;
        border-radius: var(--radius-lg);
        cursor: pointer;
        box-shadow: var(--shadow-sm);
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      " onmouseover="this.style.transform='translateY(-2px)'; this.style.filter='brightness(1.05)';" onmouseout="this.style.transform='translateY(0)'; this.style.filter='brightness(1)';">
        ${isTeachback ? '같은 수업 다시 하기' : '같은 장면 다시 통화'}
      </button>` : '';

    // 저장에 실패했으면(화면에서만 확인 가능) 한 줄로 알린다.
    const saveWarning = data.saved === false
      ? '<p style="margin: var(--spacing-md) 0 0 0; color: var(--color-text-sub); font-size: 0.9rem; line-height: 1.5;">저장은 실패했어요(화면에서만 확인)</p>'
      : '';

    return `
      <div class="card" style="text-align: left; margin-top: var(--spacing-lg);">
        <h4 style="border-bottom: 2px solid var(--color-bg); padding-bottom: var(--spacing-sm); margin-bottom: 0;">
          Tutoring
        </h4>
        ${empty}
        ${unansweredSection}
        ${section('고칠 문장', correctionsBody)}
        ${section('좋았던 문장', goodBody)}
        ${section('나온 단어', vocabBody)}
        ${section('미국식 포인트', pragmaticsBody)}
        ${retryBody}
        ${retryBtn}
        ${saveWarning}
      </div>
    `;
  }

  _startRetry() {
    if (!this._mission) {
      this.dispatchEvent(new CustomEvent('navigate', {
        bubbles: true,
        detail: { view: 'missions' }
      }));
      return;
    }
    const isTeachback = this._isTeachback();
    // Teach-back은 같은 날짜·같은 모드로 다시 시작하고, 답 못한 질문을 RETRY_BLOCK에 붙인다.
    const retry = isTeachback
      ? Object.assign({}, this._retry || {}, { unanswered: this._unanswered })
      : this._retry;
    this.dispatchEvent(new CustomEvent('navigate', {
      bubbles: true,
      detail: {
        view: 'chat',
        mission: this._mission,
        language: this._language,
        fromLanguage: this._fromLanguage,
        mode: this._mode,
        retry: retry,
        lesson: this._lesson,
        lessonDate: this._lessonDate,
        seniorMode: this._seniorMode,
      }
    }));
  }

  _esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  _renderScore(score) {
    const levels = [
      { id: '1', title: 'Tiro', stars: 1 },
      { id: '2', title: 'Proficiens', stars: 2 },
      { id: '3', title: 'Peritus', stars: 3 }
    ];

    const currentLevel = levels.find(l => l.id === score.toString()) || levels[0];
    const descriptions = {
      '1': 'You needed a lot of help',
      '2': 'A little help',
      '3': 'No help, fluid'
    };

    const starIcon = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>`;

    const scaleHtml = levels.map(level => {
      const isCurrent = level.id === score.toString();
      const opacity = isCurrent ? '1' : '0.3';
      const color = isCurrent ? 'var(--color-accent-primary)' : 'var(--color-text-main)';
      const weight = isCurrent ? 'bold' : 'normal';
      const fontSize = isCurrent ? '1.1rem' : '0.9rem';

      let starsHtml = '';
      for (let i = 0; i < level.stars; i++) starsHtml += starIcon;

      return `
        <div style="flex: 1; opacity: ${opacity}; color: ${color}; transition: all 0.3s ease; display: flex; flex-direction: column; align-items: center; gap: 4px;">
           <div style="display: flex; gap: 2px; color: ${isCurrent ? 'var(--color-accent-secondary)' : 'currentColor'}">
             ${starsHtml}
           </div>
           <span style="font-family: var(--font-heading); font-weight: ${weight}; font-size: ${fontSize};">${level.title}</span>
        </div>
      `;
    }).join('');

    return `
      <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: var(--spacing-md); height: 80px;">
        ${scaleHtml}
      </div>
      <p style="font-size: 1rem; opacity: 0.8; font-style: italic; margin-top: var(--spacing-md);">(${descriptions[score.toString()] || ''})</p>
    `;
  }
}

customElements.define('view-summary', ViewSummary);
