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

class ViewSplash extends HTMLElement {
  connectedCallback() {
    const startTranslations = [
      "ابدأ", "Comenzar", "Commencer",
      "شروع کرें", "Mulai", "Inizia", "スタート", "시작",
      "Começar", "Начать", "เริ่ม", "Başla", "Bắt đầu", "Почати", "শুরু",
      "साुरु करा", "தொடங்கு", "ప్రారంభించు"
    ];

    this.innerHTML = `
      <style>
        :host {
          display: block;
          position: relative;
          width: 100%;
          min-height: 100vh;
          overflow: hidden;
        }

        .splash-particle {
          position: absolute;
          font-family: 'JetBrains Mono', monospace;
          pointer-events: none;
          opacity: 0;
          animation: floatUp 15s linear infinite;
          color: var(--color-accent-primary);
          font-size: 1.2rem;
          z-index: 0;
          filter: blur(1px);
        }

        @keyframes floatUp {
          0% { transform: translateY(110vh) translateX(0) rotate(0deg); opacity: 0; }
          20% { opacity: 0.3; transform: translateY(80vh) translateX(30px) rotate(45deg); }
          50% { transform: translateY(50vh) translateX(-30px) rotate(90deg); }
          80% { opacity: 0.3; transform: translateY(20vh) translateX(30px) rotate(135deg); }
          100% { transform: translateY(-20vh) translateX(0) rotate(180deg); opacity: 0; }
        }

        .mystic-title {
          /* Adjusted Typography - Single Line Guaranteed */
          font-weight: 800;
          letter-spacing: -0.02em;
          line-height: normal; /* Allow natural height for descenders */
          margin-bottom: var(--spacing-sm);
          padding: 0 var(--spacing-md);
          padding-bottom: 0.3em; /* SIGNIFICANT extra space for descenders */

          /* Gradient & Texture */
          background: linear-gradient(135deg, var(--color-text-main) 30%, var(--color-accent-primary));
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;

          /* Glow/Depth */
          filter: drop-shadow(0 0 30px rgba(163, 177, 138, 0.2));
          position: relative;
          z-index: 10;
          text-align: center;
        }

        .mystic-btn {
          /* Premium Solid Pill */
          position: relative;
          background: var(--color-accent-primary);
          color: #ffffff; /* Always white text on accent for contrast */
          padding: 24px 64px;
          font-size: 1.5rem;
          font-weight: 700;
          border-radius: 9999px; /* Pill shape */
          border: none;

          /* Interaction */
          cursor: pointer;
          transition: all 0.4s cubic-bezier(0.19, 1, 0.22, 1);

          /* Depth */
          box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2),
                      0 0 0 1px rgba(255, 255, 255, 0.1) inset;

          overflow: hidden;
          z-index: 20;
          letter-spacing: 0.02em;
        }

        .mystic-btn:hover {
          transform: translateY(-4px) scale(1.02);
          box-shadow: 0 20px 50px rgba(163, 177, 138, 0.4),
                      0 0 0 2px rgba(255,255,255,0.2) inset;
          background: var(--color-accent-primary); /* Keep background stable */
          filter: brightness(1.1);
        }

        /* Shine Effect on Hover */
        .mystic-btn::after {
          content: '';
          position: absolute;
          top: 0;
          left: 0;
          width: 200%;
          height: 100%;
          background: linear-gradient(
            115deg,
            transparent 0%,
            transparent 45%,
            rgba(255, 255, 255, 0.3) 50%,
            transparent 55%,
            transparent 100%
          );
          transform: translateX(-150%) skewX(-15deg);
          transition: transform 0.6s;
        }

        .mystic-btn:hover::after {
          transform: translateX(150%) skewX(-15deg);
          transition: transform 0.6s ease-in-out;
        }

        .powered-by-link {
          color: var(--color-accent-primary);
          text-decoration: none;
          font-weight: 700;
          border-bottom: 2px solid transparent;
          transition: all 0.2s;
        }

        .powered-by-link:hover {
          border-bottom-color: var(--color-accent-primary);
        }

        .content-wrapper {
          position: relative;
          z-index: 5;
          width: 100%;
          max-width: 1200px;
          min-height: 90vh; /* Ensure full viewport height focus */
          display: flex;
          flex-direction: column;
          justify-content: center;
          align-items: center;
          padding: var(--spacing-xl);
          padding-top: 10vh; /* Shift content down */
          padding-bottom: 15vh; /* Space for footer */
        }
      </style>

      <div class="container flex-center" style="position: relative; min-height: 100vh; flex-direction: column;">

        <!-- Particles container -->
        <div id="particles-host" style="position: absolute; inset: 0; pointer-events: none;"></div>

        <!-- Main Content -->
        <div class="content-wrapper">

          <h1 class="mystic-title">Immersive Language Learning</h1>

          <p style="
            font-family: 'Playfair Display', serif;
            font-style: italic;
            font-size: clamp(1.2rem, 4vw, 2rem);
            opacity: 0.8;
            margin-bottom: var(--spacing-xl);
            color: var(--color-text-sub);
            text-align: center;
            max-width: 600px;
          ">
            Intense immersive language learning experience.
          </p>

          <div style="margin-top: var(--spacing-lg);">
            <p style="font-size: 1.3rem; opacity: 0.6; color: var(--color-text-secondary); text-align: center; line-height: 1.6;">
              Powered by <br>
              <a href="https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api" target="_blank" class="powered-by-link">
                Gemini Live API on Vertex AI
              </a>
            </p>
          </div>

          <!-- CTA Section -->
          <div style="margin-top: calc(var(--spacing-xxl) * 1.5); width: 100%; display: flex; justify-content: center;">
            <button id="start-btn" class="mystic-btn">
              <text-cycler text="Start" values='${JSON.stringify(startTranslations).replace(/'/g, "&apos;").replace(/"/g, "&quot;")}'></text-cycler>
            </button>
          </div>

        </div>

        <!-- Disclaimer Footer -->
        <div style="
          position: absolute; 
          bottom: var(--spacing-lg); 
          left: 0; 
          right: 0;
          font-size: 0.75rem; 
          opacity: 0.5; 
          max-width: 600px; 
          margin: 0 auto; 
          line-height: 1.5; 
          text-align: center;
          padding: 0 var(--spacing-md);
          z-index: 15;
        ">
            <strong>Disclaimer:</strong> This application is for demo purposes only. This is not an official product. May produce inaccurate, unexpected, or offensive results. Present to a live audience at your own risk.
        </div>

      </div>
    `;

    // Create floating language particles
    const host = this.querySelector('#particles-host');
    const particleCount = 30; // Increased count slightly for more depth
    const alphabets = [
      "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ", // Greek
      "अआइईउऊऋएऐओऔकखगघङचछजझञ", // Hindi
      "あいうえおかがきぎくぐけげこご", // Japanese
      "ABCDEFGHIJKLMNOPQRSTUVWXYZ", // Latin
      "אתבגדהוזחטיכלמנסעפצקרשת", // Hebrew
      "가나다라마바사아자차카타파하" // Korean (Added for diversity)
    ];

    for (let i = 0; i < particleCount; i++) {
      const p = document.createElement('div');
      p.className = 'splash-particle';
      const alphabet = alphabets[Math.floor(Math.random() * alphabets.length)];
      p.textContent = alphabet[Math.floor(Math.random() * alphabet.length)];
      p.style.left = `${Math.random() * 100}%`;
      p.style.animationDelay = `${Math.random() * 15}s`;
      p.style.animationDuration = `${10 + Math.random() * 10}s`;
      // Randomize font size more
      p.style.fontSize = `${0.8 + Math.random() * 1.5}rem`;
      host.appendChild(p);
    }

    this.querySelector('#start-btn').addEventListener('click', () => {
      // Transition Effect
      this.style.filter = 'blur(10px) brightness(1.2)';
      this.style.opacity = '0';
      this.style.transform = 'scale(1.05)';
      this.style.transition = 'all 0.6s cubic-bezier(0.19, 1, 0.22, 1)';

      setTimeout(() => {
        this.dispatchEvent(new CustomEvent('navigate', {
          bubbles: true,
          detail: { view: 'missions' }
        }));
      }, 500);
    });
  }
}

customElements.define('view-splash', ViewSplash);
