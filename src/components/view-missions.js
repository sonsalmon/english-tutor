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

import missionsData from '../data/missions.json';
import { TOPIC_MAX, sanitizeTopic } from '../lib/ms-park.js';

const escapeHtml = (value) => String(value)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

class ViewMissions extends HTMLElement {
  connectedCallback() {
    const options = `
            <option>🇬🇧 English</option>
            <option>🇩🇪 German</option>
            <option>🇪🇸 Spanish</option>
            <option>🇫🇷 French</option>
            <option>🇮🇳 Hindi</option>
            <option>🇦🇪 Arabic</option>
            <option>🇮🇩 Indonesian</option>
            <option>🇮🇹 Italian</option>
            <option>🇯🇵 Japanese</option>
            <option>🇰🇷 Korean</option>
            <option>🇧🇷 Portuguese</option>
            <option>🇷🇺 Russian</option>
            <option>🇳🇱 Dutch</option>
            <option>🇵🇱 Polish</option>
            <option>🇧🇩 Bengali</option>
            <option>🇮🇳 Marathi</option>
            <option>🇮🇳 Tamil</option>
            <option>🇮🇳 Telugu</option>
            <option>🇹🇭 Thai</option>
            <option>🇹🇷 Turkish</option>
            <option>🇻🇳 Vietnamese</option>
            <option>🇷🇴 Romanian</option>
            <option>🇺🇦 Ukrainian</option>
            <option>🧑‍🔬 Science Jargon</option>

    `;

    this.innerHTML = `
      <div class="container" style="max-width: 1000px;">
        <!-- HUD Panel -->
        <div class="hud-panel glass-panel" style="
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: var(--spacing-xl);
            padding: var(--spacing-lg);
            align-items: start;
            max-width: 900px;
            margin: 0 auto var(--spacing-xxl) auto;
        ">
            <!-- Native Language Column -->
            <div style="display: flex; flex-direction: column; gap: 8px;">
                <label style="
                    font-size: 0.8rem;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    color: var(--color-text-sub);
                    font-weight: 700;
                    margin-left: 4px;
                ">I speak</label>
                <div style="position: relative;">
                     <select id="from-lang" style="
                        width: 100%;
                        padding: 12px 16px;
                        border: var(--glass-border);
                        border-radius: var(--radius-md);
                        background: var(--color-surface);
                        color: var(--color-text-main);
                        font-family: var(--font-body);
                        font-weight: 600;
                        appearance: none;
                        cursor: pointer;
                        font-size: 1rem;
                        transition: all 0.2s;
                     " onmouseover="this.style.background='var(--color-bg)'" onmouseout="this.style.background='var(--color-surface)'">
                        ${options}
                     </select>
                     <div style="position: absolute; right: 12px; top: 50%; transform: translateY(-50%); pointer-events: none; opacity: 0.5;">▼</div>
                </div>
            </div>
            
            <!-- Target Language Column -->
            <div style="display: flex; flex-direction: column; gap: 8px;">
                <label style="
                    font-size: 0.8rem; 
                    text-transform: uppercase; 
                    letter-spacing: 1px; 
                    color: var(--color-accent-secondary);
                    font-weight: 700;
                    margin-left: 4px;
                ">I want to learn</label>
                <div style="position: relative;">
                    <select id="to-lang" style="
                        width: 100%;
                        padding: 12px 16px;
                        border: 1px solid var(--color-accent-secondary);
                        border-radius: var(--radius-md);
                        background: var(--color-surface);
                        color: var(--color-text-main);
                        font-family: var(--font-body);
                        font-weight: 700;
                        appearance: none;
                        cursor: pointer;
                        font-size: 1rem;
                        box-shadow: var(--shadow-sm);
                        transition: all 0.2s;
                    " onmouseover="this.style.background='var(--color-bg)'" onmouseout="this.style.background='var(--color-surface)'">
                        ${options}
                    </select>
                     <div style="position: absolute; right: 12px; top: 50%; transform: translateY(-50%); pointer-events: none; color: var(--color-accent-secondary);">▼</div>
                </div>
            </div>

            <!-- Mode Selection (Full Width Row) -->
            <div style="grid-column: 1 / -1; margin-top: var(--spacing-md); padding-top: var(--spacing-lg); border-top: 1px solid rgba(255,255,255,0.05);">
                 <label style="
                    display: block;
                    font-size: 0.8rem; 
                    text-transform: uppercase; 
                    letter-spacing: 1px; 
                    color: var(--color-text-sub);
                    font-weight: 700;
                    margin-bottom: 12px;
                    margin-left: 4px;
                ">Select Experience Mode</label>
                
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--spacing-md);">
                    <button id="mode-teacher" class="mode-btn" style="
                        display: flex;
                        align-items: center;
                        gap: 12px;
                        padding: 16px; 
                        border-radius: var(--radius-md); 
                        border: 1px solid transparent; 
                        background: rgba(255,255,255,0.03); 
                        color: var(--color-text-sub); 
                        cursor: pointer; 
                        transition: all 0.2s; 
                        text-align: left;
                    ">
                        <span style="font-size: 1.5rem;">🧑‍🏫</span>
                        <div>
                            <div style="font-weight: 700; font-size: 1rem; color: var(--color-text-main);">Teacher Mode</div>
                            <div style="font-size: 0.8rem; opacity: 0.7; margin-top: 2px;">Guidance, specific tips, and corrections</div>
                        </div>
                    </button>
                    
                    <button id="mode-immersive" class="mode-btn" style="
                        display: flex;
                        align-items: center;
                        gap: 12px;
                        padding: 16px; 
                        border-radius: var(--radius-md); 
                        border: 1px solid transparent; 
                        background: rgba(255,255,255,0.03); 
                        color: var(--color-text-sub); 
                        cursor: pointer; 
                        transition: all 0.2s; 
                        text-align: left;
                    ">
                        <span style="font-size: 1.5rem;">🎭</span>
                        <div>
                            <div style="font-weight: 700; font-size: 1rem; color: var(--color-text-main);">Immersive Roleplay</div>
                            <div style="font-size: 0.8rem; opacity: 0.7; margin-top: 2px;">Strict roleplay, no breaks in character</div>
                        </div>
                    </button>
                </div>
            </div>
        </div>

        <section id="free-talk" class="glass-panel" aria-labelledby="free-talk-title" style="
            width: 100%;
            box-sizing: border-box;
            max-width: 900px;
            margin: 0 auto var(--spacing-xxl) auto;
            padding: var(--spacing-lg);
            display: flex;
            flex-direction: column;
            gap: var(--spacing-md);
        ">
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="font-size: 1.5rem;" aria-hidden="true">💬</span>
                <div>
                    <h3 id="free-talk-title" style="margin: 0; font-size: 1.3rem;">Free Talk with Ms. Park</h3>
                    <p style="margin: 2px 0 0 0; font-size: 0.9rem; color: var(--color-text-sub);">No role-play. Pick a topic or paste something you read, and talk it over.</p>
                </div>
            </div>
            <textarea id="free-talk-topic" rows="5" maxlength="${TOPIC_MAX}" aria-label="Today's topic or material" placeholder="Today's topic, or paste an article, an email, or notes…" style="
                width: 100%;
                box-sizing: border-box;
                padding: 12px 16px;
                border: var(--glass-border);
                border-radius: var(--radius-md);
                background: var(--color-surface);
                color: var(--color-text-main);
                font-family: var(--font-body);
                font-size: 1rem;
                line-height: 1.5;
                resize: vertical;
            "></textarea>
            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--spacing-md);">
                <div style="font-size: 0.85rem; color: var(--color-text-sub);">
                    <span id="free-talk-count">0 / ${TOPIC_MAX.toLocaleString('en-US')}</span>
                    <span id="free-talk-limit" role="status" style="margin-left: 8px; color: var(--color-danger);"></span>
                </div>
                <button id="free-talk-start" type="button" style="
                    min-height: 44px;
                    padding: 12px var(--spacing-xl);
                    border: none;
                    border-radius: var(--radius-md);
                    background: var(--color-accent-primary);
                    color: var(--color-surface-solid);
                    font-family: var(--font-body);
                    font-size: 1rem;
                    font-weight: 800;
                    cursor: pointer;
                    box-shadow: var(--shadow-sm);
                ">Start Free Talk</button>
            </div>
        </section>

        <div style="margin-bottom: var(--spacing-md); text-align: center;">
            <h2 style="font-size: 2.5rem; letter-spacing: -0.03em; margin-bottom: var(--spacing-xs);">Choose Your Quest</h2>
            <p style="opacity: 0.7; font-size: 1.1rem;">Select a scenario to begin your immersive practice</p>
        </div>

        <div class="missions-list mission-grid">
          <!-- Missions will be injected here -->
        </div>

        <!-- Developer Control Center -->
        <div style="
            margin-top: var(--spacing-lg);
            margin-bottom: var(--spacing-xl);
            position: relative;
        ">
            <div style="
                background: var(--color-surface);
                backdrop-filter: blur(20px);
                border: var(--glass-border);
                border-radius: var(--radius-lg);
                padding: 0;
                overflow: hidden;
                box-shadow: var(--shadow-md);
            ">
                 <!-- Terminal Header -->
                <div style="
                    background: rgba(0,0,0,0.05);
                    padding: 12px 20px;
                    border-bottom: var(--glass-border);
                    display: flex;
                    align-items: center;
                    gap: 10px;
                ">
                    <div style="display: flex; gap: 6px;">
                        <div style="width: 10px; height: 10px; border-radius: 50%; background: #ff5f56; opacity: 0.8;"></div>
                        <div style="width: 10px; height: 10px; border-radius: 50%; background: #ffbd2e; opacity: 0.8;"></div>
                        <div style="width: 10px; height: 10px; border-radius: 50%; background: #27c93f; opacity: 0.8;"></div>
                    </div>
                    <div style="font-family: 'Courier New', monospace; font-size: 0.8rem; opacity: 0.5; margin-left: 10px; color: var(--color-text-main);">developer_mode.sh</div>
                </div>

                <div style="padding: var(--spacing-xl); display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-xl); flex-wrap: wrap;">
                    <div style="flex: 2; min-width: 300px;">
                        <h3 style="
                            font-family: 'Courier New', monospace; 
                            color: var(--color-accent-primary); 
                            margin-bottom: var(--spacing-sm);
                            font-size: 1.4rem;
                            display: flex;
                            align-items: center;
                            gap: 10px;
                        ">
                            <span style="opacity: 0.5;">></span> Deploy Your Own Version
                        </h3>
                        <p style="opacity: 0.7; font-size: 1rem; line-height: 1.6; max-width: 500px; color: var(--color-text-sub);">
                            Launch your own personalized instance in just 1-click. Customize scenarios, add new languages, or rewrite the world.
                        </p>
                    </div>

                    <div style="flex: 1; display: flex; justify-content: flex-end; gap: var(--spacing-md);">


                        <a href="https://deploy.cloud.run/?git_repo=https://github.com/ZackAkil/immersive-language-learning-with-live-api&utm_source=github&utm_medium=unpaidsoc&utm_campaign=FY-Q1-global-cloud-ai-starter-apps&utm_content=immergo-app&utm_term=-" target="_blank" style="
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            gap: 12px;
                            padding: 16px 32px;
                            border-radius: var(--radius-md);
                            color: #1a73e8;
                            background: rgba(26, 115, 232, 0.05);
                            text-decoration: none;
                            font-weight: 800;
                            box-shadow: 0 4px 15px rgba(26, 115, 232, 0.1);
                            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                            font-size: 1.1rem;
                            white-space: nowrap;
                            border: 2px dashed #1a73e8;
                        " onmouseover="this.style.transform='translateY(-3px)'; this.style.boxShadow='0 8px 25px rgba(26, 115, 232, 0.2)'; this.style.background='rgba(26, 115, 232, 0.1)';" onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 4px 15px rgba(26, 115, 232, 0.1)'; this.style.background='rgba(26, 115, 232, 0.05)';" >
                            <img src="https://www.gstatic.com/images/branding/product/1x/google_cloud_48dp.png" width="24" height="24" alt="Cloud Run Logo" />
                            Deploy to Cloud Run
                        </a>
                    </div>
                </div>
            </div>
        </div>
      </div>
    `;

    this.renderMissions();

    // Restore language preference
    const savedLang = localStorage.getItem('immergo_language');
    const savedFromLang = localStorage.getItem('immergo_from_language');

    const toSelect = this.querySelector('#to-lang');
    const fromSelect = this.querySelector('#from-lang');

    if (savedLang) {
      toSelect.value = savedLang;
    } else {
      // 이 앱은 한국어 화자의 영어 연습 전용이다. 저장된 값이 없으면 English로 연습한다.
      const options = Array.from(toSelect.options);
      const englishOption = options.find(o => o.text.includes('English'));
      if (englishOption) toSelect.value = englishOption.text;
    }

    if (savedFromLang) {
      fromSelect.value = savedFromLang;
    } else {
      const options = Array.from(fromSelect.options);
      const koreanOption = options.find(o => o.text.includes('Korean'));
      if (koreanOption) fromSelect.value = koreanOption.text;
    }


    // Mode Logic
    const modeImmersive = this.querySelector('#mode-immersive');
    const modeTeacher = this.querySelector('#mode-teacher');
    let currentMode = localStorage.getItem('immergo_mode') || 'immergo_immersive'; // Default to immersive

    const updateModeUI = () => {
      const activeBorder = 'var(--color-accent-primary)';
      const activeBg = 'rgba(163, 177, 138, 0.1)';

      // Reset styles
      [modeTeacher, modeImmersive].forEach(btn => {
        btn.style.background = 'rgba(255,255,255,0.03)';
        btn.style.borderColor = 'transparent';
        btn.style.boxShadow = 'none';
        btn.querySelector('div > div:first-child').style.color = 'var(--color-text-main)'; // Title
        btn.style.transform = 'translateY(0)';
      });

      // Active State
      const activeBtn = currentMode === 'immergo_teacher' ? modeTeacher : modeImmersive;

      activeBtn.style.background = activeBg;
      activeBtn.style.borderColor = activeBorder;
      activeBtn.style.boxShadow = '0 4px 20px rgba(163, 177, 138, 0.15)';
      activeBtn.querySelector('div > div:first-child').style.color = activeBorder;
      activeBtn.style.transform = 'translateY(-2px)';
    };

    modeImmersive.addEventListener('click', () => {
      currentMode = 'immergo_immersive';
      localStorage.setItem('immergo_mode', currentMode);
      updateModeUI();
    });

    modeTeacher.addEventListener('click', () => {
      currentMode = 'immergo_teacher';
      localStorage.setItem('immergo_mode', currentMode);
      updateModeUI();
    });

    updateModeUI();

    // Free Talk
    const topicInput = this.querySelector('#free-talk-topic');
    const topicCount = this.querySelector('#free-talk-count');
    const topicLimit = this.querySelector('#free-talk-limit');
    const updateTopicCount = () => {
      const length = topicInput.value.length;
      topicCount.textContent = `${length.toLocaleString('en-US')} / ${TOPIC_MAX.toLocaleString('en-US')}`;
      topicLimit.textContent = length >= TOPIC_MAX ? 'Limit reached. Extra text is cut off.' : '';
    };
    topicInput.addEventListener('input', updateTopicCount);

    this.querySelector('#free-talk-start').addEventListener('click', () => {
      const topic = sanitizeTopic(topicInput.value);
      const snippet = topic.replace(/\s+/g, ' ').slice(0, 120);
      this.dispatchEvent(new CustomEvent('navigate', {
        bubbles: true,
        detail: {
          view: 'chat',
          mission: {
            id: 'freetalk',
            type: 'freetalk',
            title: 'Free Talk',
            desc: snippet ? `Topic: ${escapeHtml(snippet)}` : 'Ms. Park will ask what you want to talk about.',
            target_role: 'Ms. Park',
            topic
          },
          language: 'English',
          fromLanguage: 'Korean',
          mode: 'immergo_immersive'
        }
      }));
    });

    // Add change listeners to persist immediately
    fromSelect.addEventListener('change', () => {
      localStorage.setItem('immergo_from_language', fromSelect.value);
    });

    toSelect.addEventListener('change', () => {
      localStorage.setItem('immergo_language', toSelect.value);
    });
  }

