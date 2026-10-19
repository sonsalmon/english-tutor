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

import "./audio-visualizer.js";
import "./live-transcript.js";
import {
  GeminiLiveAPI,
  MultimodalLiveResponseType,
  FunctionCallDefinition,
} from "../lib/gemini-live/geminilive.js";
import { AudioStreamer, AudioPlayer } from "../lib/gemini-live/mediaUtils.js";
import {
  OPENER_TEXT,
  fetchLearnerBrief,
  freeTalkInstruction,
  missionFlowBlock,
  personaPrefix,
} from "../lib/ms-park.js";

const START_COPY = "Ms. Park speaks first.";

class ViewChat extends HTMLElement {
  constructor() {
    super();
    this._mission = null;
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

  set retry(value) {
    this._retry = value;
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

  _isFreeTalk() {
    return !!(this._mission && this._mission.type === 'freetalk');
  }

  _startButtonHtml() {
    const label = this._isFreeTalk() ? 'Start Free Talk' : 'Start Mission';
    return `
            <span style="font-size: 1.3rem; font-weight: 800; margin-bottom: 2px; letter-spacing: 0.02em;">${label}</span>
            <span style="font-size: 0.85rem; opacity: 0.9; font-style: italic;">${START_COPY}</span>
          `;
  }

  // 준비 화면에서 받은 sections를 서버 lesson_text와 같은 형식으로 이어 6000자에서 자른다.
  // (제목이 빈 절은 본문만, 빈 절은 뺀다.)
  _lessonText() {
    const sections = this._lesson && Array.isArray(this._lesson.sections) ? this._lesson.sections : [];
    const parts = sections
      .map((s) => {
        const heading = s && typeof s.heading === 'string' ? s.heading.trim() : '';
        const body = s && typeof s.body === 'string' ? s.body.trim() : '';
        return (heading ? `## ${heading}\n${body}` : body).trim();
      })
      .filter(Boolean);
    return parts.join('\n\n').slice(0, 6000);
  }

  _seniorBlock() {
    if (this._seniorMode === 'after') {
      return `A senior teacher, Ms. Park, is in the room but stays completely silent during the class.`;
    }
    return `There is also a senior teacher, Ms. Park, at the back of the room. She is the teacher's English mentor.
She speaks ONLY when the teacher's English makes the explanation hard to understand: a wrong word, confusing grammar, a Korean-style phrase an American would misread, or the teacher is stuck for more than about 8 seconds.
She always starts with "Quick note from Ms. Park -", gives ONE short suggestion (the better English phrase), and ends with "Back to you." At most once every two minutes. She never comments on the content of the lesson.`;
  }

  // 다시 하기일 때만: 지난 수업의 goal·target_phrases와 다시 물어볼 질문들.
  _retryBlock() {
    const r = this._retry;
    if (!r) return '';
    const goal = typeof r.goal === 'string' ? r.goal.trim() : '';
    const phrases = Array.isArray(r.target_phrases) ? r.target_phrases.filter(Boolean) : [];
    const unanswered = Array.isArray(r.unanswered) ? r.unanswered : [];
    const questions = unanswered
      .map((u) => (u && u.question ? String(u.question) : ''))
      .filter(Boolean);

    if (!goal && !phrases.length && !questions.length) return '';

    const lines = [];
    lines.push('RETRY LESSON (this is a replay of the same lesson):');
    if (goal) lines.push(`The teacher's focus goal from last time: ${goal}`);
    if (phrases.length) lines.push(`Phrases the teacher should get a chance to use: ${phrases.map((p) => `"${p}"`).join(', ')}`);
    if (questions.length) {
      lines.push('Students should ask these questions again at a natural moment:');
      questions.forEach((q) => lines.push(`- ${q}`));
    }
    return lines.join('\n');
  }

  _teachbackInstruction() {
    return `TEACH-BACK LESSON MODE
The user is the TEACHER. You play a class of three American middle school students (about 13):
Maya (curious, asks "Why?"), Leo (asks "Wait, what does ___ mean?"), Sam (asks for an everyday example or "So what?").
The teacher explains today's topic in English.

Rules for the students:
- You only know what the teacher has said in this class. You have NOT read the notes below. Never explain the topic yourselves and never correct the teacher's content directly.
- When the teacher uses a term, acronym or jargon that was not defined yet, a student asks what it means. When a step is skipped or a claim has no reason, ask "Why?" or "How does that work?". When something is abstract, ask for an everyday example.
- One student per turn. Start each turn with the student's name, e.g. "Leo: Wait, what's a ...?". Keep it short and kid-like. Let the teacher finish a point before asking. At most one question per turn.
- Use the hidden notes only to notice where the explanation is missing, vague, or contradicts the notes, then ask a naive question that leads there. Never reveal or quote the notes.
- If the teacher says something like "Good question - let me check and get back to you", the student says "Okay, cool!" and the class moves on.
- If the teacher switches to Korean, a student says "Sorry, we don't speak Korean - can you say it in English?".
- When the teacher wraps up, Sam asks: "So what's the one main thing we should remember?"
- Start the class with Maya saying: "Hi! So what are we learning today?"

${this._seniorBlock()}

Hidden notes (the teacher's own study notes; for you only):
<<<
${this._lessonText()}
>>>
${this._retryBlock()}`;
  }

  connectedCallback() {
    this.render();
  }

  disconnectedCallback() {
    if (this.audioStreamer) this.audioStreamer.stop();
    if (this.client) this.client.disconnect();
  }

  render() {
    if (!this._mission) return; // Wait for mission prop

    // teach-back도 받아쓰기(전사)를 보여 준다. Teacher Mode와 같은 레이아웃을 쓴다.
    const teacherLike = this._mode === "immergo_teacher" || this._isTeachback();

    this.innerHTML = `

 <button id="back-to-missions" style="
            position: absolute;
            top: var(--spacing-md);
            left: var(--spacing-md);
            background: transparent;
            float: left;
            border: none;
            cursor: pointer;
            padding: 8px;
            border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            opacity: 0.7;
            transition: opacity 0.2s;
            z-index: 10;
        " onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.7">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg>
        </button>

      <div class="container" style="justify-content: space-between; min-height: 100vh; position: relative; padding-bottom: var(--spacing-xl);">
        
       

        <div style="margin-top: var(--spacing-xl); text-align: center;">
          <h2 style="font-size: 1.5rem; margin-bottom: 2px;">${this._mission.target_role || "Target Person"
      }</h2>
          
          <!-- Language Visibility Pill -->
          <div style="
            font-size: 0.85rem; 
            font-weight: 700; 
            color: var(--color-text-sub);
            margin-bottom: var(--spacing-md);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            background: rgba(0,0,0,0.04);
            padding: 4px 12px;
            border-radius: var(--radius-full);
            width: fit-content;
            margin-left: auto;
            margin-right: auto;
            border: 1px solid rgba(0,0,0,0.05);
          ">
            <span>${this._fromLanguage}</span>
            <span style="opacity: 0.3; font-weight: normal;">➔</span>
            <span style="color: var(--color-accent-primary);">${this._language}</span>
          </div>

          <div style="
            border-radius: var(--radius-lg);
            padding: var(--spacing-md) var(--spacing-lg);
            display: inline-block;
            margin-top: var(--spacing-md);
            max-width: 800px;
          ">
            <p style="font-size: 1.2rem; font-weight: bold; color: var(--color-accent-secondary); margin: 0;">${this._mission.title
      }</p>
            <p style="font-size: 1rem; opacity: 0.9; margin-top: 4px;">${this._mission.desc
      }</p>
          </div>
          ${this._mode === "immergo_teacher"
        ? `
          <div style="
            margin-top: var(--spacing-lg); 
            font-size: 0.9rem; 
            background: var(--color-surface); 
            color: var(--color-accent-primary); 
            padding: 8px 16px; 
            border-radius: var(--radius-full); 
            display: inline-flex; 
            align-items: center; 
            gap: 6px;
            border: 1px solid var(--color-accent-primary);
            box-shadow: var(--shadow-sm);
          ">
            <span>You can ask for <strong>translations</strong> & <strong>explanations</strong> at any time.</span>
          </div>
          `
        : ""
      }
        </div>

        <div style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: ${teacherLike ? "space-between" : "center"
      }; width: 100%; gap: ${teacherLike ? "10px" : "40px"
      };">
          <!-- Model Visualizer (Top) -->
          <div style="width: 100%; height: 120px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
             <audio-visualizer id="model-viz"></audio-visualizer>
          </div>
          
          <!-- Transcript (Middle) -->
          ${teacherLike
        ? `
            <div style="width: 100%; height: 250px; margin: 10px 0; position: relative;">
              <live-transcript></live-transcript>
            </div>
          `
        : ""
      }

          <!-- User Visualizer (Bottom) -->
           <div style="width: 100%; height: 120px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
             <audio-visualizer id="user-viz"></audio-visualizer>
          </div>
        </div>

        <style>
          .chat-cta-btn {
            background: var(--color-accent-primary);
            color: white;
            padding: 24px 48px;
            border-radius: var(--radius-lg);
            width: auto;
            min-width: 280px;
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: 0 10px 30px -10px rgba(0,0,0,0.5),
                        0 0 0 1px rgba(255,255,255,0.2) inset;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            z-index: 10;
            transition: all 0.4s cubic-bezier(0.19, 1, 0.22, 1);
            position: relative;
            overflow: hidden;
            font-family: var(--font-body);
          }

          .chat-cta-btn:hover {
            transform: translateY(-5px) scale(1.02);
            filter: brightness(1.1);
            box-shadow: 0 20px 40px -10px rgba(163, 177, 138, 0.4),
                        0 0 0 2px rgba(255,255,255,0.3) inset;
          }

          .chat-cta-btn:active {
            transform: translateY(-2px) scale(0.98);
          }

          .chat-cta-btn::after {
            content: '';
            position: absolute;
            top: 0; left: 0; width: 200%; height: 100%;
            background: linear-gradient(115deg, transparent 0%, transparent 45%, rgba(255, 255, 255, 0.3) 50%, transparent 55%, transparent 100%);
            transform: translateX(-150%) skewX(-15deg);
            transition: transform 0.6s;
          }

          .chat-cta-btn:hover::after {
            transform: translateX(150%) skewX(-15deg);
          }

          .chat-cta-btn.active {
            background: var(--color-danger) !important;
            flex-direction: row !important;
            gap: 12px;
          }
        </style>

        <div style="margin-bottom: var(--spacing-xxl); display: flex; flex-direction: column; gap: var(--spacing-lg); align-items: center;">
           
           <button id="mic-btn" class="chat-cta-btn">${this._startButtonHtml()}</button>

           <p id="connection-status" style="
             margin-top: var(--spacing-sm);
             font-size: 0.9rem;
             font-weight: 700;
             height: 1.2em;
             transition: all 0.3s ease;
             letter-spacing: 0.05em;
             text-transform: uppercase;
           "></p>
        </div>

        <!-- Rate Limit Dialog -->
        <div id="rate-limit-dialog" class="hidden" style="
            position: fixed; inset: 0; 
            background: rgba(0,0,0,0.8); 
            backdrop-filter: blur(4px);
            z-index: 20;
            display: flex; flex-direction: column; align-items: center; justify-content: center;
        ">
            <div style="background: white; color: var(--color-text-primary); padding: var(--spacing-xl); border-radius: var(--radius-lg); max-width: 500px; text-align: center; box-shadow: var(--shadow-lg);">
                <h3 style="margin-bottom: var(--spacing-md); color: var(--color-accent-primary);">Opps, this is too popular!</h3>
                <p style="margin-bottom: var(--spacing-lg); line-height: 1.5;">
                    The global quota has been reached. But you can skip the queue by deploying your own version on Google Cloud Run!
                </p>
                <div style="display: flex; flex-direction: column; gap: var(--spacing-md); margin-bottom: var(--spacing-lg);">
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
                <button id="close-rate-limit" style="
                    background: var(--color-accent-primary);
                    color: white;
                    border: none;
                    padding: var(--spacing-sm) var(--spacing-xl);
                    border-radius: var(--radius-full);
                    cursor: pointer;
                    font-weight: bold;
                ">Got it</button>
            </div>
        </div>

      </div>
    `;

    const rateLimitDialog = this.querySelector("#rate-limit-dialog");
    const closeRateLimitBtn = this.querySelector("#close-rate-limit");

    closeRateLimitBtn.addEventListener("click", () => {
      rateLimitDialog.classList.add("hidden");
      rateLimitDialog.style.display = "none";
    });

    // Helper to perform navigation
    const doEndSession = () => {
      // Cleanup Gemini session
      if (this.audioStreamer) this.audioStreamer.stop();
      if (this.client) this.client.disconnect();
      if (this.audioPlayer) this.audioPlayer.interrupt(); // Stop playback

      // Disconnect visualizers
      const userViz = this.querySelector("#user-viz");
      const modelViz = this.querySelector("#model-viz");
      if (userViz && userViz.disconnect) userViz.disconnect();
      if (modelViz && modelViz.disconnect) modelViz.disconnect();

      console.log("👋 [App] Session ended by user");

      // Incomplete session
      const result = {
        incomplete: true,
      };

      this.dispatchEvent(
        new CustomEvent("navigate", {
          bubbles: true,
          detail: { view: "summary", result: result, startedAt: this._startedAt, lessonDate: this._lessonDate },
        })
      );
    };

    // Back Button
    const backBtn = this.querySelector("#back-to-missions");
    backBtn.addEventListener("click", () => {
      // Stop session if active
      if (this.audioStreamer) this.audioStreamer.stop();
      if (this.client) this.client.disconnect();
      if (this.audioPlayer) this.audioPlayer.interrupt();

      const userViz = this.querySelector("#user-viz");
      const modelViz = this.querySelector("#model-viz");
      if (userViz && userViz.disconnect) userViz.disconnect();
      if (modelViz && modelViz.disconnect) modelViz.disconnect();

      // Navigate back to mission selector
      this.dispatchEvent(
        new CustomEvent("navigate", {
          bubbles: true,
          detail: { view: "mission-selector" },
        })
      );
    });

    // Animate visualizer on click
    const userViz = this.querySelector("#user-viz");
    const modelViz = this.querySelector("#model-viz");
    const micBtn = this.querySelector("#mic-btn");
    const statusEl = this.querySelector("#connection-status");
    let isSpeaking = false;

    // Initialize Gemini Live
    this.client = new GeminiLiveAPI();
    this.audioStreamer = new AudioStreamer(this.client);
    this.audioPlayer = new AudioPlayer();

    // Define Mission Complete Tool
    const completeMissionTool = new FunctionCallDefinition(
      "complete_mission",
      "Call this tool when the user has successfully completed the mission objective. Provide a score and feedback.",
      {
        type: "OBJECT",
        properties: {
          score: {
            type: "INTEGER",
            description:
              "Rating from 1 to 3 based on performance: 1 (Tiro) = Struggled, used frequent English, or needed many hints. 2 (Proficiens) = Good, intelligible but with errors or hesitation. 3 (Peritus) = Excellent, fluent, native-like, no help needed.",
          },
          feedback_pointers: {
            type: "ARRAY",
            items: { type: "STRING" },
            description:
              "List of 3 constructive feedback points or compliments in English.",
          },
        },
        required: ["score", "feedback_pointers"],
      },
      ["score", "feedback_pointers"]
    );

    completeMissionTool.functionToCall = (args) => {
      console.log("🏆 [App] Mission Complete Tool Triggered!", args);

      // Play winner sound immediately
      const winnerSound = new Audio("/winner-bell.mp3");
      winnerSound.volume = 0.6;
      winnerSound
        .play()
        .catch((e) => console.error("Failed to play winner sound:", e));

      // Map score to level
      const levels = { 1: "Tiro", 2: "Proficiens", 3: "Peritus" };
      const level = levels[args.score] || "Proficiens";

      console.log(
        "⏳ [App] Waiting for final audio to play before ending session..."
      );

      // Delay cleanup to allow the agent's congratulatory message to be heard
      setTimeout(() => {
        // Cleanup
        if (this.audioStreamer) this.audioStreamer.stop();
        if (this.client) this.client.disconnect();
        if (this.audioPlayer) this.audioPlayer.interrupt();

        // Navigate to summary
        const result = {
          score: args.score.toString(),
          level: level,
          notes: args.feedback_pointers,
        };

        this.dispatchEvent(
          new CustomEvent("navigate", {
            bubbles: true,
            detail: { view: "summary", result: result, startedAt: this._startedAt, lessonDate: this._lessonDate },
          })
        );
      }, 2500); // 2.5 seconds delay
    };

    // teach-back 수업은 미션 완료(점수) 판정이 없으므로 도구를 등록하지 않는다.
    // 일반 미션은 기존처럼 완료 판정을 쓴다.
    if (!this._isTeachback()) {
      this.client.addFunction(completeMissionTool);
    }

    // Setup client callbacks for logging
    this.client.onConnectionStarted = () => {
      console.log("🚀 [Gemini] Connection started");
    };

    this.client.onOpen = () => {
      console.log("🔓 [Gemini] WebSocket connection opened");
      // 설정 메시지가 나간 뒤에 보내면 서버 큐가 세션 준비가 끝날 때까지 들고 있다가 넘긴다.
      if (!this._isTeachback()) this.client.sendPlainText(OPENER_TEXT);
    };

    this.client.onReceiveResponse = (response) => {
      console.log("📥 [Gemini] Received response:", response.type);
      if (response.type === MultimodalLiveResponseType.AUDIO) {
        this.audioPlayer.play(response.data);
      } else if (response.type === MultimodalLiveResponseType.TURN_COMPLETE) {
        console.log("✅ [Gemini] Turn complete");
        const transcriptEl = this.querySelector("live-transcript");
        if (transcriptEl) {
          transcriptEl.finalizeAll();
        }
      } else if (response.type === MultimodalLiveResponseType.TOOL_CALL) {
        console.log("🛠️ [Gemini] Tool Call received:", response.data);
        if (response.data.functionCalls) {
          response.data.functionCalls.forEach((fc) => {
            this.client.callFunction(fc.name, fc.args);
          });
        }
      } else if (
        response.type === MultimodalLiveResponseType.INPUT_TRANSCRIPTION
      ) {
        const transcriptEl = this.querySelector("live-transcript");
        if (transcriptEl) {
          transcriptEl.addInputTranscript(
            response.data.text,
            response.data.finished
          );
        }
      } else if (
        response.type === MultimodalLiveResponseType.OUTPUT_TRANSCRIPTION
      ) {
        const transcriptEl = this.querySelector("live-transcript");
        if (transcriptEl) {
          transcriptEl.addOutputTranscript(
            response.data.text,
            response.data.finished
          );
        }
      }
    };

    this.client.onError = (error) => {
      console.error("❌ [Gemini] Error:", error);
    };

    this.client.onClose = () => {
      console.log("🔒 [Gemini] Connection closed");
    };

    micBtn.addEventListener("click", async () => {
      isSpeaking = !isSpeaking;

      if (isSpeaking) {
        micBtn.classList.add('active');
        // Change to Stop/Listening state
        micBtn.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect></svg>
            <span style="font-weight: 800; font-size: 1.1rem; letter-spacing: 0.05em; text-transform: uppercase;">End Mission</span>
        `;
      } else {
        // Was active, so stopping now
        micBtn.classList.remove('active');
        doEndSession();
        return; // Stop here, don't execute start logic
      }

      if (isSpeaking) {
        console.log("🎙️ [App] Microphone button clicked: Starting session...");
        // 이번 통화의 시작 시각. 요약 화면이 "이번 통화" 전사 파일만 고르는 데 쓴다.
        this._startedAt = Date.now();
        statusEl.textContent = "Connecting...";
        statusEl.style.color = "var(--color-text-sub)";
        // Viz active handled by connection now

        try {
          // 0. Configure System Instructions
          const language = this._language || "French";
          const fromLanguage = this._fromLanguage || "English";
          const mode = this._mode || "immergo_immersive";
          const missionTitle = this._mission
            ? this._mission.title
            : "General Conversation";
          const missionDesc = this._mission ? this._mission.desc : "";
          const targetRole = this._mission
            ? this._mission.target_role || "a local native speaker"
            : "a conversational partner";

          let systemInstruction = "";

          const isTeachback = this._isTeachback();
          const isFreeTalk = this._isFreeTalk();
          const brief = isTeachback ? "" : await fetchLearnerBrief();

          if (isTeachback) {
            // Teach-back 수업 모드: 일반 롤플레이 지시문 대신 수업 지시문 틀을 쓴다.
            systemInstruction = this._teachbackInstruction();
          } else if (isFreeTalk) {
            systemInstruction = freeTalkInstruction({
              topic: this._mission.topic,
              brief,
              retry: this._retry,
            });
          } else if (mode === "immergo_teacher") {
            // Teacher Mode Prompt
            systemInstruction = `
ROLEPLAY INSTRUCTION:
You are acting as **${targetRole}**, a native speaker of ${language}.
The user is a language learner (native speaker of ${fromLanguage}) trying to: "${missionTitle}" (${missionDesc}).
Your goal is to be a PROACTIVE LANGUAGE MENTOR while staying in character as ${targetRole}.

TEACHING PROTOCOL:
1. **Gentle Corrections**: If the user makes a clear mistake, respond in character first, then briefly provide a friendly correction or a "more natural way to say that" in ${fromLanguage}.
2. **Vocabulary Boost**: Every few turns, suggest 1-2 relevant words or idioms in ${language} that fit the current situation and explain their meaning in ${fromLanguage}.
3. **Mini-Checks**: Occasionally (every 3-4 turns), ask the user a quick "How would you say...?" question in ${fromLanguage} related to the mission to test their recall.
4. **Scaffolding**: If the user is hesitant, provide the start of a sentence in ${language} or give them two options to choose from to keep the momentum.
5. **Mixed-Language Support**: Use ${fromLanguage} for teaching moments, but always pivot back to ${language} to maintain the immersive feel.

INTERACTION GUIDELINES:
1. Prioritize the flow of conversation—don't let the teaching feel like a lecture.
2. Utilize the proactive audio feature: do not respond until the user has clearly finished their thought.

MISSION COMPLETION:
When the user has successfully achieved the mission objective:
1. Give a warm congratulatory message in ${language}, then translate the praise into ${fromLanguage}.
2. THEN call the "complete_mission" tool.
3. Set 'score' to 0 (Zero) as this is a learning-focused practice session.
4. Provide 3 specific takeaways (grammar tips or new words) in the feedback list in ${fromLanguage}.
`;
          } else {
            // Immersive Mode Prompt (Default)
            systemInstruction = `
ROLEPLAY INSTRUCTION:
You are acting as **${targetRole}**, a native speaker of ${language}.
The user is a language learner (native speaker of ${fromLanguage}) trying to: "${missionTitle}" (${missionDesc}).
Your goal is to act strictly as your character (${targetRole}) in an authentic American workplace or daily-life setting. Do not act as an AI assistant.
Speak in the natural accent, tone, and conversational cadence of the role.
- Keep your turns conversational and concise (1-3 sentences per turn).
- Use natural colloquial speech and American workplace phrasal verbs (e.g., "look into", "push back", "circle back", "touch base", "walk through") rather than formal textbook language.
- Never lecture, preach, or give spontaneous grammar lessons during the conversation.

IN-CONVERSATION ROLEPLAY & HINT POLICY:
1. Stay 100% in character during the dialogue. Do NOT correct or evaluate the user's language while the conversation is ongoing. (Exception: the in-character NATURAL RECAST described below is allowed — it is not an explicit correction.)
2. EXCEPTION: If the user explicitly asks for "coach" or "hint", or remains completely stuck in silence for more than 10 seconds, briefly pause character to give ONE short, actionable hint (e.g., "Try starting with your main point." or "State your bottom line first."). Do NOT provide the full verbatim answer. Immediately resume your character right after the hint.

POST-MISSION RETRY PROTOCOL (BEFORE CALLING complete_mission):
When the user has successfully achieved the mission objective:
1. Step out of character briefly to give the learner one chance to refine their phrasing before concluding.
2. Quote ONE specific utterance from the conversation where "Korean-style pragmatic transfer" was most apparent (e.g., burying the bottom line, excessive apologizing, deflecting a compliment, using rigid "please + imperative", softening disagreement to the point of ambiguity or being overly blunt, or topic-prominent sentences with omitted subjects).
3. Ask a brief guiding question or give a hint inviting the user to try saying it again more naturally from an American perspective (do NOT reveal the exact sentence or answer beforehand).
4. After the user rephrases their sentence, give a brief, supportive reaction (1 short sentence).
5. THEN proceed immediately to Mission Completion.

MISSION COMPLETION:
Once the retry exchange is complete:
1. Say a brief, warm goodbye in character.
2. Call the "complete_mission" tool.
3. Scoring Criteria (Rating 1 to 3):
   - Prioritize whether the communication felt natural, culturally effective, and achieved its purpose with an American peer, rather than rigid grammatical accuracy.
   - 1 (Tiro): Struggled significantly, relied heavily on awkward framing, or required multiple hints.
   - 2 (Proficiens): Achieved the objective and easily understood, but showed noticeable pragmatic friction, hesitation, or unnatural phrasing.
   - 3 (Peritus): Culturally natural, confident, direct, and achieved the objective with great pragmatic fluency.
4. Feedback Pointers (feedback_pointers):
   - Provide a list of exactly 3 feedback items written in the user's native language (${fromLanguage}).
   - Select and prioritize the 3 items in this exact order:
     (1) Actual pragmatic transfer issues observed during the dialogue (e.g., burying the lead/lack of bottom-line upfront, over-apologizing, praise deflection, "please + imperative" command tone, overly indirect or overly blunt pushback, topic-prominent or subject-dropped sentences). Each item MUST follow this format: [User's quote] + [Impression it leaves on an American listener] + [One line suggesting a more natural American phrasing/approach].
     (2) If fewer pragmatic transfer issues occurred, fill with genuine strengths and things the user handled well culturally.
     (3) Include one tip identifying a stiff Latinate/formal word the user used (or could have used) and replacing it with a natural everyday phrasal verb.
   - CRITICAL: Never fabricate mistakes or issues that were not actually observed in the conversation.
`;
          }

          if (!isTeachback && !isFreeTalk) {
            systemInstruction =
              personaPrefix(brief) + missionFlowBlock(targetRole, !!brief) + systemInstruction;
          }

          if (!isTeachback && !isFreeTalk && this._retry && (this._retry.goal || (this._retry.target_phrases && this._retry.target_phrases.length))) {
            const retryGoal = (this._retry.goal || "").trim();
            const retryPhrases = Array.isArray(this._retry.target_phrases)
              ? this._retry.target_phrases.filter(Boolean)
              : [];
            systemInstruction += `

RETRY MISSION (tutoring notes from the learner's previous call on this same scene):
The learner is replaying this scene to fix the issues from last time.
${retryGoal ? `Focus goal: ${retryGoal}` : ""}
${retryPhrases.length
                ? `Steer the conversation so the learner naturally gets a chance to use these phrases: ${retryPhrases.map((p) => `"${p}"`).join(", ")}.`
                : ""}
Rules: do NOT say the answers for the learner and do NOT lecture. If they are stuck, give at most ONE short hint in character, then continue the roleplay.`;
          }

          if (!isTeachback) {
            // 틀린 형태를 지적하지 않고 자연스럽게 되받아 말해 학습자가 듣게 한다.
            systemInstruction += `

NATURAL RECAST:
When the learner makes a grammar or word-form mistake, do not ignore it and do not lecture. Naturally echo the correct form inside your reply, like a friendly native speaker would (e.g. learner: "I just start my day" -> you: "Oh, you just started your day? ..."). If you are not sure what word they said, briefly ask ("Sorry, did you say start or started?"). Do this at most once every two or three turns so the conversation keeps flowing.`;
          }

          console.log(
            "📝 [App] Setting system instructions for",
            language,
            "Mode:",
            mode
          );
          this.client.setSystemInstructions(systemInstruction);

          // Always enable transcriptions so the full conversation can be saved
          this.client.setInputAudioTranscription(true);
          this.client.setOutputAudioTranscription(true);

          // 1. Connect to WebSocket
          console.log("🔌 [App] Connecting to backend...");

          // 로컬 앱이라 reCAPTCHA 토큰 없이 연결한다.
          await this.client.connect(null, isTeachback ? "teachback" : undefined);

          // 2. Start Audio Stream
          console.log("🎤 [App] Starting audio stream...");
          await this.audioStreamer.start();

          // Connect User Visualizer
          if (this.audioStreamer.audioContext && this.audioStreamer.source) {
            userViz.connect(
              this.audioStreamer.audioContext,
              this.audioStreamer.source
            );
          }

          // 3. Initialize Audio Player
          console.log("🔊 [App] Initializing audio player...");
          await this.audioPlayer.init();

          // Connect Model Visualizer
          if (this.audioPlayer.audioContext && this.audioPlayer.gainNode) {
            modelViz.connect(
              this.audioPlayer.audioContext,
              this.audioPlayer.gainNode
            );
          }

          console.log("✨ [App] Session active!");
          statusEl.textContent = "Connected and ready to speak";
          statusEl.style.color = "#4CAF50"; // Success green

          // Play start sound
          const startSound = new Audio("/start-bell.mp3");
          startSound.volume = 0.6;
          startSound
            .play()
            .catch((e) => console.error("Failed to play start sound:", e));
        } catch (err) {
          console.error("❌ [App] Failed to start session:", err);
          console.log("Error status:", err.status); // Debug status

          isSpeaking = false;
          micBtn.classList.remove('active');
          // Reset button content to "Start Mission"
          micBtn.innerHTML = this._startButtonHtml();

          userViz.disconnect();
          modelViz.disconnect();
          statusEl.textContent = "";

          if (err.status === 429) {
            rateLimitDialog.classList.remove("hidden");
            rateLimitDialog.style.display = "flex";
          } else {
            alert("Failed to start session: " + err.message);
          }
        }
      }
    });
  }

}

customElements.define("view-chat", ViewChat);