  renderMissions() {
    const missions = missionsData;
    const listContainer = this.querySelector('.missions-list');

    const getMissionIcon = (title) => {
      if (title.includes('Teach-back')) return '🧑‍🏫';
      if (title.includes('Coffee')) return '☕';
      if (title.includes('Bus')) return '🚌';
      if (title.includes('dinner')) return '🍕';
      if (title.includes('Shirt')) return '👕';
      if (title.includes('directions')) return '🗺️';
      if (title.includes('Symptoms')) return '🤒';
      if (title.includes('Market')) return '🍎';
      if (title.includes('rent')) return '🏠';
      if (title.includes('Job')) return '💼';
      return '📜';
    };

    missions.forEach(mission => {
      const card = document.createElement('div');
      card.className = 'card mission-card';
      card.style.cursor = 'pointer';

      let badgeColor = '#8bc34a';
      if (mission.difficulty === 'Medium') badgeColor = '#ffc107';
      if (mission.difficulty === 'Hard') badgeColor = '#ff9800';
      if (mission.difficulty === 'Expert') badgeColor = '#f44336';

      // Highlight Easy for the first one if we wanted, but sticking to logic
      if (mission.difficulty === 'Easy') badgeColor = '#8bc34a';


      card.innerHTML = `
        <div style="margin-bottom: var(--spacing-md); display: flex; justify-content: space-between; align-items: start;">
            <div style="font-size: 2.5rem; line-height: 1;">${getMissionIcon(mission.title)}</div>
            <span style="
                background: ${badgeColor}22;
                color: ${badgeColor};
                padding: 4px 8px;
                border-radius: var(--radius-sm);
                font-size: 0.75rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                border: 1px solid ${badgeColor}44;
            ">${mission.difficulty}</span>
        </div>
        <h3 style="margin: 0 0 var(--spacing-sm) 0; font-size: 1.4rem; line-height: 1.2;">${mission.title}</h3>
        <p style="margin: 0; font-size: 0.95rem; opacity: 0.7; line-height: 1.5;">${mission.desc}</p>
        <div style="margin-top: auto; padding-top: var(--spacing-md); font-size: 0.8rem; color: var(--color-accent-secondary); font-weight: bold; opacity: 0.8;">
            Roleplay: ${mission.target_role}
        </div>
      `;

      card.addEventListener('click', () => {
        const toSelect = this.querySelector('#to-lang');
        const fromSelect = this.querySelector('#from-lang');

        const selectedToLang = toSelect.value;
        const selectedFromLang = fromSelect.value;

        // currentMode is defined in the closure above? No, it's local to connectedCallback.
        // We need to re-read it or make it accessible. Let's re-read from localStorage for simplicity and safety
        const selectedMode = localStorage.getItem('immergo_mode') || 'immergo_immersive';

        // Save preference
        localStorage.setItem('immergo_language', selectedToLang);
        localStorage.setItem('immergo_from_language', selectedFromLang);

        this.dispatchEvent(new CustomEvent('navigate', {
          bubbles: true,
          detail: mission.type === 'teachback'
            ? {
              view: 'lesson-prep',
              mission: mission,
              language: selectedToLang,
              fromLanguage: selectedFromLang,
              mode: selectedMode
            }
            : {
              view: 'chat',
              mission: mission,
              language: selectedToLang,
              fromLanguage: selectedFromLang,
              mode: selectedMode
            }
        }));
      });

      listContainer.appendChild(card);
    });
  }
}

customElements.define('view-missions', ViewMissions);
